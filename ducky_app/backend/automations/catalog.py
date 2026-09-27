"""Builtin + enabled-plugin automation / pipeline node catalog."""

from __future__ import annotations

from typing import Any

from backend.automations.store import KIND_AUTOMATION, KIND_PIPELINE, normalize_kind

_BOTH = [KIND_AUTOMATION, KIND_PIPELINE]

BUILTIN_NODES: list[dict[str, Any]] = [
    {
        "type": "start.manual",
        "label": "Manual",
        "group": "Starting",
        "role": "starter",
        "systems": [KIND_AUTOMATION],
        "description": "Run from the editor Test button or run_automation.",
        "config_fields": [],
    },
    {
        "type": "start.cron",
        "label": "Cron / interval",
        "group": "Starting",
        "role": "starter",
        "systems": [KIND_AUTOMATION],
        "description": "Fires while the panel is running. interval_seconds or 5-field cron.",
        "config_fields": [
            {"id": "interval_seconds", "label": "Interval (seconds)", "type": "number"},
            {"id": "cron", "label": "Cron (m h dom mon dow)", "type": "string"},
        ],
    },
    {
        "type": "start.chat",
        "label": "Chat input",
        "group": "Starting",
        "role": "starter",
        "systems": [KIND_PIPELINE],
        "description": "Pass the text and files sent with this pipeline reference into the next step. Optional: any unconnected input can start a pipeline.",
        "config_fields": [],
    },
    {
        "type": "ducky.prompt",
        "label": "Prompt existing ducky",
        "group": "Duckies",
        "role": "action",
        "systems": [KIND_AUTOMATION],
        "description": "Send a prompt to a chat id. Does not switch island.",
        "config_fields": [
            {"id": "conv_id", "label": "Chat id", "type": "string"},
            {"id": "prompt", "label": "Prompt", "type": "textarea"},
            {"id": "mode", "label": "Mode", "type": "string"},
            {"id": "model", "label": "Model", "type": "string"},
        ],
    },
    {
        "type": "ducky.spawn",
        "label": "Spawn ducky",
        "group": "Duckies",
        "role": "action",
        "systems": [KIND_AUTOMATION],
        "description": "Create a chat on the current island and send a prompt.",
        "config_fields": [
            {"id": "title", "label": "Title", "type": "string"},
            {"id": "prompt", "label": "Prompt", "type": "textarea"},
            {"id": "ducky_style", "label": "Ducky style", "type": "string"},
            {"id": "mode", "label": "Mode", "type": "string"},
            {"id": "model", "label": "Model", "type": "string"},
        ],
    },
    {
        "type": "pipeline.agent",
        "label": "Agent",
        "group": "Agents",
        "role": "action",
        "systems": [KIND_PIPELINE],
        "description": "Assign a ducky or create one when this workflow runs. Wait for its result and pass files to the next step.",
        "config_fields": [
            {"id": "ducky", "label": "Assign ducky", "type": "ducky"},
            {"id": "prompt", "label": "Instructions (optional; uses the workflow request)", "type": "textarea"},
        ],
    },
    {
        "type": "pipeline.finish",
        "label": "Return to user",
        "group": "End",
        "role": "end",
        "systems": list(_BOTH),
        "description": "End this path and send its result and files back to the user. In a test run, show the result in the run log.",
        "config_fields": [
            {"id": "message", "label": "Message (optional)", "type": "textarea"},
        ],
    },
    {
        "type": "flow.end",
        "label": "End workflow",
        "group": "End",
        "role": "end",
        "systems": list(_BOTH),
        "description": "End this path without posting a reply.",
        "config_fields": [],
    },
    {
        "type": "flow.wait",
        "label": "Wait",
        "group": "Logic",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Pause this run (capped at 120s).",
        "config_fields": [{"id": "seconds", "label": "Seconds", "type": "number"}],
    },
    {
        "type": "flow.foreach",
        "label": "For each",
        "group": "Logic",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Run the each-wire once per item in a payload list, then follow done.",
        "config_fields": [{"id": "field", "label": "List field", "type": "string"}],
    },
    {
        "type": "flow.branch",
        "label": "Branch",
        "group": "Logic",
        "role": "action",
        "systems": list(_BOTH),
        "description": "True/false edges. Data: field equals / contains / exists. Agent: assigned profile decides.",
        "config_fields": [
            {"id": "mode", "label": "Mode (data or agent)", "type": "string"},
            {"id": "field", "label": "Payload field", "type": "string"},
            {"id": "op", "label": "Op (equals/contains/exists)", "type": "string"},
            {"id": "equals", "label": "Equals (optional)", "type": "string"},
            {"id": "contains", "label": "Contains (optional)", "type": "string"},
            {"id": "ducky", "label": "Judge ducky (agent mode)", "type": "ducky"},
            {"id": "prompt", "label": "Judge prompt (agent mode)", "type": "textarea"},
        ],
    },
    {
        "type": "tool.call",
        "label": "Call tool",
        "group": "Tools",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Call a named host or plugin MCP tool.",
        "config_fields": [
            {"id": "name", "label": "Tool name", "type": "string"},
            {"id": "arguments_json", "label": "Arguments JSON", "type": "textarea"},
        ],
    },
    {
        "type": "uefn.open_project",
        "label": "Open UEFN project",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Start UEFN if closed, select this workspace and wait for the chosen island before continuing.",
        "config_fields": [
            {"id": "project", "label": "UEFN project", "type": "project"},
            {"id": "timeout", "label": "Ready timeout (seconds, max 300)", "type": "number"},
        ],
    },
    {
        "type": "uefn.launch",
        "label": "Launch UEFN",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Start UEFN from closed and select this workspace. Follow with Wait for UEFN before editor actions.",
        "config_fields": [
            {"id": "project", "label": "UEFN project", "type": "project"},
        ],
    },
    {
        "type": "uefn.close",
        "label": "Close UEFN",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "WM_CLOSE, press Save, taskkill only if UEFN is still up.",
        "config_fields": [],
    },
    {
        "type": "uefn.restart",
        "label": "Restart UEFN",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Close UEFN, reopen the project, wait until the listener matches.",
        "config_fields": [
            {"id": "project", "label": "UEFN project", "type": "project"},
            {"id": "timeout", "label": "Wait timeout (seconds)", "type": "number"},
        ],
    },
    {
        "type": "uefn.wait_ready",
        "label": "Wait for UEFN",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Poll until the listener is online and the open island matches (max 300s).",
        "config_fields": [
            {"id": "project", "label": "UEFN project", "type": "project"},
            {"id": "timeout", "label": "Timeout (seconds)", "type": "number"},
        ],
    },
    {
        "type": "uefn.wait_window",
        "label": "Wait for UEFN window",
        "group": "UEFN",
        "role": "action",
        "systems": list(_BOTH),
        "description": "Wait until a UEFN window title matches (max 300s).",
        "config_fields": [
            {"id": "title_regex", "label": "Title regex", "type": "string"},
            {"id": "timeout", "label": "Timeout (seconds)", "type": "number"},
        ],
    },
]


