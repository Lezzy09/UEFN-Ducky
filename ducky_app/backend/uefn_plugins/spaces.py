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
STATES_READ_ONLY = frozenset({"paused", "waiting", "locked", "lost"})
STATE_CLOSED = "lost"  # access gone: the copy here reads as empty until it comes back


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
    (no-op for Local)."""
    from backend.uefn_plugins import scopes

    scope = scopes.active_scope(plugin)
    if scope["kind"] != "shared" or not has_provider():
        return {"ok": True, "started": False}

    def _work() -> None:
        out = provider().sync(scope["account"], scope["id"], force=force)
        if on_done and (out.get("changed") or not out.get("skipped")):
            on_done(out)

    threading.Thread(target=_work, name="space-data-sync", daemon=True).start()
    return {"ok": True, "started": True}


def scope_status(plugin: str) -> dict[str, Any]:
    """Where ``plugin``'s data lives: the host scope bar and the Plugins page. ``visible``
    is false while the account has no shared spaces to offer. ``local`` / ``current`` are
    the Local and the shown copy's counts and bytes."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import scopes
    from frontend.duckyos_account import get_status

    scope = scopes.active_scope(plugin)
    account = scope["account"]
    shared = scope["kind"] == "shared"
    out: dict[str, Any] = {
        "ok": True,
        "visible": shared or provider().enabled(),
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
        out.update(
            members=int(st["members"]),
            error=st["error"],
            syncedAt=float(st["synced_at"]) or None,
            pending=repo.count_dirty(account, scope["id"]),
            usage=st["usage"] or {},
        )
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
