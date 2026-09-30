"""MCP tools so a ducky can author, share and run Workflows."""

from __future__ import annotations

from typing import Any

from backend.server import mcp
from backend.util.json_util import tool_json


def _reveal_graph(workflow_id: str, action: str) -> None:
    """Open the Workflows editor on this graph. Panel-closed is a no-op."""
    wid = (workflow_id or "").strip()
    if not wid:
        return
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "graph_focus", "id": wid, "action": action})
    except Exception:
        pass


@mcp.tool()
def list_workflow_nodes(pretty: bool = False) -> str:
    """Catalog of builtin + enabled-plugin workflow nodes (starters, triggers, actions)."""
    from backend.automations.catalog import list_nodes

    return tool_json({"ok": True, "nodes": list_nodes()}, pretty=pretty)


@mcp.tool()
def list_workflow_templates(pretty: bool = False) -> str:
    """Builtin, plugin and custom workflow templates (ready-made graphs)."""
    from backend.automations.templates import list_templates

    return tool_json({"ok": True, "templates": list_templates()}, pretty=pretty)


@mcp.tool()
def list_workflows(pretty: bool = False) -> str:
    """Saved workflows (id, name, enabled, folder, what starts them) and their owner:
    Local (this PC only) or a team (synced to every member). A reusable workflow
    has a signature: the inputs a Run workflow node passes and the outputs it returns."""
    from backend.automations.store import list_workflows as _list
    from backend.automations.team import owners

    return tool_json({"ok": True, "workflows": _list(), "owners": owners()["owners"]}, pretty=pretty)


@mcp.tool()
def get_workflow(workflow_id: str, pretty: bool = False) -> str:
    """Full workflow graph, owner, and this PC's last run log."""
    from backend.automations.store import get_workflow as _get

    wf = _get(workflow_id)
    if wf is None:
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    return tool_json({"ok": True, "workflow": wf}, pretty=pretty)