def normalize_systems(raw: Any) -> list[str]:
    if raw in (None, "", []):
        return list(_BOTH)
    items = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, list) else []
    out: list[str] = []
    for item in items:
        key = normalize_kind(item)
        if key not in out:
            out.append(key)
    return out or list(_BOTH)


def node_in_system(node: dict[str, Any], system: str) -> bool:
    want = (system or "").strip().lower()
    if not want:
        return True
    return want in normalize_systems(node.get("systems"))


def list_nodes(system: str = KIND_AUTOMATION) -> list[dict[str, Any]]:
    out = [dict(n) for n in BUILTIN_NODES if node_in_system(n, system)]
    try:
        from backend.uefn_plugins.host import get_ui_contributions
        from backend.uefn_plugins.store import get_enabled_plugin_ids

        enabled = set(get_enabled_plugin_ids())
        contrib = get_ui_contributions()
    except Exception:
        return out
    for row in contrib.get("automations_triggers") or []:
        parsed = _plugin_node(row, enabled, role="starter", default_group="Triggers")
        if parsed and node_in_system(parsed, system):
            out.append(parsed)
    for row in contrib.get("automations_nodes") or []:
        parsed = _plugin_node(row, enabled, role="action", default_group="")
        if parsed and node_in_system(parsed, system):
            out.append(parsed)
    # Read each plugin's own artwork once, even when it contributes many nodes.
    icons: dict[str, str] = {}
    for node in out:
        pid = str(node.get("plugin_id") or "")
        if not pid:
            continue
        if pid not in icons:
            try:
                from backend.uefn_plugins.store import plugin_icon_data_url

                icons[pid] = plugin_icon_data_url(pid) or ""
            except Exception:
                icons[pid] = ""
        node["icon"] = icons[pid] or node.get("icon") or ""
    return out


def starter_types() -> set[str]:
    return {n["type"] for n in list_nodes(system="") if n.get("role") == "starter"}


def _plugin_node(
    row: Any,
    enabled: set[str],
    *,
    role: str,
    default_group: str,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    pid = str(row.get("plugin_id") or "")
    if pid and pid not in enabled:
        return None
    ntype = str(row.get("id") or row.get("type") or "").strip()
    if not ntype:
        return None
    return {
        "type": ntype,
        "label": str(row.get("label") or ntype),
        "group": str(row.get("group") or default_group or pid or "Plugins"),
        "role": role,
        "description": str(row.get("description") or ""),
        "plugin_id": pid,
        "icon": str(row.get("icon") or ""),
        "systems": normalize_systems(row.get("systems")),
        "config_fields": _fields(row.get("config_fields") or row.get("fields")),
    }


def _fields(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for f in raw:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        if not fid:
            continue
        row: dict[str, Any] = {
            "id": fid,
            "label": str(f.get("label") or fid),
            "type": str(f.get("type") or "string"),
        }
        if f.get("provider"):
            row["provider"] = str(f.get("provider") or "")
        opts = f.get("options")
        if isinstance(opts, list):
            clean: list[dict[str, str]] = []
            for opt in opts:
                if isinstance(opt, dict) and (opt.get("id") or opt.get("value")):
                    oid = str(opt.get("id") or opt.get("value") or "")
                    clean.append({"id": oid, "label": str(opt.get("label") or oid)})
                elif isinstance(opt, str) and opt.strip():
                    clean.append({"id": opt, "label": opt})
            if clean:
                row["options"] = clean
        out.append(row)
    return out
