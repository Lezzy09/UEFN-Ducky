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

A provider can also hand core a ledger per plugin (:meth:`Provider.ledger`): core's
version engine (:mod:`backend.uefn_plugins.vcs_engine`) then syncs that plugin's copy as
changesets, with locks, presence, conflicts and history, and the provider's own
:meth:`Provider.sync` keeps the rest. The provider tells core what it heard about a space
(:func:`remote_event`) and asks whether the space is in active use (:func:`space_active`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Mapping

_log = logging.getLogger(__name__)

# Generic space states. A provider reports one; core decides read-only and closed.
# ``unavailable``: the provider can't use the space now (the sync row's error says why);
# ``reset``: its data was reset on the server. ``no_provider`` (core's own) stays writable.
STATES_READ_ONLY = frozenset({"paused", "waiting", "locked", "lost", "unavailable", "reset"})
STATE_CLOSED = "lost"  # access gone: the copy here reads as empty until it comes back
NO_PROVIDER_ERROR = "Not connected: Ducky Account isn't running"
NO_LEDGER_ERROR = "This copy still syncs the older way: locks, history and restore come once it moves to the new sync."
WORKFLOW_DOCS = "ducky.automations"  # the plugin id workflows are kept under (owned.DOC_PLUGIN)
# What a provider hears about a space (:func:`remote_event`): a new head of a plugin, a
# lock taken or released, someone's presence, a request to release a lock of this PC, the
# space's data reset, an import moving on.
REMOTE_EVENTS = frozenset({"head", "lock", "presence", "ask", "epoch", "import"})


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

    def ledger(self, account: str, space_id: str, plugin: str) -> Any:
        """The remote side of ``plugin``'s copy in the space, as a
        :class:`backend.uefn_plugins.ledger.LedgerBackend` (core's version engine syncs it:
        changesets, locks, presence, history), or None to keep the plugin on :meth:`sync`.
        Asked for every plugin of a space every few seconds, in the app and the MCP bridge:
        answer quickly from what is already known (cache it) and never raise. A
        :meth:`sync` round of the space leaves plugins with a ledger out. Core moves the
        plugin's copy over itself on its first round (a full listing with each imported
        item's ``meta["v1rev"]``); the provider never writes core's tables for it. Once a
        plugin moved, keep returning its ledger, also while the new sync is switched off on
        the server (``Heads.v2`` false): core then keeps it read-only, "Team sync paused"."""
        return None

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


_BAD_LEDGER: set[str] = set()  # providers already logged for answering with something else


def ledger_for(account: str, space: str, plugin: str) -> Any:
    """``plugin``'s ledger backend in the space (:meth:`Provider.ledger`), or None (no
    provider, the older sync, or a provider that failed to answer)."""
    impl = provider()
    try:
        got = impl.ledger(account, space, plugin)
    except Exception:  # noqa: BLE001 — a failing provider keeps the older sync
        _log.debug("ledger of %s in %s failed", plugin, space, exc_info=True)
        return None
    if got is None:
        return None
    from backend.uefn_plugins.ledger import LedgerBackend

    if not isinstance(got, LedgerBackend):
        if provider_plugin() not in _BAD_LEDGER:
            _BAD_LEDGER.add(provider_plugin())
            _log.warning("%s answered ledger() with %s, not a LedgerBackend", provider_plugin(), type(got).__name__)
        return None
    return got


def ledgers(account: str, space: str, plugins: Any) -> dict[str, Any]:
    """``{plugin: ledger backend}`` of the ``plugins`` that have one in the space."""
    out: dict[str, Any] = {}
    for plugin in sorted(set(plugins)):
        got = ledger_for(account, space, plugin)
        if got is not None:
            out[plugin] = got
    return out


def remote_event(account: str, space: str, kind: str, plugin: str | None = None,
                 data: Mapping[str, Any] | None = None) -> None:
    """The provider heard something about a space (``kind``, one of :data:`REMOTE_EVENTS`):
    the background sync looks at the space again soon (heads; a ``head`` of ``plugin`` also
    pulls it). ``ask``: someone asks this PC to release a lock (``data``: ``unit``, and
    ``user_name`` or ``user`` of who asks); the person is told. Only a hint: a missed event
    only delays a pull. Never raises."""
    try:
        if kind not in REMOTE_EVENTS:
            return
        if kind == "ask":
            _asked(account, space, str(plugin or ""), dict(data or {}))
            return
        from backend.uefn_plugins import sync_scheduler

        sync_scheduler.wake(account, space, plugin if kind == "head" and plugin else None)
    except Exception:  # noqa: BLE001 — a hint never breaks the provider's waiter
        _log.debug("remote event %s for %s failed", kind, space, exc_info=True)


def _asked(account: str, space: str, plugin: str, data: dict[str, Any]) -> None:
    """Someone asks this PC to release a lock it holds: an alert, and the plugin's bar hears
    it (it offers Release)."""
    from backend.store.repos import space_vcs

    unit = str(data.get("unit") or "")
    mine = next((lk for lk in space_vcs.locks(account, space, plugin or None, live=False)
                 if lk["unit"] == unit and lk["mine"]), None)
    if mine is None:
        return
    plugin = plugin or str(mine["plugin_id"])
    who = str(data.get("user_name") or data.get("user") or "A teammate")
    name = str(mine["name"] or unit.split(":", 1)[-1])
    label = plugin_label(plugin) or plugin
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "plugin_lock_asked", "plugin_id": plugin, "unit": unit, "unit_name": name,
                       "holder": who})
    except Exception:  # noqa: BLE001 — the alert below still tells the person
        _log.debug("telling the panel about an ask failed", exc_info=True)
    from frontend.notifications import alert

    alert(label, "A teammate asks you to release a lock.", level="ask", detail=f"{who} asks you to release {name}.")


