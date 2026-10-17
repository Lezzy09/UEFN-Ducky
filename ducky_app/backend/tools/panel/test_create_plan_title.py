"""ducky_create_plan without a title still makes the plan."""

from __future__ import annotations

import json


def test_a_plan_without_a_title_is_named_from_its_overview(monkeypatch):
    # Oct 17 2026: a lead sent overview without title and got "title Field required" twice.
    from backend.agent.coding_agents import plans
    from backend.tools.panel import ducky_panel

    made = {}

    def create_plan(cid, *, title, **_kw):
        made["title"] = title
        return {"id": "p1", "title": title, "nodes": []}

    monkeypatch.setattr(ducky_panel, "_resolve_plan_chat_id", lambda _cid: "chat-1")
    monkeypatch.setattr(ducky_panel, "_project_root", lambda: "")
    monkeypatch.setattr(plans, "create_plan", create_plan)
    monkeypatch.setattr(plans, "push_plan_updated", lambda _p: None)
    monkeypatch.setattr(plans, "todo_progress", lambda _p: {})
    monkeypatch.setattr(plans, "outline_numbers", lambda *_a, **_k: {})
    out = json.loads(ducky_panel.ducky_create_plan(overview="Treasure Hunt team plan: Verse, pictures, Blender."))
    assert out["ok"] is True
    assert made["title"] == "Treasure Hunt team plan: Verse, pictures, Blender"
    ducky_panel.ducky_create_plan()
    assert made["title"] == "Plan"