@mcp.tool()
def save_workflow(
    graph: dict[str, Any] | None = None,
    name: str = "",
    description: str = "",
    enabled: bool = True,
    workflow_id: str = "",
    owner: str = "local",
    folder: str | None = None,
    pretty: bool = False,
) -> str:
    """Create or replace a workflow. Opens the Workflows editor on this graph.

    graph = {nodes:[{id,type,x,y,config,label,description}], edges:[{source,target,kind}],
    groups:[{id,name,node_ids,parent_id?}]}. Groups are boxes on the canvas; a node is
    in at most one group and parent_id nests a group inside another.
    Pass workflow_id to update the same graph; each save refreshes the open canvas.
    owner picks where a NEW workflow lives: "local" (default, this PC only) or a
    team id from list_workflows owners (shared with that team). An existing
    workflow keeps its owner; use copy_workflow to move it. folder files it in the
    list ("Play tests/Tycoon"; "" = top level); omit it to keep the current folder.

    Reusable workflows (functions): a flow.input node (config inputs=[{name,default}])
    is where a caller's values arrive; flow.output nodes (config outputs=[{name,value}])
    end a path and hand values back (blank value = the field of that name; "{{field}}"
    reads a step's value). Another workflow runs it with a workflow.call node:
    config {workflow_id, args:{input_name: "literal or {{field}}"}, share?}; the returned
    values become fields for the next steps (also under "returned"). share=true runs it
    on a copy of this run's fields and brings every field back. If it has flow.output
    nodes and none is reached, the caller's path stops there.
    """
    from backend.automations.store import save_workflow as _save

    doc: dict[str, Any] = {
        "name": name or "Untitled",
        "description": description,
        "enabled": bool(enabled),
        "graph": graph or {"nodes": [], "edges": []},
    }
    if (workflow_id or "").strip():
        doc["id"] = workflow_id.strip()
    if folder is not None:
        doc["folder"] = folder
    try:
        saved = _save(doc, owner=owner)
    except (PermissionError, ValueError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    _reveal_graph(str(saved.get("id") or ""), "saved")
    return tool_json({"ok": True, "workflow": saved}, pretty=pretty)


@mcp.tool()
def set_workflow_folder(workflow_id: str, folder: str = "", pretty: bool = False) -> str:
    """File a workflow in a folder of the Workflows list without touching its graph.
    folder is a path inside its owner ("Play tests/Tycoon"); "" = top level."""
    from backend.automations.store import set_folder

    try:
        out = set_folder(workflow_id, folder)
    except (PermissionError, ValueError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    if out is None:
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    return tool_json({"ok": True, "workflow": out}, pretty=pretty)


@mcp.tool()
def copy_workflow(workflow_id: str, owner: str, move: bool = False, pretty: bool = False) -> str:
    """Copy a workflow to "local" or a team id (new id), or move it there (move=True).
    Moving a team workflow to local removes it for the team's members."""
    from backend.automations.store import copy_workflow as _copy

    try:
        out = _copy(workflow_id, owner, move=move)
    except KeyError:
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    except (PermissionError, ValueError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    _reveal_graph(str(out.get("id") or ""), "saved")
    return tool_json({"ok": True, "workflow": out}, pretty=pretty)


@mcp.tool()
def delete_workflow(workflow_id: str, pretty: bool = False) -> str:
    """Delete one workflow (for every member, if it is a team's) and close it in the editor."""
    from backend.automations.store import delete_workflow as _delete

    wid = (workflow_id or "").strip()
    try:
        ok = _delete(wid)
    except PermissionError as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    if not ok:
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    _reveal_graph(wid, "deleted")
    return tool_json({"ok": True, "id": wid}, pretty=pretty)


@mcp.tool()
def run_workflow(
    workflow_id: str,
    prompt: str = "",
    files: list[Any] | None = None,
    caller_conv_id: str = "",
    payload: dict[str, Any] | None = None,
    trigger_id: str = "",
    pretty: bool = False,
) -> str:
    """Run a workflow now and open it in the editor. Does not switch the active island.

    From chat: pass the user's request after a workflow reference as prompt, and
    their files. caller_conv_id defaults to the chat running this tool, which gets
    the files and the Return to user result. A reusable workflow takes its inputs
    in payload and gives its Return values back as outputs.
    """
    from backend.automations.runner import run_workflow as _run

    out = _run(
        workflow_id,
        trigger_id=trigger_id,
        payload=payload or {},
        prompt=prompt,
        files=files,
        caller_conv_id=caller_conv_id,
    )
    if out.get("ok"):
        _reveal_graph(workflow_id, "saved")
    return tool_json(out, pretty=pretty)


@mcp.tool()
def emit_workflow_trigger(
    trigger_id: str,
    payload: dict[str, Any] | None = None,
    pretty: bool = False,
) -> str:
    """Simulate a plugin trigger: run every enabled workflow on this PC that listens for trigger_id."""
    from backend.automations.runner import emit_trigger

    return tool_json(emit_trigger(trigger_id, payload or {}), pretty=pretty)


@mcp.tool()
def save_workflow_template(
    name: str,
    description: str = "",
    graph: dict[str, Any] | None = None,
    template_id: str = "",
    icon: str = "⚡",
    pretty: bool = False,
) -> str:
    """Save a reusable custom workflow template (shown in the New workflow picker).

    Pass template_id (custom:…) to replace one. graph uses the same shape as save_workflow.
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
def delete_workflow_template(template_id: str, pretty: bool = False) -> str:
    """Delete a custom:… template. Builtin and plugin templates cannot be deleted."""
    from backend.automations.templates import delete_custom

    if not delete_custom(template_id):
        return tool_json({"ok": False, "error": "template not found"}, pretty=pretty)
    return tool_json({"ok": True, "id": (template_id or "").strip()}, pretty=pretty)
