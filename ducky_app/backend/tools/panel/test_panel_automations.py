"""MCP graph tools open the editor and can delete graphs and templates."""

from __future__ import annotations

import json


def _events(monkeypatch) -> list[dict]:
    events: list[dict] = []
    monkeypatch.setattr("frontend.ui_web.agent_modes.push_ui_event", events.append)
    return events


def test_save_pipeline_opens_editor(monkeypatch):
    from backend.automations.store import delete_automation
    from backend.tools.panel.panel_automations import save_pipeline

    events = _events(monkeypatch)
    raw = save_pipeline(
        name="Live",
        graph={"nodes": [{"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}}], "edges": []},
    )
    doc = json.loads(raw)
    wid = doc["pipeline"]["id"]
    try:
        assert doc["ok"] is True
        assert {"type": "graph_focus", "kind": "pipeline", "id": wid, "action": "saved"} in events
    finally:
        delete_automation(wid)


def test_delete_pipeline_opens_editor(monkeypatch):
    from backend.tools.panel.panel_automations import delete_pipeline, save_pipeline

    events = _events(monkeypatch)
    wid = json.loads(save_pipeline(name="Gone", graph={"nodes": [], "edges": []}))["pipeline"]["id"]
    events.clear()
    out = json.loads(delete_pipeline(wid))
    assert out == {"ok": True, "id": wid}
    assert {"type": "graph_focus", "kind": "pipeline", "id": wid, "action": "deleted"} in events
    assert json.loads(delete_pipeline(wid))["ok"] is False


def test_delete_automation_refuses_pipeline(monkeypatch):
    from backend.automations.store import delete_automation as wipe
    from backend.tools.panel.panel_automations import delete_automation, save_pipeline

    _events(monkeypatch)
    wid = json.loads(save_pipeline(name="Pipe", graph={"nodes": [], "edges": []}))["pipeline"]["id"]
    try:
        assert json.loads(delete_automation(wid))["ok"] is False
    finally:
        wipe(wid)


def test_custom_template_roundtrip(monkeypatch):
    from backend.tools.panel.panel_automations import (
        delete_custom_automation_template,
        save_custom_automation_template,
    )

    events = _events(monkeypatch)
    raw = save_custom_automation_template(
        name="Starter",
        graph={"nodes": [{"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}}], "edges": []},
    )
    doc = json.loads(raw)
    tid = doc["template"]["id"]
    try:
        assert doc["ok"] is True
        assert any(e.get("type") == "templates_changed" for e in events)
        assert json.loads(delete_custom_automation_template(tid))["ok"] is True
    finally:
        delete_custom_automation_template(tid)