def space_active(account: str, space: str) -> bool:
    """Whether the space is in use on this PC right now: a linked plugin's panel or the
    Workflows view on screen, a change made here in the last 5 minutes, a lock held here,
    or changes still to send. The provider keeps its live channel open only while true."""
    from backend.uefn_plugins import sync_scheduler

    try:
        return sync_scheduler.space_active(account, space)
    except Exception:  # noqa: BLE001 — unsure: not active (heads still come every 15 minutes)
        _log.debug("space_active failed for %s", space, exc_info=True)
        return False


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
    if action == "upload":
        from backend.uefn_plugins import vcs_engine

        vcs_engine.conflicts_into_rows(account, space)  # an unresolved conflict's mine is part of my copy
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
    ``reset``) names everything Upload my copy / Clear my copy act on. The team fields
    (:func:`team_fields`): ``people``, ``locks``, ``changes``, ``conflicts``, ``mode``,
    ``head``, ``nextTry``, ``importing``, and for a lost space ``unsent`` / ``unsentChosen``."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import scopes
    from frontend.duckyos_account import get_status

    scope = scopes.active_scope(plugin)
    account = scope["account"]
    shared = scope["kind"] == "shared"
    out: dict[str, Any] = {
        "ok": True,
        # No bar at all for a plugin that can't share (it keeps its own files, or says
        # data_sharing: false): there is nothing to pick.
        "visible": shared or (scopes.shareable(plugin) and provider().enabled()),
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
            out.update(team_fields(account, scope["id"], plugin, state=scope["state"]))
        except Exception:  # noqa: BLE001 — the bar still shows the rest
            _log.debug("team fields failed for %s", plugin, exc_info=True)
        try:
            out.update(provider().status(account, scope["id"], plugin) or {})
        except Exception:  # noqa: BLE001 — the bar still shows what core knows
            _log.debug("provider status failed for %s", plugin, exc_info=True)
    return out


def _people(account: str, space: str, plugin: str) -> list[dict[str, Any]]:
    """The space's roster (the last heads or beat) as the bar reads it: each person's
    name, PC label and what they do in ``plugin``; ``me`` marks this PC's own row."""
    from backend.store.repos import space_vcs

    roster = space_vcs.presence_get(account, space)["roster"]
    people = roster.get("people") if isinstance(roster, dict) else None
    me = space_vcs.device_id()
    out: list[dict[str, Any]] = []
    for p in people if isinstance(people, list) else []:
        if not isinstance(p, Mapping):
            continue
        plugins = p.get("plugins") if isinstance(p.get("plugins"), Mapping) else {}
        here = plugins.get(plugin) if isinstance(plugins.get(plugin), Mapping) else {}
        editing = [
            {"unitName": str(e.get("unitName") or ""), "actor": "agent" if e.get("actor") == "agent" else "user",
             "ducky": str(e.get("ducky") or ""), "since": float(e.get("since") or 0.0)}
            for e in here.get("editing") or [] if isinstance(e, Mapping)
        ]
        out.append({
            "name": str(p.get("user_name") or p.get("user") or "Someone"),
            "user": str(p.get("user") or ""),
            "device": str(p.get("label") or ""),
            "me": str(p.get("device") or "") == me,
            "plugins": {plugin: {"viewing": bool(here.get("viewing")), "editing": editing}},
        })
    return out


def team_fields(account: str, space: str, plugin: str, *, state: str = "ok") -> dict[str, Any]:
    """What the bar and its drawer show of a team copy, beyond the sync row: ``engine``
    (``v1``: the provider's older sync, ``v2``: the new one), ``changes.outgoing`` with each
    one's state, ``conflicts`` and ``importing`` (%). Only on the new sync: who is in the
    space (``people``), live ``locks`` on this plugin, ``changes.incoming`` changesets and
    ``changes.blocked`` incoming items, ``mode``, ``head`` (the last changeset applied
    here), ``nextTry``; a failed round shows as state ``offline`` / ``error`` with its
    reason, a paused one as ``paused``, and ``pending`` counts only what is queued. A lost
    space adds ``unsent`` (changes never sent) and ``unsentChosen``."""
    import re

    from backend.store.repos import plugin_data as repo
    from backend.store.repos import space_vcs

    now = time.time()
    head = space_vcs.head_get(account, space, plugin)
    v2 = head["engine"] == "v2"
    sending = space_vcs.cs_items_open(account, space, plugin)
    outgoing = []
    for r in repo.pending_items(account, space, plugin):
        queued = r["sync_state"] or ("sending" if (r["kind"], r["key"]) in sending else "queued")
        outgoing.append({"kind": r["kind"], "key": r["key"], "name": r["key"], "size": int(r["size"]),
                         "deleted": bool(r["deleted"]), "state": queued, "reason": r["sync_error"],
                         "attempts": int(r["attempts"])})
    pct = re.search(r"(\d+)%", str(head["error"] or "")) if head["state"] == "importing" else None
    out: dict[str, Any] = {
        "engine": "v2" if v2 else "v1",
        "changes": {"outgoing": outgoing},
        "conflicts": [{"kind": c["kind"], "key": c["key"], "name": c["key"], "unit": c["unit"],
                       "reason": c["reason"], "by": c["theirs_by"], "at": c["theirs_at"],
                       "theirsSeq": int(c["theirs_seq"])} for c in space_vcs.conflicts(account, space, plugin)],
        "importing": float(pct.group(1)) if pct else None,
    }
    if v2:
        out.update(
            head=int(head["seq"]),
            mode=head["mode"],
            people=_people(account, space, plugin),
            locks=[{"unit": lk["unit"], "name": lk["name"] or lk["unit"].split(":", 1)[-1],
                    "holder": lk["holder_name"] or lk["holder_user"], "mine": lk["mine"], "since": lk["since"],
                    "leaseLeft": lk["lease_left"]} for lk in space_vcs.locks(account, space, plugin, now=now)],
            nextTry=float(head["next_try"]) if float(head["next_try"]) > now else None,
            pending=sum(1 for o in outgoing if o["state"] in ("queued", "sending")),
        )
        out["changes"].update(
            incoming=max(0, int(head["remote_seq"]) - int(head["seq"])),
            blocked=[{"kind": b["kind"], "key": b["key"], "name": b["key"], "error": b["error"],
                      "attempts": int(b["attempts"])} for b in space_vcs.blocked(account, space, plugin)],
        )
        if state == "ok" and head["state"] in ("offline", "error", "retry"):
            out.update(state="offline" if head["state"] == "offline" else "error", error=str(head["error"] or ""))
        elif state == "ok" and head["state"] == "paused":
            out.update(state="paused", error=str(head["error"] or ""))
    if state == "lost":
        out.update(unsent=space_vcs.pending_unsent(account, space),
                   unsentChosen=bool(space_vcs.lost_choice_get(account, space)))
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
    """Keep ``plugin``'s data in Local or one shared space (the UI confirmed first). Auto
    locks this PC held on the copy it leaves are released."""
    from backend.uefn_plugins import scopes

    before = scopes.active_scope(plugin)
    scopes.link_plugin(plugin, scope_id)
    if before["kind"] == "shared" and before["id"] != scope_id:
        threading.Thread(target=release_auto_locks, args=(before["account"], before["id"], plugin),
                         name="space-lock-release", daemon=True).start()
    return scope_status(plugin)


def release_auto_locks(account: str, space: str, plugin: str | None = None) -> int:
    """Release the auto locks this PC holds in the space (``plugin``'s only, when given):
    a scope switch, the app closing. Manual locks stay until released. Best effort: a
    lease the server can't hear about runs out within 5 minutes. Returns how many."""
    from backend.store.repos import space_vcs
    from backend.uefn_plugins import vcs_engine

    units: dict[str, list[str]] = {}
    for lk in space_vcs.locks(account, space, plugin, live=False):
        if lk["mine"] and lk["reason"] == "auto":
            units.setdefault(lk["plugin_id"], []).append(lk["unit"])
    for pid, held in units.items():
        backend = ledger_for(account, space, pid)
        if backend is not None:
            vcs_engine.release(account, space, pid, backend, held)
        else:
            space_vcs.lock_delete(account, space, pid, held)
    return sum(len(held) for held in units.values())


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


# --------------------------------------------------------------------------- team copies: the drawer + agents
#
# What the bar's drawer and the agents' team tools do with a plugin's copy on the new
# sync (a ledger): locks, conflicts, history, restore, Auto/Manual, Push and Pull, and the
# unsent changes of a space this account lost.


def _team(plugin: str, *, need_ledger: bool = True) -> tuple[str, str, Any]:
    """``(account, space, ledger)`` of ``plugin``'s shared copy. ValueError with the reason
    when it is Local, or (``need_ledger``) the copy isn't on the new sync."""
    from backend.uefn_plugins import scopes

    if not scopes.valid_plugin_id(plugin):
        raise ValueError(f"invalid plugin id: {plugin!r}")
    scope = scopes.active_scope(plugin)
    if scope["kind"] != "shared":
        raise ValueError(f"{plugin_label(plugin) or plugin}'s data is Local, on this PC only.")
    backend = ledger_for(scope["account"], scope["id"], plugin) if need_ledger else None
    if need_ledger and backend is None:
        raise ValueError(NO_LEDGER_ERROR if has_provider() else NO_PROVIDER_ERROR)
    return scope["account"], scope["id"], backend


def team_unit(plugin: str, unit: str) -> str:
    """A unit as given (``doc:<key>``, ``asset:<path>``, ``tree:...``), or a bare key: the
    doc of that name, else the file of that path."""
    from backend.uefn_plugins import scopes

    unit = str(unit or "").strip()
    kind, sep, key = unit.partition(":")
    if sep and kind in ("doc", "asset", "tree"):
        ok = scopes.valid_doc_key(key) if kind == "doc" else scopes.valid_asset_path(key) if kind == "asset" else bool(key)
        if ok:
            return unit
        raise ValueError(f"invalid unit: {unit!r}")
    if scopes.valid_doc_key(unit) and scopes.PluginData(plugin).get(unit) is not None:
        return f"doc:{unit}"
    if scopes.valid_asset_path(unit) and scopes.PluginData(plugin).has_file(unit):
        return f"asset:{unit}"
    if scopes.valid_doc_key(unit):
        return f"doc:{unit}"
    raise ValueError(f"invalid unit: {unit!r} (use doc:<key> or asset:<path>)")


def _changed(plugin: str) -> None:
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "plugin_scope_changed", "plugins": [plugin]})
    except Exception:  # noqa: BLE001 — the next status read shows it
        _log.debug("announcing a team change failed", exc_info=True)


