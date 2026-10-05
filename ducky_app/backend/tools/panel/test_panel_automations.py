"""Workflow MCP tools open the editor, refuse unknown owners, and manage templates."""

from __future__ import annotations

import json
import asyncio
import contextvars
import threading


def test_workflow_runner_keeps_mcp_loop_responsive(monkeypatch):
    from backend.tools.panel import panel_automations as panel

    caller = contextvars.ContextVar("test_workflow_caller")
    monkeypatch.setattr(panel, "_reveal_graph", lambda *args, **kwargs: None)

    async def check():
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        caller.set("calling-chat")

        async def diagnostic():
            return "diagnostics returned"

        def runner(*args, **kwargs):
            assert threading.get_ident() != loop_thread
            assert caller.get() == "calling-chat"
            # Reproduce the worker agent requesting tools from the same loop.
            result = asyncio.run_coroutine_threadsafe(diagnostic(), loop).result(timeout=2)
            return {"ok": True, "evidence": result}

        monkeypatch.setattr("backend.automations.runner.run_workflow", runner)
        monkeypatch.setattr("backend.automations.runner.run_node", runner)
        for request in (panel.run_workflow("demo", caller_conv_id="calling-chat"),
                        panel.run_workflow_node("demo", "build")):
            result = json.loads(await request)
            assert result["ok"] is True
            assert result["evidence"] == "diagnostics returned"

    asyncio.run(check())


def _events(monkeypatch) -> list[dict]:
    events: list[dict] = []
    monkeypatch.setattr("frontend.ui_web.agent_modes.push_ui_event", events.append)
    return events


