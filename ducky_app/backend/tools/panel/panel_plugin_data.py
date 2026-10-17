"""MCP tools for where a plugin's data lives (Local or a shared space) and its team copy.

``ducky_plugin_data_scope`` shows or switches the copy; switching asks the user first,
following the app's inline Allow/Deny pattern (``ducky_ask_user``).
``ducky_team_status`` says who else is in the plugin's team copy, what is locked, what
waits to go out and what conflicts; ``ducky_team_lock`` takes or releases a lock, so a
ducky can hold an item through a long edit.
"""

from __future__ import annotations

import json
from typing import Any

from backend.server import mcp
from backend.util.json_util import tool_json


def _team_summary(pid: str) -> dict[str, Any]:
    """The scope bar's status, trimmed for an agent: the copy, its state and reason, and for
    a shared copy who is in it, locks, what waits to go out or come in, and conflicts."""
    from backend.uefn_plugins.spaces import scope_status

    st = scope_status(pid)
    out: dict[str, Any] = {"scope": st.get("scope") or {}, "state": st.get("state") or "ok"}
    if (st.get("scope") or {}).get("kind") != "shared":
        return out
    if st.get("error"):
        out["reason"] = st["error"]
    changes = st.get("changes") or {}
    people = []
    for p in st.get("people") or []:
        if p.get("me"):
            continue
        here = (p.get("plugins") or {}).get(pid) or {}
        doing = [f"{'ducky ' + e['ducky'] + ' ' if e.get('actor') == 'agent' else ''}editing {e.get('unitName')}"
                 for e in here.get("editing") or []] or (["viewing"] if here.get("viewing") else [])
        people.append({"name": p.get("name"), "device": p.get("device") or "", "doing": doing})
    out.update(
        mode=st.get("mode") or "auto",
        head=st.get("head") or 0,
        pending=st.get("pending") or 0,
        incoming=changes.get("incoming") or 0,
        people=people,
        locks=[{"unit": lk["unit"], "name": lk.get("name"), "holder": "you" if lk.get("mine") else lk.get("holder"),
                "leaseLeft": round(float(lk.get("leaseLeft") or 0))} for lk in st.get("locks") or []],
        conflicts=[{"kind": c["kind"], "key": c["key"], "reason": c.get("reason"), "by": c.get("by")}
                   for c in st.get("conflicts") or []],
        notSent=[{"kind": o["kind"], "key": o["key"], "state": o["state"], "reason": o.get("reason") or ""}
                 for o in changes.get("outgoing") or [] if o["state"] not in ("queued", "sending")],
    )
    if changes.get("blocked"):
        out["incomingBlocked"] = [{"kind": b["kind"], "key": b["key"], "error": b.get("error")}
                                  for b in changes["blocked"]]
    return out


def _confirm(prompt: str, title: str = "Confirm") -> bool:
    """Ask one Yes/No question inline; True only on an explicit Yes."""
    from backend.tools.panel.panel_ui import ducky_ask_user

    raw = ducky_ask_user(
        [
            {
                "id": "ok",
                "prompt": prompt,
                "options": [
                    {"id": "yes", "label": "Yes"},
                    {"id": "no", "label": "No"},
                ],
                "required": True,
            }
        ],
        title=title,
    )
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if out.get("skipped_all"):
        return False
    ans = (out.get("answers") or {}).get("ok") or {}
    return "yes" in (ans.get("selected") or [])


