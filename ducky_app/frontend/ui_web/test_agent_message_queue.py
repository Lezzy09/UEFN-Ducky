"""Agent-to-agent messages never cancel the chat they reach: a busy chat holds them."""

from __future__ import annotations

import time
from types import SimpleNamespace

from frontend.ui_web import agent_modes as am


def test_a_busy_chat_holds_agent_messages_and_runs_them_after_its_turn(monkeypatch) -> None:
    cancels: list[object] = []
    monkeypatch.setattr(am, "load_conversation", lambda cid, **kw: SimpleNamespace(id=cid))
    monkeypatch.setattr(am, "is_agent_running", lambda cid: True)
    monkeypatch.setattr(am, "cancel_agent", lambda cid=None, **kw: cancels.append(cid))
    monkeypatch.setattr(am, "_pending_agent_messages", {})

    assert am.run_message("c1", "report 1", "agent", "", queue_if_busy=True, _local=True) == "queued"
    assert am.run_message("c1", "report 2", "agent", "", queue_if_busy=True, _local=True) == "queued"
    assert cancels == []  # the coordinator's turn keeps running
    assert am._pending_agent_messages["c1"] == ["report 1", "report 2"]

    started: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(am, "wait_for_idle", lambda cid, timeout=None: True)
    monkeypatch.setattr(am, "run_message", lambda cid, text, mode, model, **kw: started.append((cid, text, kw)) or "run")
    am._deliver_pending_agent_messages("c1")
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.02)
    assert started and started[0][:2] == ("c1", "report 1\n\nreport 2")
    assert started[0][2].get("queue_if_busy") is True
    assert "c1" not in am._pending_agent_messages


def test_a_person_pressing_stop_drops_held_agent_messages(monkeypatch) -> None:
    monkeypatch.setattr(am, "_pending_agent_messages", {"c2": ["held"]})
    am.cancel_agent("c2")
    assert "c2" not in am._pending_agent_messages


def test_a_turn_that_replaces_a_running_one_is_not_a_stop(monkeypatch) -> None:
    # Oct 12 2026: a recycle's fresh-session message replaced the member's running turn; the
    # lead was told "stopped by the user" and stood its team down.
    from backend.agent import a2a_broker as broker
    stops: list[str] = []
    monkeypatch.setattr(broker, "on_agent_cancelled_by_user", stops.append)
    monkeypatch.setattr(am, "_pending_agent_messages", {})
    am.cancel_agent("c3", by_user=False)
    assert stops == []
    am.cancel_agent("c3")  # the person's Stop
    assert stops == ["c3"]


def test_terminal_quota_tap_retains_pending_until_cooldown(monkeypatch):
    from backend.agent import a2a_broker as broker
    monkeypatch.setattr(broker, "_cooldowns", {}, raising=False)
    monkeypatch.setattr(broker, "_stopped", set(), raising=False)
    monkeypatch.setattr(broker, "_uncertain_chats", set(), raising=False)
    monkeypatch.setattr(broker, "_retry_queue_later", lambda cid: None)
    monkeypatch.setattr(am, "_pending_agent_messages", {"limited": ["queued work"]})
    calls = []
    monkeypatch.setattr(am, "_deliver_pending_agent_messages", lambda cid: calls.append(cid))
    tap = am._make_broker_tap(lambda event: None, "limited")
    event = {"type": "agent_stopped", "conv_id": "limited", "reason": "error",
             "detail": '{"error":{"code":"insufficient_quota"}}'}
    tap(event)
    tap(event)
    assert calls == []
    assert am._pending_agent_messages == {"limited": ["queued work"]}


def test_held_messages_are_handed_over_once(monkeypatch) -> None:
    monkeypatch.setattr(am, "_pending_agent_messages", {"c3": ["one", "two"]})
    assert am.take_pending_agent_messages("c3") == ["one", "two"]
    assert am.take_pending_agent_messages("c3") == []


def test_an_agent_waiting_on_a_busy_chat_queues_instead_of_replacing_its_turn(monkeypatch) -> None:
    # Oct 21 2026: a lead's sends cancelled its busy member's turn four times in a row.
    monkeypatch.setattr(am, "is_agent_running", lambda cid: True)
    sent: list[dict] = []
    monkeypatch.setattr(am, "run_message", lambda cid, text, mode, model, **kw: sent.append(kw) or "queued")
    out = am.run_message_and_wait("member", "next task", queue_if_busy=True, _local=True)
    assert out["status"] == "queued" and out["error"] == am.BUSY_QUEUED
    assert sent[0]["queue_if_busy"] is True and not sent[0].get("force")


def test_the_bridge_asks_the_panel_which_chats_run_and_stops_them_there(monkeypatch, tmp_path) -> None:
    # Oct 21 2026: from the MCP bridge a Codex lead saw its busy member as idle and sent all its
    # parallel work into it, and ducky_agent_stop stopped nothing: the agents run in the panel.
    from backend.panel import rpc
    from frontend.ui_web import panel_httpd

    monkeypatch.setattr(panel_httpd, "_server", None)
    monkeypatch.setattr(panel_httpd, "_root", None)
    monkeypatch.setattr(panel_httpd, "PANEL_UI_HTTP_PORT", 0)
    monkeypatch.setattr(panel_httpd, "verify_panel_dist", lambda _root: None)
    panel_httpd.start_panel_ui_server(tmp_path)
    server = panel_httpd._server
    monkeypatch.setattr(rpc, "_RPC_URL", f"http://127.0.0.1:{server.server_address[1]}/__panel_rpc")
    asked: list[str] = []

    def panel_state(cancel="", by_user=True):
        asked.append(cancel)
        return {"running": [] if cancel else ["member"], "parents": {"member": "lead"}}

    monkeypatch.setattr(am, "run_state", panel_state)
    monkeypatch.setattr(am, "_panel_runs_cache", (float("-inf"), None))
    try:
        assert not am.is_agent_running("member")  # not the bridge: this process's own runs
        assert asked == []
        monkeypatch.setenv("UEFN_DUCKY_MCP_BRIDGE", "1")
        assert am.is_agent_running("member") and am.list_running_agents() == ["member"]
        assert am.linked_children_of("lead") == ["member"] and am.linked_parent_of("member") == "lead"
        assert asked == [""]  # one question, kept for a second
        am.cancel_agent("member")
        assert asked == ["", "member"] and not am.is_agent_running("member")
    finally:
        server.shutdown()
        server.server_close()