def test_save_workflow_opens_editor_in_local(monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import save_workflow

    events = _events(monkeypatch)
    raw = save_workflow(
        name="Live",
        graph={"nodes": [{"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}}], "edges": []},
    )
    doc = json.loads(raw)
    wid = doc["workflow"]["id"]
    try:
        assert doc["ok"] is True
        assert doc["workflow"]["owner"]["kind"] == "local"
        # The editor opens on it and frames what was added.
        assert {"type": "graph_focus", "id": wid, "action": "saved", "nodes": ["s"]} in events
    finally:
        delete_workflow(wid)


def test_delete_workflow_asks_the_user_first_then_opens_editor(monkeypatch):
    from backend.automations.store import get_workflow
    from backend.tools.panel.panel_automations import delete_workflow, save_workflow

    events = _events(monkeypatch)
    wid = json.loads(save_workflow(name="Gone", graph={"nodes": [], "edges": []}))["workflow"]["id"]
    events.clear()
    refused = json.loads(delete_workflow(wid))
    assert refused["ok"] is False and refused["needs_confirmation"] is True
    assert "ducky_ask_user" in refused["error"] and "“Gone”" in refused["error"]
    assert get_workflow(wid) is not None and events == []  # nothing deleted without the user's yes
    out = json.loads(delete_workflow(wid, confirmed=True))
    assert out == {"ok": True, "id": wid}
    assert {"type": "graph_focus", "id": wid, "action": "deleted"} in events
    assert json.loads(delete_workflow(wid, confirmed=True))["ok"] is False
    assert json.loads(delete_workflow(wid))["error"] == "workflow not found"


def test_delete_workflow_needs_no_second_yes_when_the_chat_allows_everything(monkeypatch):
    from backend.automations.store import get_workflow
    from backend.tools.panel import panel_automations
    from backend.tools.panel.panel_automations import delete_workflow, save_workflow

    _events(monkeypatch)
    wid = json.loads(save_workflow(name="Gone too", graph={"nodes": [], "edges": []}))["workflow"]["id"]
    monkeypatch.setattr(panel_automations, "_chat_allows_everything", lambda: True)
    assert json.loads(delete_workflow(wid)) == {"ok": True, "id": wid}
    assert get_workflow(wid) is None


def test_find_workflows_then_make_one_from_a_template(monkeypatch):
    from backend.automations.store import delete_workflow as _delete
    from backend.tools.panel.panel_automations import create_workflow_from_template, find_workflows, save_workflow

    events = _events(monkeypatch)
    mine = json.loads(save_workflow(name="Chest prop to UEFN", description="Makes a 3D chest and imports it", graph={"nodes": [], "edges": []}))["workflow"]["id"]
    try:
        found = json.loads(find_workflows("make a 3D chest model for UEFN"))
        assert found["ok"] and found["workflows"][0]["id"] == mine and "run_workflow" in found["hint"]
        assert found["templates"][0]["id"] == "builtin:pipe-prompt-3d-uefn"
        nothing = json.loads(find_workflows("zzz qqq"))
        assert nothing["workflows"] == [] and nothing["templates"] == [] and "Nothing fits" in nothing["hint"]
        made = json.loads(create_workflow_from_template("builtin:pipe-sprite-sheet", name="My sheet"))
        assert made["ok"], made
        wid = made["workflow"]["id"]
        try:
            assert made["workflow"]["name"] == "My sheet" and len(made["workflow"]["graph"]["nodes"]) == 3
            assert any(e.get("type") == "graph_focus" and e.get("id") == wid for e in events)  # the editor opens on it
        finally:
            _delete(wid)
        assert json.loads(create_workflow_from_template("builtin:nope"))["ok"] is False
    finally:
        _delete(mine)


def test_save_workflow_refuses_an_unknown_team(monkeypatch):
    from backend.tools.panel.panel_automations import list_workflows, save_workflow

    _events(monkeypatch)
    out = json.loads(save_workflow(name="Shared", graph={"nodes": [], "edges": []}, owner="team_nobody"))
    assert out["ok"] is False and "unknown workflow owner" in out["error"]
    listed = json.loads(list_workflows())
    assert [o["kind"] for o in listed["owners"]] == ["local"]  # signed out: Local only
    assert all(w["name"] != "Shared" for w in listed["workflows"])


def test_custom_template_roundtrip(monkeypatch):
    from backend.tools.panel.panel_automations import delete_workflow_template, save_workflow_template

    events = _events(monkeypatch)
    raw = save_workflow_template(
        name="Starter",
        graph={"nodes": [{"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}}], "edges": []},
    )
    doc = json.loads(raw)
    tid = doc["template"]["id"]
    try:
        assert doc["ok"] is True
        assert any(e.get("type") == "templates_changed" for e in events)
        assert json.loads(delete_workflow_template(tid))["ok"] is True
    finally:
        delete_workflow_template(tid)


def _graph():
    return {
        "nodes": [
            {"id": "s", "type": "start.manual", "x": 0, "y": 0, "config": {}},
            {"id": "a", "type": "flow.wait", "x": 280, "y": 0, "config": {"seconds": 1}, "label": "Pause", "locked": True},
            {"id": "b", "type": "flow.wait", "x": 560, "y": 0, "config": {}},
            {"id": "c", "type": "flow.wait", "x": 840, "y": 0, "config": {}},
        ],
        "edges": [{"source": "s", "target": "a", "kind": "main"}],
        "groups": [{"id": "g", "name": "Tail", "node_ids": ["c"], "locked": True}],
    }


def test_save_workflow_keeps_what_an_update_leaves_out(monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import save_workflow

    _events(monkeypatch)
    wid = json.loads(save_workflow(name="Keep", description="Checks the lobby", enabled=False, graph=_graph()))["workflow"]["id"]
    try:
        out = json.loads(save_workflow(workflow_id=wid, name="Renamed"))
        assert out["ok"] is True
        wf = out["workflow"]
        assert wf["name"] == "Renamed" and wf["description"] == "Checks the lobby" and wf["enabled"] is False
        assert [n["id"] for n in wf["graph"]["nodes"]] == ["s", "a", "b", "c"]  # the graph was not wiped
    finally:
        delete_workflow(wid)


def test_save_workflow_holds_agents_to_the_users_locks(monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import save_workflow

    events = _events(monkeypatch)
    wid = json.loads(save_workflow(name="Locked", graph=_graph()))["workflow"]["id"]
    try:
        moved = _graph()
        moved["nodes"][1]["x"] = 999
        moved["nodes"][3]["config"] = {"seconds": 5}
        out = json.loads(save_workflow(workflow_id=wid, graph=moved))
        assert out["ok"] is False and out["locked"] == ["Pause", "flow.wait"]
        unlocked_ok = _graph()
        unlocked_ok["nodes"][2]["x"] = 600
        events.clear()
        assert json.loads(save_workflow(workflow_id=wid, graph=unlocked_ok))["ok"] is True
        assert events[-1] == {"type": "graph_focus", "id": wid, "action": "saved", "nodes": ["b"]}  # only what changed
        assert json.loads(save_workflow(workflow_id=wid, graph=moved, allow_locked_changes=True))["ok"] is True
    finally:
        delete_workflow(wid)


def test_show_workflow_points_the_editor_at_nodes_and_groups(monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import save_workflow, show_workflow

    events = _events(monkeypatch)
    wid = json.loads(save_workflow(name="Tour", graph=_graph()))["workflow"]["id"]
    try:
        events.clear()
        out = json.loads(show_workflow(wid, node_ids=["a", "zz"], note="This waits a second"))
        assert out == {"ok": True, "shown": ["a"], "missing": ["zz"]}
        assert events == [{"type": "graph_focus", "id": wid, "action": "show", "nodes": ["a"], "select": True, "note": "This waits a second"}]
        assert json.loads(show_workflow(wid, group_id="g", select=False))["shown"] == ["c"]
        assert json.loads(show_workflow(wid, group_id="nope"))["ok"] is False
        assert json.loads(show_workflow("missing-id"))["ok"] is False
    finally:
        delete_workflow(wid)


def test_save_workflow_refuses_data_wires_that_do_not_fit(monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import save_workflow

    _events(monkeypatch)
    graph = {
        "nodes": [
            {"id": "n", "type": "input.number", "x": 0, "y": 0, "config": {"value": 3}},
            {"id": "img", "type": "input.image", "x": 300, "y": 0, "config": {}},
            {"id": "p", "type": "util.preview", "x": 600, "y": 0, "config": {}},
            {"id": "c", "type": "logic.compare", "x": 600, "y": 200, "config": {}},
        ],
        "edges": [
            {"source": "img", "target": "c", "kind": "data", "source_pin": "image", "target_pin": "nope"},
            {"source": "n", "target": "p", "kind": "data", "source_pin": "number", "target_pin": "value"},
        ],
    }
    out = json.loads(save_workflow(name="Wires", graph=graph))
    assert out["ok"] is False and out["wires"] == ["Compare has no input 'nope'"]
    graph["edges"][0]["target_pin"] = "a"
    out = json.loads(save_workflow(name="Wires", graph=graph))
    try:
        assert out["ok"] is True
    finally:
        delete_workflow(out["workflow"]["id"])
