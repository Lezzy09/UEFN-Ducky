"""MCP tools so a ducky can author, share and run Workflows."""

from __future__ import annotations

from typing import Any

from backend.server import mcp
from backend.util.json_util import tool_json


# What one focus event may carry: the editor lights up and frames these nodes.
_FOCUS_MAX_NODES = 60
_NOTE_MAX = 280


def _reveal_graph(workflow_id: str, action: str, *, nodes: list[str] | None = None, select: bool = False, note: str = "") -> None:
    """Open the Workflows editor on this graph. With ``nodes`` the camera glides to them and
    they light up (selected too when ``select``); ``note`` shows as a caption. Panel-closed is a no-op."""
    wid = (workflow_id or "").strip()
    if not wid:
        return
    event: dict[str, Any] = {"type": "graph_focus", "id": wid, "action": action}
    if nodes:
        event["nodes"] = [str(n) for n in nodes][:_FOCUS_MAX_NODES]
    if select:
        event["select"] = True
    if note.strip():
        event["note"] = note.strip()[:_NOTE_MAX]
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event(event)
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
    description: str | None = None,
    enabled: bool | None = None,
    workflow_id: str = "",
    owner: str = "local",
    folder: str | None = None,
    allow_locked_changes: bool = False,
    pretty: bool = False,
) -> str:
    """Create or replace a workflow. Opens the Workflows editor on it, glides to the nodes
    this save added or changed and lights them up, so the user sees what you did.

    graph = {nodes:[{id,type,x,y,config,label,description,color?,icon?,locked?}],
    edges:[{source,target,kind,source_pin?,target_pin?}], groups:[{id,name,node_ids,parent_id?,color?,icon?,locked?}]}.
    White wires: kind main | true | false (after If / Branch) | each | done (after For each).
    Data wires: kind "data" with source_pin (an output) and target_pin (an input) from the
    node's pins in list_workflow_nodes (inputs/outputs with types); one wire per input; a
    wire whose types don't fit is refused with the reason. Nodes with exec:false (Inputs,
    Expression, Ask a model, Preview…) have no white wires: they run when their value is
    needed, and a graph with no start runs every one of them. Unwired inputs take
    config.inputs[pin].
    Cards are 240x82 at x,y; leave ~300 between columns. color: red|amber|green|blue|purple
    (none = by kind). icon: one emoji (none = the kind's icon). Groups are boxes on the canvas;
    a node is in at most one group and parent_id nests a group inside another.
    LOCKED (locked:true on a node or group, or inside a locked group) means the user froze it:
    keep it exactly as it is (spot, settings, wires, group). A save that changes one is refused
    with the names; ask the user, and only after they agree pass allow_locked_changes=true.
    Pass workflow_id to update the same graph. Updating, anything you leave out (graph,
    name, description, enabled) stays as it is; each save refreshes the open canvas.
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
    from backend.automations.locks import changed_nodes, locked_changes
    from backend.automations.store import get_workflow as _get, save_workflow as _save

    wid = (workflow_id or "").strip()
    before = (_get(wid) if wid else None) or {}
    new_graph = graph if graph is not None else before.get("graph") or {"nodes": [], "edges": []}
    from backend.automations.catalog import node_specs
    from backend.automations.pins import check_wires
    from backend.automations.runner import _signature

    misfits = check_wires(new_graph, node_specs(), _signature)
    if misfits:
        return tool_json({"ok": False, "error": "Some data wires don't fit: " + "; ".join(misfits[:10]), "wires": misfits}, pretty=pretty)
    if before and not allow_locked_changes:
        held = locked_changes(before.get("graph"), new_graph)
        if held:
            return tool_json({
                "ok": False,
                "error": "The user locked " + ", ".join(held) + ". Leave locked nodes and groups exactly as they are, "
                "or ask the user; pass allow_locked_changes=true only after they agree.",
                "locked": held,
            }, pretty=pretty)
    doc: dict[str, Any] = {
        "name": name or before.get("name") or "Untitled",
        "description": description if description is not None else str(before.get("description") or ""),
        "enabled": bool(enabled) if enabled is not None else bool(before.get("enabled", True)),
        "graph": new_graph,
    }
    if wid:
        doc["id"] = wid
    if folder is not None:
        doc["folder"] = folder
    try:
        saved = _save(doc, owner=owner)
    except (PermissionError, ValueError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    _reveal_graph(str(saved.get("id") or ""), "saved", nodes=changed_nodes(before.get("graph"), saved.get("graph")))
    return tool_json({"ok": True, "workflow": saved}, pretty=pretty)


@mcp.tool()
def show_workflow(
    workflow_id: str,
    node_ids: list[str] | None = None,
    group_id: str = "",
    note: str = "",
    select: bool = True,
    pretty: bool = False,
) -> str:
    """Show the user part of a workflow in the editor while you explain it.

    Opens the Workflows editor on it, glides the camera to node_ids (or every node of
    group_id), lights them up and, with select=true, selects them so their details panel
    opens. note is a short caption over the canvas ("This Branch checks the score").
    Nothing is saved. Walk someone through a workflow by calling this once per step;
    ducky_walkthrough_run can also spotlight workflows.node.<id> / workflows.group.<id>
    and the editor's buttons (ducky_ui_list_targets("workflows")) with Next / Back.
    """
    from backend.automations.store import get_workflow as _get
    from backend.automations.locks import group_members

    wid = (workflow_id or "").strip()
    wf = _get(wid) if wid else None
    if wf is None:
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    graph = wf.get("graph") or {}
    present = {str(n.get("id")) for n in graph.get("nodes") or []}
    wanted = [str(n) for n in node_ids or []]
    if group_id.strip():
        groups = graph.get("groups") or []
        if not any(g.get("id") == group_id.strip() for g in groups):
            return tool_json({"ok": False, "error": f"group not found: {group_id}"}, pretty=pretty)
        wanted += group_members(groups, group_id.strip())
    shown = [n for n in dict.fromkeys(wanted) if n in present]
    missing = [n for n in dict.fromkeys(wanted) if n not in present]
    _reveal_graph(wid, "show", nodes=shown, select=bool(select) and bool(shown), note=note)
    return tool_json({"ok": True, "shown": shown, "missing": missing}, pretty=pretty)


@mcp.tool()
def move_workflow_folder(owner: str, path: str, new_path: str = "", pretty: bool = False) -> str:
    """Rename or move a folder of the Workflows list, with everything in it.

    owner is "local" or a team id; path is the folder ("Play tests/Tycoon"). new_path is
    where it goes ("Play tests/Lobby" renames it); its parent ("Play tests") or "" for a
    top-level one removes the folder and keeps its workflows."""
    from backend.automations.store import move_folder

    try:
        moved = move_folder(owner, path, new_path)
    except (PermissionError, ValueError) as exc:
        return tool_json({"ok": False, "error": str(exc)}, pretty=pretty)
    return tool_json({"ok": True, "moved": moved}, pretty=pretty)


@mcp.tool()
def clear_workflow_runs(workflow_id: str, pretty: bool = False) -> str:
    """Run log → Clear log: forget this PC's past runs of one workflow."""
    from backend.automations.store import clear_runs

    if not clear_runs(workflow_id):
        return tool_json({"ok": False, "error": "workflow not found"}, pretty=pretty)
    return tool_json({"ok": True}, pretty=pretty)