def team_lock(plugin: str, unit: str, action: str = "acquire", *, name: str = "") -> dict[str, Any]:
    """``acquire`` (a manual lock, kept until released), ``release``, ``break`` (owners and
    admins, or anyone once the lease ran out) or ``ask`` (the holder is asked to release)."""
    from backend.uefn_plugins import vcs_engine

    account, space, backend = _team(plugin)
    unit = team_unit(plugin, unit)
    if action == "acquire":
        got = vcs_engine.acquire(account, space, plugin, backend, [(unit, name or unit.split(":", 1)[-1])])[unit]
        out = {k: v for k, v in got.items() if k != "unit"}
    elif action == "release":
        out = vcs_engine.release(account, space, plugin, backend, [unit])
    elif action == "break":
        out = vcs_engine.break_lock(account, space, plugin, backend, unit)
    elif action == "ask":
        out = vcs_engine.ask(account, space, plugin, backend, unit)
    else:
        raise ValueError("action must be acquire, release, break or ask")
    _changed(plugin)
    return {"unit": unit, **out}


def _conflict_text(account: str, space: str, plugin: str, kind: str, key: str) -> str:
    """Compare: the team's version (current here) against mine, as a line diff of the
    pretty JSON for a doc, of the text for a text file, else sizes and checksums."""
    import difflib
    import json
    from pathlib import Path

    from backend.store.repos import space_vcs
    from backend.uefn_plugins import data_crypto, scopes

    c = space_vcs.conflict_get(account, space, plugin, kind, key)
    if c is None:
        raise ValueError("There is no conflict here any more.")
    row = space_vcs.row(None, account, space, plugin, kind, key)
    live = row is not None and not int(row["deleted"])
    theirs_deleted = bool(int(c["theirs_deleted"])) or not live
    mine_deleted = bool(int(c["mine_deleted"]))
    if kind == "doc":
        def pretty(sealed: str | None) -> list[str]:
            if not sealed:
                return []
            return json.dumps(json.loads(data_crypto.open_text(sealed, account)), indent=2, sort_keys=True,
                              ensure_ascii=False).splitlines()

        theirs = [] if theirs_deleted else pretty(row["value"] if row else None)
        mine = [] if mine_deleted else pretty(c["mine_value"])
    else:
        def text(path: str) -> list[str] | None:
            try:
                raw = data_crypto.open_bytes(Path(path).read_bytes(), account)
                return raw.decode("utf-8").splitlines() if len(raw) <= 1024 * 1024 else None
            except (OSError, UnicodeDecodeError, ValueError):
                return None

        target = str(scopes.asset_file({"account": account, "id": space}, plugin, key))
        theirs = [] if theirs_deleted else text(target)
        mine = [] if mine_deleted or not c["mine_path"] else text(c["mine_path"])
        if theirs is None or mine is None:
            def line(who: str, gone: bool, size: int, sha: str, by: str) -> str:
                return f"{who}: deleted" if gone else f"{who}: {size:,} bytes, sha256 {sha[:12]}{by}"

            by = f", by {c['theirs_by']}" if c["theirs_by"] else ""
            return "\n".join([
                line("Theirs", theirs_deleted, int(row["size"]) if row else 0, str(row["sha256"]) if row else "", by),
                line("Mine", mine_deleted, int(c["mine_size"]), str(c["mine_sha"]), ""),
            ])
    who = c["theirs_by"] or "theirs"
    return "\n".join(difflib.unified_diff(theirs, mine, fromfile=f"{who}'s", tofile="mine", lineterm=""))


