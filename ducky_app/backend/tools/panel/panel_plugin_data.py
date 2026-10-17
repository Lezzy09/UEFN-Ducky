"""MCP tool to show or switch where a plugin's data lives (Local or a shared space).

Switching asks the user first, following the app's inline Allow/Deny pattern
(``ducky_ask_user``).
"""

from __future__ import annotations

import json

from backend.server import mcp
from backend.util.json_util import tool_json


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

    ``scope`` empty → report the current scope. ``scope`` of 'local' or a space id →
    move the plugin's data copy there (nothing is copied) and restart it on the new copy.
    """
    from backend.uefn_plugins import scopes
    from backend.uefn_plugins.spaces import provider

    pid = (id or "").strip()
    if not scopes.valid_plugin_id(pid):
        return tool_json({"ok": False, "error": f"invalid plugin id: {id!r}"}, pretty=pretty)
    want = str(scope or "").strip()
    if not want:
        return tool_json({"ok": True, "scope": scopes.scope_view(scopes.active_scope(pid))}, pretty=pretty)
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