@mcp.tool()
def list_workflow_versions(workflow_id: str, pretty: bool = False) -> str:
    """Saved versions of a workflow (newest first): id, name, saved_at, node_count, note.
    The editor's History lists the same ones; restore_workflow_version brings one back."""
    from backend.automations.versions import list_versions

    return tool_json({"ok": True, "versions": list_versions(workflow_id)}, pretty=pretty)


@mcp.tool()
def restore_workflow_version(workflow_id: str, version_id: str, allow_locked_changes: bool = False, pretty: bool = False) -> str:
    """Bring back a saved version (name, description, on/off, graph) as a new save; the
    version it replaces stays in History, so this can be undone the same way. Locked
    nodes and groups are respected as in save_workflow."""
    from backend.automations.versions import get_version

    version = get_version(workflow_id, version_id)
    if not version:
        return tool_json({"ok": False, "error": "version not found"}, pretty=pretty)
    return save_workflow(
        graph=version.get("graph") or {"nodes": [], "edges": []},
        name=str(version.get("name") or ""),
        description=str(version.get("description") or ""),
        enabled=bool(version.get("enabled", True)),
        workflow_id=workflow_id,
        allow_locked_changes=allow_locked_changes,
        pretty=pretty,
    )


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
def stop_workflow(workflow_id: str, pretty: bool = False) -> str:
    """Stop every run of a workflow on this PC right away (the editor's Stop button).
    A step that was mid-way (a tool, UEFN, a ducky) finishes in the background, unused."""
    from backend.automations.runner import stop_workflow as _stop

    return tool_json({"ok": True, "stopped": _stop(workflow_id)}, pretty=pretty)


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
