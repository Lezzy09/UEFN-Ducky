"""Workflow MCP tools open the editor, refuse unknown owners, and manage templates."""

from __future__ import annotations

import json


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
        assert {"type": "graph_focus", "id": wid, "action": "saved"} in events
    finally:
        delete_workflow(wid)


def test_delete_workflow_opens_editor(monkeypatch):
    from backend.tools.panel.panel_automations import delete_workflow, save_workflow

    events = _events(monkeypatch)
    wid = json.loads(save_workflow(name="Gone", graph={"nodes": [], "edges": []}))["workflow"]["id"]
    events.clear()
    out = json.loads(delete_workflow(wid))
    assert out == {"ok": True, "id": wid}
    assert {"type": "graph_focus", "id": wid, "action": "deleted"} in events
    assert json.loads(delete_workflow(wid))["ok"] is False


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
