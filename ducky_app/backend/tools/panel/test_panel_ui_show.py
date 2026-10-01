"""Show me: ducky_ui_show, tours with actions and name targets, workflow Show me / tours,
which window answers, and the two Settings switches."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.tools.panel import panel_ui


@pytest.fixture()
def rpc(monkeypatch):
    calls: list[tuple[str, dict[str, Any], float]] = []
    reply: dict[str, Any] = {"ok": True, "shown": True, "missing": False, "target": "x"}

    def fake(method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
        calls.append((method, dict(params or {}), timeout))
        return dict(reply)

    monkeypatch.setattr(panel_ui, "panel_rpc", fake)
    monkeypatch.setattr("backend.panel.rpc.panel_rpc", fake)
    return calls


def test_show_me_sends_what_to_show_and_where(rpc):
    out = json.loads(panel_ui.ducky_ui_show(
        target="settings.tab.audio", title="Audio settings", body="Mic and speakers.", navigate="settings.audio",
    ))
    assert out == {"ok": True, "shown": True, "missing": False, "target": "x"}
    method, params, timeout = rpc[-1]
    assert method == "show" and timeout == panel_ui._SHOW_WAIT_S
    assert params == {"target": "settings.tab.audio", "title": "Audio settings", "body": "Mic and speakers.", "wait": False, "navigate": "settings.audio"}

    panel_ui.ducky_ui_show(
        target="workflows.node.a", also=["workflows.node.b", " "], title="", body="Both of these", workflow_id=" wf1 ",
        action=" workflows.add_menu ", action_args={"query": "if"}, wait=True,
    )
    method, params, timeout = rpc[-1]
    assert params["target"] == ["workflows.node.a", "workflows.node.b"]
    assert params["title"] == "Both of these" and params["workflow_id"] == "wf1"
    assert params["action"] == {"id": "workflows.add_menu", "args": {"query": "if"}}
    assert params["wait"] is True and timeout == panel_ui._SHOW_CLOSE_WAIT_S

    panel_ui.ducky_ui_show(target=" Save ", role="Button", within="workflows.details", title="Save")
    assert rpc[-1][1]["target"] == {"role": "button", "name": "Save", "within": "workflows.details"}
    panel_ui.ducky_ui_show(target="Run log", role="text", title="Log")
    assert rpc[-1][1]["target"] == {"text": "Run log"}

    panel_ui.ducky_ui_show(target="settings.store.detail", title="Meshy", navigate="settings.store", item_id="meshy")
    assert rpc[-1][1]["item_id"] == "meshy"


def test_show_me_refuses_what_it_cant_show(rpc):
    assert "error" in json.loads(panel_ui.ducky_ui_show(target="", title="x"))
    assert "error" in json.loads(panel_ui.ducky_ui_show(target=" ", role="button", title="x"))
    assert "say what it is" in json.loads(panel_ui.ducky_ui_show(target="a.b", title=" "))["error"]
    bad = json.loads(panel_ui.ducky_ui_show(target="a.b", title="x", navigate="settings.nowhere"))
    assert bad["error"].startswith("unknown route") and "settings.audio" in bad["routes"]
    assert rpc == []


def test_list_targets_searches(rpc):
    panel_ui.ducky_ui_list_targets(route="workflows", query=" test run ", visible_only=True)
    assert rpc[-1][:2] == ("list_targets", {"route": "workflows", "query": "test run", "visible_only": True})


def test_tour_steps_take_actions_and_name_targets():
    out = panel_ui._normalize_walkthrough_steps([
        {"target": {"role": "button", "name": "Save"}, "body": "Keeps it", "action": {"id": "workflows.open", "args": {"id": "w"}}},
        {"target": "settings.tab.store", "title": "Store", "navigate": "settings.store", "item_id": "meshy", "action": {"args": {}}},
    ])
    assert out[0]["target"] == {"role": "button", "name": "Save"} and out[0]["title"] == "Keeps it"
    assert out[0]["action"] == {"id": "workflows.open", "args": {"id": "w"}}
    assert out[1]["navigate"] == "settings.store" and out[1]["item_id"] == "meshy" and "action" not in out[1]
    assert "error" in panel_ui._normalize_walkthrough_steps([{"target": {"bogus": 1}}])


def _workflow() -> str:
    from backend.automations.store import save_workflow

    graph = {"nodes": [{"id": "s", "type": "start.manual", "x": 0, "y": 0, "config": {}},
                       {"id": "w", "type": "flow.wait", "x": 300, "y": 0, "config": {}}],
             "edges": [{"source": "s", "target": "w", "kind": "main"}],
             "groups": [{"id": "g1", "name": "Both", "node_ids": ["s", "w"]}]}
    return save_workflow({"name": "Show me demo", "graph": graph})["id"]


def test_show_workflow_with_a_title_is_a_show_me(rpc, monkeypatch):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import show_workflow

    monkeypatch.setattr("frontend.ui_web.agent_modes.push_ui_event", lambda _e: None)
    wid = _workflow()
    try:
        out = json.loads(show_workflow(wid, node_ids=["w", "nope"], title="The wait", body="Pauses."))
        assert out == {"ok": True, "shown": ["w"], "missing": ["nope"], "show_me": True}
        assert rpc[-1][:2] == ("show", {"target": "workflows.node.w", "workflow_id": wid, "title": "The wait", "body": "Pauses."})
        json.loads(show_workflow(wid, group_id="g1", title="Both"))
        assert rpc[-1][1]["target"] == "workflows.group.g1"
        rpc.clear()
        assert json.loads(show_workflow(wid, node_ids=["w"], note="old style"))["ok"] is True
        assert rpc == []  # no title: the old glide + caption
    finally:
        delete_workflow(wid)


def test_tour_workflow_checks_steps_then_asks_the_editor(rpc):
    from backend.automations.store import delete_workflow
    from backend.tools.panel.panel_automations import tour_workflow

    wid = _workflow()
    try:
        assert json.loads(tour_workflow("missing"))["error"] == "workflow not found"
        assert "auto=true" in json.loads(tour_workflow(wid))["error"]
        assert "step 1" in json.loads(tour_workflow(wid, steps=[{"node_ids": ["nope"], "title": "x"}]))["error"]
        tour_workflow(wid, auto=True)
        assert rpc[-1][:2] == ("tour_workflow", {"workflow_id": wid, "steps": [], "auto": True}) and rpc[-1][2] == 600.0
        tour_workflow(wid, steps=[{"node_ids": ["s", "zzz"], "title": "Start", "body": "Runs it"}, {"group_id": "g1", "body": "Both"}, {"target": "workflows.toolbar.run", "title": "Test"}])
        assert rpc[-1][1]["steps"] == [
            {"node_ids": ["s"], "title": "Start", "body": "Runs it"},
            {"group_id": "g1", "title": "Both", "body": "Both"},
            {"target": "workflows.toolbar.run", "title": "Test", "body": "Test"},
        ]
        assert rpc[-1][1]["auto"] is False
    finally:
        delete_workflow(wid)


def test_requests_go_to_the_window_in_use():
    from frontend.ui_web import ui_rpc

    ui_rpc.mark_active("desk-1")
    assert ui_rpc.window_for("show") == "desk-1"
    assert ui_rpc.window_for("ask_user") == ""  # questions stay on every window
    ui_rpc.mark_active("phone-2")
    assert ui_rpc.window_for("tour_workflow") == "phone-2"
    ui_rpc.mark_active("desk-1", False)  # not the active one: no change
    assert ui_rpc.window_for("navigate") == "phone-2"
    ui_rpc.mark_active("phone-2", False)
    assert ui_rpc.window_for("navigate") == ""

    request_id, event = ui_rpc.submit("show", {"target": "x", "_for_client": "desk-1"})
    assert event["params"]["_for_client"] == "desk-1"
    assert ui_rpc.wait_ack(request_id, 0.05) is False
    assert ui_rpc.ack(request_id) is True
    assert ui_rpc.wait_ack(request_id, 0.05) is True
    ui_rpc.respond(request_id, {"ok": True})
    assert ui_rpc.wait(request_id, 0.1) == {"ok": True}
    assert ui_rpc.wait_ack(request_id, 0.05) is True  # answered and collected
    assert ui_rpc.ack("unknown") is False

    # Sent to every window: the first to claim it runs it, the rest drop it.
    request_id, _event = ui_rpc.submit("tour_workflow", {"workflow_id": "w"})
    assert ui_rpc.claim(request_id) is True
    assert ui_rpc.claim(request_id) is False
    assert ui_rpc.wait_ack(request_id, 0.01) is True
    assert ui_rpc.claim("unknown") is False


def test_settings_switches_save_and_read_back():
    from frontend.ui_web.panel_api import PanelApi
    from frontend.settings import PanelSettings

    assert PanelSettings().first_open_tours is True and PanelSettings().show_me_autoplay is True
    api = PanelApi.__new__(PanelApi)
    api.save_agent_settings({"first_open_tours": False, "show_me_autoplay": False})
    got = api.get_settings()
    assert got["first_open_tours"] is False and got["show_me_autoplay"] is False
    api.save_agent_settings({"first_open_tours": True})
    assert api.get_settings()["first_open_tours"] is True