def team_resolve(plugin: str, kind: str, key: str, choice: str) -> dict[str, Any]:
    """Settle a conflict: ``mine`` (Keep mine, Restore mine), ``theirs`` (Keep theirs,
    Accept delete), or ``compare`` (``diff``, nothing changes). ``both`` is for folder
    units. What is kept goes out on the next round."""
    from backend.uefn_plugins import vcs_engine

    account, space, _ = _team(plugin, need_ledger=False)
    if kind not in ("doc", "asset"):
        raise ValueError("kind must be doc or asset")
    if choice == "compare":
        return {"ok": True, "diff": _conflict_text(account, space, plugin, kind, key)}
    if choice == "both":
        return {"ok": False, "error": "Keep both is for folder units; pick mine or theirs."}
    out = vcs_engine.resolve(account, space, plugin, kind, key, choice, ledger_for(account, space, plugin))
    if out.get("ok"):
        _changed(plugin)
        sync_space(account, space, force=True)
    return out


def team_restore(plugin: str, *, items: list[Mapping[str, Any]] | None = None, to_seq: int | None = None,
                 undo_seq: int | None = None, message: str = "") -> dict[str, Any]:
    """Items back to their version at a seq, the plugin as of ``to_seq``, or changeset
    ``undo_seq`` undone: a new changeset everyone gets, then pulled here."""
    from backend.uefn_plugins import scopes, vcs_engine

    account, space, backend = _team(plugin)
    if undo_seq:
        out = vcs_engine.undo(account, space, plugin, backend, int(undo_seq), message=message)
    elif items:
        wanted: dict[tuple[str, str], int] = {}
        for it in items:
            kind, key = str(it.get("kind") or ""), str(it.get("key") or "")
            if kind not in ("doc", "asset") or not (scopes.valid_doc_key(key) if kind == "doc"
                                                    else scopes.valid_asset_path(key)):
                raise ValueError(f"invalid item: {kind}:{key}")
            wanted[(kind, key)] = int(it.get("seq") or 0)
        out = vcs_engine.restore(account, space, plugin, backend, items=wanted, message=message)
    elif to_seq is not None and int(to_seq) >= 0:
        out = vcs_engine.restore(account, space, plugin, backend, to_seq=int(to_seq),
                                 message=message or f"Restored to #{int(to_seq)}")
    else:
        raise ValueError("Say what to restore: items, toSeq or undoSeq.")
    if out.get("ok"):
        _changed(plugin)
    return out


