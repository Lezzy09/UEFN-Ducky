"""MCP tools so a ducky can author and test Automations graphs."""

from __future__ import annotations

from typing import Any

from backend.server import mcp
from backend.util.json_util import tool_json


def _reveal_graph(kind: str, workflow_id: str, action: str) -> None:
    """Open the matching editor and show this graph. Panel-closed is a no-op."""
    wid = (workflow_id or "").strip()
    if not wid:
        return
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event(
            {
                "type": "graph_focus",
                "kind": "pipeline" if kind == "pipeline" else "automation",
                "id": wid,
                "action": action,
            }
        )
    except Exception:
        pass


@mcp.tool()
def list_automation_nodes(pretty: bool = False) -> str:
    """Catalog of builtin + enabled-plugin automation nodes and triggers."""
    from backend.automations.catalog import list_nodes

    return tool_json({"ok": True, "nodes": list_nodes(system="automation")}, pretty=pretty)


@mcp.tool()
def list_automation_templates(pretty: bool = False) -> str:
    """Plugin + user Automations templates (ready-made graphs)."""
    from backend.automations.templates import list_templates

    return tool_json({"ok": True, "templates": list_templates(system="automation")}, pretty=pretty)


@mcp.tool()
def list_automations(pretty: bool = False) -> str:
    """List saved Automations workflows (id, name, enabled, updated)."""
    from backend.automations.store import list_automations as _list

    return tool_json({"ok": True, "automations": _list()}, pretty=pretty)


@mcp.tool()
def get_automation(workflow_id: str, pretty: bool = False) -> str:
    """Full automation graph + last run log."""
    from backend.automations.store import get_automation as _get

    wf = _get(workflow_id)
    if wf is None:
        return tool_json({"ok": False, "error": "automation not found"}, pretty=pretty)
    return tool_json({"ok": True, "automation": wf}, pretty=pretty)


@mcp.tool()
def save_automation(
    graph: dict[str, Any] | None = None,
    name: str = "",
    enabled: bool = True,
    workflow_id: str = "",
    pretty: bool = False,
) -> str:
    """Create or replace an automation. Opens the Automations editor on this graph.

    graph = {nodes:[{id,type,x,y,config,label,description}], edges:[{source,target,kind}]}.
    Pass workflow_id to update the same graph; each save refreshes the open canvas.
    """
    from backend.automations.store import save_automation as _save

    doc: dict[str, Any] = {
        "name": name or "Untitled",
        "enabled": bool(enabled),
        "graph": graph or {"nodes": [], "edges": []},
    }
    if (workflow_id or "").strip():
        doc["id"] = workflow_id.strip()
    saved = _save(doc)
    _reveal_graph("automation", str(saved.get("id") or ""), "saved")
    return tool_json({"ok": True, "automation": saved}, pretty=pretty)


@mcp.tool()
def delete_automation(workflow_id: str, pretty: bool = False) -> str:
    """Delete one automation and remove it from the open Automations editor."""
    from backend.automations.store import KIND_AUTOMATION, delete_automation as _delete
    from backend.automations.store import get_automation, normalize_kind

    wid = (workflow_id or "").strip()
    wf = get_automation(wid)
    if wf is None or normalize_kind(wf.get("kind")) != KIND_AUTOMATION:
        return tool_json({"ok": False, "error": "automation not found"}, pretty=pretty)
    if not _delete(wid):
        return tool_json({"ok": False, "error": "automation not found"}, pretty=pretty)
    _reveal_graph("automation", wid, "deleted")
    return tool_json({"ok": True, "id": wid}, pretty=pretty)


@mcp.tool()
def run_automation(
    workflow_id: str,
    trigger_id: str = "",
    payload: dict[str, Any] | None = None,
    pretty: bool = False,
) -> str:
    """Manual test run. Opens the Automations editor on this graph. Does not switch the active island."""
    from backend.automations.runner import run_automation as _run

    out = _run(workflow_id, trigger_id=trigger_id, payload=payload or {})
    if out.get("ok"):
        _reveal_graph("automation", workflow_id, "saved")
    return tool_json(out, pretty=pretty)


@mcp.tool()
def emit_automation(
    trigger_id: str,
    payload: dict[str, Any] | None = None,
    pretty: bool = False,
) -> str:
    """Simulate a plugin trigger: run every enabled workflow that listens for trigger_id."""
    from backend.automations.runner import emit_automation as _emit

    return tool_json(_emit(trigger_id, payload or {}), pretty=pretty)


@mcp.tool()
def list_pipeline_nodes(pretty: bool = False) -> str:
    """Catalog of builtin + enabled-plugin pipeline nodes."""
    from backend.automations.catalog import list_nodes

    return tool_json({"ok": True, "nodes": list_nodes(system="pipeline")}, pretty=pretty)


