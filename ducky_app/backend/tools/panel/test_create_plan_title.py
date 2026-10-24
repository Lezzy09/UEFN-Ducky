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


class _FakeApi:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"ok": True, "member": {"member_conv_id": "m1"}}
        return call


def test_group_tools_pass_model_mute_and_stop_to_the_panel(monkeypatch):
    from backend.tools.panel import ducky_panel

    api = _FakeApi()
    monkeypatch.setattr(ducky_panel, "_panel_api", lambda: api)
    monkeypatch.setattr(ducky_panel, "_resolve_ducky_profile", lambda d: {"id": "tester"})
    ducky_panel.ducky_group_invite("g1", "tester", name="Tester", model="codex:gpt-5-mini")
    ducky_panel.ducky_group_add_member("g1", "c1", as_leader=True)
    ducky_panel.ducky_set_muted("g1", True)
    ducky_panel.ducky_group_stop("g1")
    name, args, kwargs = api.calls[0]
    assert name == "group_invite" and kwargs["model"] == "codex:gpt-5-mini" and kwargs["for_agent"] is True
    assert api.calls[1] == ("group_add_member", ("g1", "c1"), {"as_leader": True, "move_folder": True})
    assert api.calls[2] == ("set_muted", ("g1", True), {})
    assert api.calls[3] == ("group_stop", ("g1",), {})


def test_mute_and_group_stop_are_in_the_panel_toolset():
    from backend.agent.toolsets.categories import panel

    assert {"ducky_set_muted", "ducky_group_stop"} <= panel._DELEGATION_TOOLS