@mcp.tool()
def ducky_plugin_data_scope(id: str, scope: str = "", pretty: bool = False) -> str:
    """Show or switch where a plugin's data lives (Local or a shared space). Switching asks first.

    ``scope`` empty → report the current scope, its state (ok, offline, error, paused,
    waiting, locked, lost, unavailable, reset, no_provider) and, for a shared copy, who is
    in it, locks, what waits to go out or come in, and conflicts (as ``ducky_team_status``).
    ``scope`` of 'local' or a space id → move the plugin's data copy there (nothing is
    copied) and restart it on the new copy.
    """
    from backend.uefn_plugins import scopes
    from backend.uefn_plugins.spaces import provider

    pid = (id or "").strip()
    if not scopes.valid_plugin_id(pid):
        return tool_json({"ok": False, "error": f"invalid plugin id: {id!r}"}, pretty=pretty)
    want = str(scope or "").strip()
    if not want:
        try:
            return tool_json({"ok": True, **_team_summary(pid)}, pretty=pretty)
        except Exception as exc:  # noqa: BLE001 — the scope alone still answers
            return tool_json({"ok": True, "scope": scopes.scope_view(scopes.active_scope(pid)),
                              "note": f"status unavailable: {exc}"}, pretty=pretty)
    scope_id = scopes.PERSONAL if want.lower() in ("local", "personal") else want
    if scope_id != scopes.PERSONAL and not scopes.sharing_allowed(pid):
        return tool_json({"ok": False, "error": f"'{pid}' keeps its data on this PC only. It can't be shared."},
                         pretty=pretty)
    label ="Local" if scope_id == scopes.PERSONAL else f"{provider().kind_label} {want}"
    if not _confirm(f"Switch '{pid}' data to {label}? Nothing is copied.", title="Switch data"):
        return tool_json({"ok": False, "error": "Cancelled — data scope unchanged."}, pretty=pretty)
    # Same steps as the scope bar's switch (PanelApi.plugin_scope_set): relink, tell the
    # panels, sync, then restart the plugin on the new copy and reload its open panels.
    import threading

    from backend.uefn_plugins.spaces import link_scope, sync_active
    from frontend.ui_web.agent_modes import push_ui_event

    try:
        before = scopes.active_scope(pid)["id"]
        result = link_scope(pid, scope_id)
    except (ValueError, PermissionError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    push_ui_event({"type": "plugin_scope_changed", "plugins": [pid]})
    try:
        sync_active(
            pid,
            force=True,
            on_done=lambda r: push_ui_event(
                {"type": "plugin_scope_changed", "plugins": list(r.get("changed") or []), "synced": True}
            ),
        )
    except Exception:
        pass
    if before != scope_id:

        def _restart() -> None:
            try:
                from backend.uefn_plugins.host import reload_single_plugin

                reload_single_plugin(pid)
            except Exception:
                pass
            push_ui_event({"type": "plugin_scope_changed", "plugins": [pid], "switched": True})

        threading.Thread(target=_restart, name="plugin-scope-restart", daemon=True).start()
    return tool_json({"ok": True, "scope": result}, pretty=pretty)


@mcp.tool()
def ducky_team_status(plugin: str, pretty: bool = False) -> str:
    """Who else is in a plugin's team copy, what is locked, what waits to sync, and conflicts.

    Answers the copy (``scope``) and its ``state`` (``reason`` when not ok); for a shared
    copy also ``people`` (each one's PC and what they do in this plugin: viewing, editing
    an item, or their ducky editing it), ``locks`` (unit, name, holder, seconds left),
    ``pending`` (changes of this PC to send), ``incoming`` (changes waiting to come
    down), ``notSent`` (changes held back, each with why) and ``conflicts``. Check it
    before a long edit of a shared item, and lock with ``ducky_team_lock``.
    """
    from backend.uefn_plugins import scopes

    pid = (plugin or "").strip()
    if not scopes.valid_plugin_id(pid):
        return tool_json({"ok": False, "error": f"invalid plugin id: {plugin!r}"}, pretty=pretty)
    try:
        return tool_json({"ok": True, "plugin": pid, **_team_summary(pid)}, pretty=pretty)
    except Exception as exc:  # noqa: BLE001
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)


@mcp.tool()
def ducky_team_lock(plugin: str, unit: str, action: str = "acquire", pretty: bool = False) -> str:
    """Lock or release one item of a plugin's team copy, so nobody else changes it meanwhile.

    ``unit``: ``doc:<key>`` for a doc, ``asset:<path>`` for a file, or just the key or
    path. ``action``: ``acquire`` (kept until you release it; renewed while the app runs)
    or ``release`` (as soon as your edit is saved). Someone else's lock answers who holds
    it; a copy you're behind on is synced first. Only for a shared copy on the new sync.
    """
    from backend.uefn_plugins import scopes
    from backend.uefn_plugins.spaces import team_lock

    pid = (plugin or "").strip()
    if not scopes.valid_plugin_id(pid):
        return tool_json({"ok": False, "error": f"invalid plugin id: {plugin!r}"}, pretty=pretty)
    if action not in ("acquire", "release"):
        return tool_json({"ok": False, "error": "action must be acquire or release"}, pretty=pretty)
    try:
        return tool_json(team_lock(pid, unit, action), pretty=pretty)
    except (ValueError, PermissionError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