def team_history(plugin: str, *, kind: str = "", key: str = "", before: int | None = None,
                 limit: int = 50) -> dict[str, Any]:
    """Changesets newest first, or one item's versions (``kind`` + ``key``), before ``before``."""
    from backend.uefn_plugins import vcs_engine

    account, space, backend = _team(plugin)
    item = (kind, key) if kind and key else None
    out = vcs_engine.history(account, space, plugin, backend, key=item, before=before or None,
                             limit=max(1, min(int(limit or 50), 200)))
    for entry in out.get("entries") or []:
        entry["items"] = [list(i) for i in entry.get("items") or []]
    return out


def team_mode(plugin: str, mode: str) -> dict[str, Any]:
    """Auto (rounds push and pull by themselves) or Manual (only Push and Pull do)."""
    from backend.uefn_plugins import vcs_engine

    account, space, _ = _team(plugin)  # Manual mode is the new sync's; the older one never reads it
    out = vcs_engine.set_mode(account, space, plugin, mode)
    _changed(plugin)
    return out


def team_sync(plugin: str, *, push: bool | None = None, pull: bool | None = None, message: str = "",
              kind: str = "", key: str = "", on_done: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Push (with an optional message) or Pull now, on a worker thread, whatever the mode.
    ``kind`` + ``key``: download that incoming item again first. ``on_done(result)`` after."""
    from backend.store.repos import space_vcs
    from backend.uefn_plugins import vcs_engine

    account, space, backend = _team(plugin)
    if kind and key:
        space_vcs.blocked_retry_now(account, space, plugin, kind, key)

    def _work() -> None:
        try:
            out = vcs_engine.run(account, space, plugin, backend, push=push, pull=pull, force=True, message=message)
        except Exception as exc:  # noqa: BLE001 — recorded like any round that raised
            out = _round_failed({"account": account, "id": space}, exc)
        if on_done is not None:
            on_done(out)

    threading.Thread(target=_work, name="space-team-sync", daemon=True).start()
    return {"ok": True, "started": True}


def save_unsent(plugin: str, action: str = "save") -> dict[str, Any]:
    """A space this account lost: copy this PC's changes never sent into Local (``save``:
    same key when Local has none, else ``<key>-from-<space>``) or let them go with the
    copy (``discard``). Either way the copy here may then leave this PC."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import vcs_engine

    account, space, _ = _team(plugin, need_ledger=False)
    if repo.sync_get(account, space)["state"] != "lost":
        raise ValueError("Only for a space you lost access to.")
    if action == "discard":
        return vcs_engine.discard_unsent(account, space)
    if action != "save":
        raise ValueError("Choose save or discard.")
    out = vcs_engine.save_unsent_to_local(account, space, label=repo.sync_get(account, space)["label"])
    _changed(plugin)
    if any(s["plugin"] == WORKFLOW_DOCS for s in out.get("saved") or []):
        try:
            from frontend.ui_web.agent_modes import push_ui_event

            push_ui_event({"type": "graphs_changed"})
        except Exception:  # noqa: BLE001 — the Workflows view reads it on its next open
            pass
    return out