@mcp.tool()
def list_pipeline_templates(pretty: bool = False) -> str:
    """Plugin + user Pipeline templates (ready-made graphs)."""
    from backend.automations.templates import list_templates

    return tool_json({"ok": True, "templates": list_templates(system="pipeline")}, pretty=pretty)


@mcp.tool()
def list_pipelines(pretty: bool = False) -> str:
    """List saved Pipelines (id, name, description, enabled)."""
    from backend.automations.store import KIND_PIPELINE, list_automations as _list

    return tool_json({"ok": True, "pipelines": _list(kind=KIND_PIPELINE)}, pretty=pretty)


@mcp.tool()
def get_pipeline(pipeline_id: str, pretty: bool = False) -> str:
    """Full pipeline graph + last run log."""
    from backend.automations.store import KIND_PIPELINE, get_automation, normalize_kind

    wf = get_automation(pipeline_id)
    if wf is None or normalize_kind(wf.get("kind")) != KIND_PIPELINE:
        return tool_json({"ok": False, "error": "pipeline not found"}, pretty=pretty)
    return tool_json({"ok": True, "pipeline": wf}, pretty=pretty)


@mcp.tool()
def save_pipeline(
    graph: dict[str, Any] | None = None,
    name: str = "",
    description: str = "",
    enabled: bool = True,
    pipeline_id: str = "",
    pretty: bool = False,
) -> str:
    """Create or replace a pipeline. Opens the Pipelines editor on this graph.

    Same graph shape as automations. Pass pipeline_id to update it; each save
    refreshes the open canvas (positions are node x/y).
    """
    from backend.automations.store import KIND_PIPELINE, save_automation as _save

    doc: dict[str, Any] = {
        "name": name or "Untitled",
        "description": description,
        "enabled": bool(enabled),
        "kind": KIND_PIPELINE,
        "graph": graph or {"nodes": [], "edges": []},
    }
    if (pipeline_id or "").strip():
        doc["id"] = pipeline_id.strip()
    saved = _save(doc)
    _reveal_graph("pipeline", str(saved.get("id") or ""), "saved")
    return tool_json({"ok": True, "pipeline": saved}, pretty=pretty)


@mcp.tool()
def delete_pipeline(pipeline_id: str, pretty: bool = False) -> str:
    """Delete one pipeline and remove it from the open Pipelines editor."""
    from backend.automations.store import KIND_PIPELINE, delete_automation, get_automation, normalize_kind

    wid = (pipeline_id or "").strip()
    wf = get_automation(wid)
    if wf is None or normalize_kind(wf.get("kind")) != KIND_PIPELINE:
        return tool_json({"ok": False, "error": "pipeline not found"}, pretty=pretty)
    if not delete_automation(wid):
        return tool_json({"ok": False, "error": "pipeline not found"}, pretty=pretty)
    _reveal_graph("pipeline", wid, "deleted")
    return tool_json({"ok": True, "id": wid}, pretty=pretty)


@mcp.tool()
def run_pipeline(
    pipeline_id: str,
    prompt: str = "",
    files: list[Any] | None = None,
    caller_conv_id: str = "",
    payload: dict[str, Any] | None = None,
    pretty: bool = False,
) -> str:
    """Run a pipeline from chat. Opens the Pipelines editor when it finishes.

    Stamps caller_conv_id from this run when omitted.
    """
    from backend.automations.runner import run_pipeline as _run

    out = _run(
        pipeline_id,
        prompt=prompt,
        files=files,
        caller_conv_id=caller_conv_id,
        payload=payload or {},
    )
    if out.get("ok"):
        _reveal_graph("pipeline", pipeline_id, "saved")
    return tool_json(out, pretty=pretty)


@mcp.tool()
def save_custom_automation_template(
    name: str,
    description: str = "",
    graph: dict[str, Any] | None = None,
    template_id: str = "",
    icon: str = "⚡",
    pretty: bool = False,
) -> str:
    """Save a reusable custom template. It appears in both Automations and Pipelines pickers.

    Pass template_id (custom:…) to replace one. graph uses the same shape as save_pipeline.
    """
    from backend.automations.templates import save_custom

    try:
        row = save_custom(
            name,
            description=description,
            icon=icon,
            graph=graph,
            template_id=template_id,
        )
    except ValueError as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    return tool_json({"ok": True, "template": row}, pretty=pretty)


@mcp.tool()
def delete_custom_automation_template(template_id: str, pretty: bool = False) -> str:
    """Delete a custom:… template. Builtin and plugin templates cannot be deleted."""
    from backend.automations.templates import delete_custom

    if not delete_custom(template_id):
        return tool_json({"ok": False, "error": "template not found"}, pretty=pretty)
    return tool_json({"ok": True, "id": (template_id or "").strip()}, pretty=pretty)
