"""Shared spaces: copies of plugin data and workflows that live outside Local.

Core keeps every copy on this PC (:mod:`backend.uefn_plugins.scopes` stores a shared
space's rows and files exactly like Local's) and does the bookkeeping a sync needs:
dirty flags, tombstones, revisions, a per-space sync row (label, state, cursor) and a
per-space meta row. A space's state comes from its sync row, which the provider keeps.
Core does not know which spaces exist, who may use them, or how a copy reaches anyone
else.
A provider plugin answers those questions through :class:`Provider`. Without one the
pickers offer only Local and nothing syncs; copies already on this PC stay as they are
(a provider plugin that is updating comes back to them).

One provider at a time. It must come from a Store-signed install (a local build only
when ``DUCKY_DEV_SPACES=1``), because it reads and moves every plugin's shared data.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

_log = logging.getLogger(__name__)

# Generic space states. A provider reports one; core decides read-only and closed.
# ``unavailable``: the provider can't use the space now (the sync row's error says why);
# ``reset``: its data was reset on the server. ``no_provider`` (core's own) stays writable.
STATES_READ_ONLY = frozenset({"paused", "waiting", "locked", "lost", "unavailable", "reset"})
STATE_CLOSED = "lost"  # access gone: the copy here reads as empty until it comes back
NO_PROVIDER_ERROR = "Not connected: Ducky Account isn't running"
WORKFLOW_DOCS = "ducky.automations"  # the plugin id workflows are kept under (owned.DOC_PLUGIN)


class Provider:
    """What a shared-space service adds. Every method has a Local-only default, so a
    provider overrides only what it offers."""

    #: How names read: ``f"{kind_label} {label}"`` in tool results ("space Alpha").
    kind_label = "space"
    #: What a paused (read-only) space's line says in lists.
    paused_label = "Paused"

    # -- plugin data
    def enabled(self) -> bool:
        """Show the space picker and sync line at all (the account can use spaces)."""
        return False

    def choices(self, purpose: str) -> list[dict[str, Any]]:
        """Spaces the account can pick, besides Local. ``purpose``: ``data`` (where a
        plugin's data lives) or ``workflows`` (workflow owners). Each: id, label, and
        any display extras (members, slug)."""
        return []

    def choices_note(self, purpose: str) -> str:
        """What a picker says when there is nothing to pick besides Local."""
        return ""

    def status(self, account: str, space_id: str, plugin: str) -> dict[str, Any]:
        """Extra fields for the scope bar of ``plugin`` while it shows ``space_id``."""
        return {}

    def settle_lost(self, account: str, space_id: str) -> str:
        """A read found the space lost: return its state now (``unavailable`` after the
        provider dropped the copy here, e.g. once access has been gone long enough)."""
        return "lost"

    def linked(self, account: str, plugin: str, space_id: str) -> None:
        """A plugin's data was just pointed at ``space_id`` (record labels, retry access)."""

    def first_pull(self, account: str, space_id: str, timeout: float) -> bool:
        """Bring a space this PC never pulled before a plugin reads it. True once pulled."""
        return False

    def sync(self, account: str, space_id: str, *, force: bool = False) -> dict[str, Any]:
        """One round for the space: ``{state, changed, error}`` (``skipped`` when too soon)."""
        return {"state": "ok", "changed": [], "error": "", "skipped": True}

    def open_web(self, *, space_id: str = "", plugin: str = "", page: str = "") -> dict[str, Any]:
        """Open the space (or its ``page``, e.g. ``workflows`` / ``plugins``) on the web."""
        return {"ok": False, "error": "Nothing to open."}

    def on_login_change(self, keep_account: str) -> None:
        """The signed-in account changed; drop what belonged to other accounts."""

    def reset_for_tests(self) -> None:
        """Forget in-memory state between tests."""

    # -- workflows
    def workflow_spaces(self, account: str) -> list[str]:
        """Spaces whose workflows this account sees (in display order)."""
        return []

    def workflow_edit_refusal(self, account: str, space_id: str, label: str) -> str:
        """Why this account can't change the space's workflows from this PC ("" when it can)."""
        return ""

    def refresh_workflow_spaces(self) -> None:
        """Ask the service which spaces the account has (when the Workflows view opens)."""

    # -- private Store items
    def catalog_item(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Audience fields of one Store catalog item (``audience_id``, ``audience_label``,
        ``mine``). Empty: the item is shown like any public one."""
        return {}

    def catalog_extras(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Catalog-level fields: ``audiences`` (bool: show the Shared category),
        ``audienceNotes`` (per-audience notes), ``audienceCategoryLabel``."""
        return {}


_NULL = Provider()
_LOCK = threading.Lock()
_ACTIVE: dict[str, Any] = {"plugin": "", "provider": _NULL}


def provider() -> Provider:
    """The registered provider, or a Local-only stand-in."""
    return _ACTIVE["provider"]


def provider_plugin() -> str:
    return _ACTIVE["plugin"]


def has_provider() -> bool:
    return _ACTIVE["provider"] is not _NULL


def _trusted(plugin_id: str) -> bool:
    if os.environ.get("DUCKY_DEV_SPACES") == "1":
        return True
    try:
        from backend.uefn_plugins import signing
        from backend.uefn_plugins.store import load_plugin_manifest

        manifest = load_plugin_manifest(plugin_id) or {}
        if str(manifest.get("source") or "") != "store":
            return False
        return bool(signing.installed_record_ok(plugin_id))
    except Exception:  # noqa: BLE001 — an unreadable record is not a signed one
        _log.debug("signed-record check failed for %s", plugin_id, exc_info=True)
        return False


def register(plugin_id: str, impl: Provider) -> None:
    """Make ``impl`` the shared-space provider (``api.provide_spaces``)."""
    if not isinstance(impl, Provider):
        raise TypeError("a spaces provider subclasses backend.uefn_plugins.spaces.Provider")
    if not _trusted(plugin_id):
        raise PermissionError("Only a Store-signed plugin can provide shared spaces.")
    with _LOCK:
        current = _ACTIVE["plugin"]
        if current and current != plugin_id:
            raise PermissionError(f"Shared spaces are already provided by {current}.")
        _ACTIVE.update(plugin=plugin_id, provider=impl)
    _log.info("shared spaces provided by %s", plugin_id)


def unregister(plugin_id: str) -> None:
    """The provider's plugin unloaded: back to Local only."""
    with _LOCK:
        if _ACTIVE["plugin"] == plugin_id:
            _ACTIVE.update(plugin="", provider=_NULL)


def reset_for_tests() -> None:
    try:
        provider().reset_for_tests()
    finally:
        with _LOCK:
            _ACTIVE.update(plugin="", provider=_NULL)


def install_for_tests(impl: Provider, plugin_id: str = "test-spaces") -> None:
    """Tests: register ``impl`` without the signed-install check."""
    with _LOCK:
        _ACTIVE.update(plugin=plugin_id, provider=impl)


# --------------------------------------------------------------------------- host glue


def plugin_label(plugin_id: str) -> str:
    """The plugin's display name, from its manifest. Empty when it has none."""
    try:
        from backend.uefn_plugins.store import load_plugin_manifest

        manifest = load_plugin_manifest(plugin_id) or {}
        label = str(manifest.get("label") or "").strip()
        if label and len(label) <= 80 and all(ord(c) >= 32 for c in label):
            return label
    except Exception:
        return ""
    return ""


def sync_active(plugin: str, *, force: bool = False, on_done: Any = None) -> dict[str, Any]:
    """Start a round for the shared space ``plugin``'s data lives in, on a worker thread
    (no-op for Local). Without a provider nothing can sync, and the answer says so."""
    from backend.uefn_plugins import scopes

    scope = scopes.active_scope(plugin)
    if scope["kind"] != "shared":
        return {"ok": True, "started": False}
    return sync_space(scope["account"], scope["id"], force=force, on_done=on_done)


def sync_space(account: str, space: str, *, force: bool = False, on_done: Any = None) -> dict[str, Any]:
    """:func:`sync_active` for a space by id. The round holds the space's round lock, so
    it never overlaps one of the same space in another process (the MCP bridge)."""
    if not has_provider():
        return {"ok": False, "started": False, "error": NO_PROVIDER_ERROR}

    def _work() -> None:
        from backend.uefn_plugins.sync_scheduler import run_round

        out = run_round(account, space, force=force)
        if on_done and (out.get("changed") or not out.get("skipped")):
            on_done(out)

    threading.Thread(target=_work, name="space-data-sync", daemon=True).start()
    return {"ok": True, "started": True}


def _round_failed(scope: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """A provider's round raised. The space shows the error (the bar says "Not synced" and
    why) and the provider plugin's errors get it with the traceback; before, the thread
    died silently and the bar kept saying when the last round worked."""
    import traceback

    from backend.store.repos import plugin_data as repo

    msg = f"Sync failed: {type(exc).__name__}: {exc}"
    _log.warning("sync of space %s failed", scope["id"], exc_info=True)
    try:
        repo.sync_put(scope["account"], scope["id"], state="error", error=msg[:500])
        from backend.tools.panel.panel_plugin_check import record

        record("plugin_sync_error", provider_plugin(), msg, stack=traceback.format_exc()[-4000:])
    except Exception:  # noqa: BLE001 — reporting must not raise from the sync thread
        _log.debug("recording the sync failure failed", exc_info=True)
    return {"state": "error", "changed": [], "error": msg}


def space_contents(account: str, space: str) -> list[str]:
    """What this PC keeps of a space, by name: each plugin's label, sorted, then
    ``Workflows`` when it holds the space's workflows."""
    from backend.store.repos import plugin_data as repo

    plugins = repo.scope_plugin_ids(account, space)
    names = {plugin_label(plugin) or plugin for plugin in plugins if plugin != WORKFLOW_DOCS}
    return sorted(names, key=str.casefold) + (["Workflows"] if WORKFLOW_DOCS in plugins else [])


def settle_reset(space: str, action: str) -> dict[str, Any]:
    """The person's choice for a space whose data was reset on the server: ``upload``
    (Upload my copy: this PC's copy goes up again as new) or ``clear`` (Clear my copy: it
    goes, rows and files, and the space's data comes down instead). Either one is for the
    space's whole copy here, every plugin's and its workflows, because the provider waits
    for all of it. ``plugins``: the plugin ids whose copy it was."""
    import shutil

    from backend.store.repos import plugin_data as repo
    from backend.store.repos import workflows
    from backend.uefn_plugins import scopes

    if action not in ("upload", "clear"):
        raise ValueError("Choose Upload my copy or Clear my copy.")
    account = scopes.account_id()
    if account == scopes.LOCAL or not scopes.valid_space_id(space):
        raise ValueError("invalid space id")
    sync = repo.sync_get(account, space)
    if sync["state"] != "reset":
        return {"ok": False, "error": f"{sync['label'] or 'This space'}'s data wasn't reset on the server."}
    plugins = repo.scope_plugin_ids(account, space)
    space_workflows = [r["key"] for r in repo.rows(account, space, WORKFLOW_DOCS, "doc")]
    count = repo.settle_reset(account, space, keep=action == "upload")
    if action == "upload":
        return {"ok": True, "plugins": plugins, "queued": count}
    # The copy's files and what this PC derived from it go too; its links and sync row stay.
    workflows.runtime_delete(account, space_workflows)
    try:
        from backend.store.repos import search as search_repo

        search_repo.drop_scope_records(account, space)
    except Exception:  # noqa: BLE001 — a search error never blocks the clear
        _log.debug("dropping search records of %s failed", space, exc_info=True)
    shutil.rmtree(scopes.scopes_root(account) / space, ignore_errors=True)
    return {"ok": True, "plugins": plugins, "cleared": count}


def scope_status(plugin: str) -> dict[str, Any]:
    """Where ``plugin``'s data lives: the host scope bar and the Plugins page. ``visible``
    is false while the account has no shared spaces to offer, and always for a plugin
    that never shares its data (``"data_sharing": false``). ``shareable`` is false for a
    plugin that keeps its own files (:func:`scopes.shareable`): no space is offered and
    the bar says Local only. ``local`` / ``current`` are the Local and the shown copy's
    counts and bytes.

    For a shared copy: ``pending`` is this plugin's changes still to send; ``refused``,
    ``blocked`` and ``conflict`` count its changes that aren't going out, listed in
    ``items`` (kind, key, state, reason, attempts, deleted). ``resetContents`` (state
    ``reset``) names everything Upload my copy / Clear my copy act on."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import scopes
    from frontend.duckyos_account import get_status

    scope = scopes.active_scope(plugin)
    account = scope["account"]
    shared = scope["kind"] == "shared"
    out: dict[str, Any] = {
        "ok": True,
        "visible": shared or (scopes.sharing_allowed(plugin) and provider().enabled()),
        "shareable": shared or scopes.shareable(plugin),
        "kindLabel": provider().kind_label,
        "scope": scopes.scope_view(scope),
        "pluginLabel": plugin_label(plugin) or plugin,
        "email": str(get_status().get("email") or ""),
        "canChange": account != scopes.LOCAL,
        "state": scope["state"],
        "local": repo.totals(account, scopes.PERSONAL, plugin),
        "current": repo.totals(account, scope["id"], plugin),
    }
    if shared:
        st = repo.sync_get(account, scope["id"])
        held = repo.state_counts(account, scope["id"], plugin)
        out.update(
            members=int(st["members"]),
            error=NO_PROVIDER_ERROR if scope["state"] == "no_provider" else st["error"],
            syncedAt=float(st["synced_at"]) or None,
            pending=repo.count_dirty(account, scope["id"], plugin),
            refused=held["refused"],
            blocked=held["blocked"],
            conflict=held["conflict"],
            items=[
                {"kind": r["kind"], "key": r["key"], "state": r["sync_state"], "reason": r["sync_error"],
                 "attempts": int(r["attempts"]), "deleted": bool(r["deleted"])}
                for r in repo.state_items(account, scope["id"], plugin)
            ],
            usage=st["usage"] or {},
        )
        if scope["state"] == "reset":
            out["resetContents"] = space_contents(account, scope["id"])
        try:
            out.update(provider().status(account, scope["id"], plugin) or {})
        except Exception:  # noqa: BLE001 — the bar still shows what core knows
            _log.debug("provider status failed for %s", plugin, exc_info=True)
    return out


def scope_choices(purpose: str = "data") -> dict[str, Any]:
    """Local, plus the spaces the provider offers for ``purpose``. Pickers only."""
    from backend.uefn_plugins import scopes

    choices: list[dict[str, Any]] = [{"id": scopes.PERSONAL, "kind": "personal", "label": "Local"}]
    if scopes.account_id() != scopes.LOCAL:
        for row in provider().choices(purpose) or []:
            sid = str((row or {}).get("id") or "")
            if scopes.valid_space_id(sid):
                choices.append({**row, "id": sid, "kind": "shared", "label": str(row.get("label") or sid)})
    return {"ok": True, "choices": choices, "kindLabel": provider().kind_label,
            "emptyNote": provider().choices_note(purpose)}


def link_scope(plugin: str, scope_id: str) -> dict[str, Any]:
    """Keep ``plugin``'s data in Local or one shared space (the UI confirmed first)."""
    from backend.uefn_plugins import scopes

    scopes.link_plugin(plugin, scope_id)
    return scope_status(plugin)


def on_account_change(before: str, after: str) -> None:
    """Sign-in, sign-out or another account (account ids). Every plugin that showed a
    shared space's copy, or shows one now, restarts on the copy it reads now and its
    open panels reload, like a switch: signing out puts them all on Local instead of
    leaving the space's data on screen."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import scopes

    plugins = sorted(
        {
            plugin
            for account in {before, after} - {scopes.LOCAL}
            for plugin, space in repo.links(account).items()
            if scopes.valid_space_id(space) and scopes.sharing_allowed(plugin)
        }
    )
    if not plugins:
        return

    def _work() -> None:
        from backend.uefn_plugins.host import reload_single_plugin
        from backend.uefn_plugins.store import get_enabled_plugin_ids
        from frontend.ui_web.agent_modes import push_ui_event

        enabled = set(get_enabled_plugin_ids())
        for plugin in plugins:
            if plugin in enabled:
                try:
                    reload_single_plugin(plugin)
                except Exception:  # noqa: BLE001 — its panels still reload on the new copy
                    _log.debug("restart after account change failed for %s", plugin, exc_info=True)
        push_ui_event({"type": "plugin_scope_changed", "plugins": plugins, "switched": True})

    threading.Thread(target=_work, name="space-account-change", daemon=True).start()
