"""Send now into a running turn: held until a tool call takes it, never a Stop."""

from __future__ import annotations

from backend.agent.coding_agents.runner import merge_steered_blocks
from backend.server import _with_steer
from frontend.ui_web import steer


def test_post_take_and_end(monkeypatch):
    monkeypatch.setattr("frontend.ui_web.agent_modes.is_agent_running", lambda cid: cid == "busy")
    events = []
    steer.bind_run("busy", events.append)
    try:
        assert steer.post("idle", "q0", "hi") is False  # no turn: the composer sends it normally
        assert steer.post("busy", "q1", "use blue") is True
        assert steer.post("busy", "q1", "use blue") is True  # Send now twice: held once
        assert steer.post("busy", "q2", "and red") is True
        steer.post("busy", "q2", "")  # deleted from the queue before a tool call took it
        assert steer.take("busy") == ["use blue"]
        assert events == [{"type": "user_steered", "conv_id": "busy", "steer_id": "q1", "text": "use blue"}]
        assert steer.take("busy") == []
        steer.post("busy", "q3", "late")
    finally:
        steer.end_run("busy")
    assert steer.take("busy") == []  # the turn ended: its queue runs it next instead


def test_steer_note_rides_on_every_result_shape():
    from mcp.types import CallToolResult, TextContent

    text = TextContent(type="text", text="ok")
    content, structured = _with_steer(([text], {"a": 1}), ["stop using red"])
    assert structured == {"a": 1} and "stop using red" in content[-1].text
    assert "stop using red" in _with_steer([text], ["stop using red"])[-1].text
    both, kept = _with_steer({"a": 1}, ["x"])
    assert kept == {"a": 1} and len(both) == 2
    protocol = _with_steer(CallToolResult(content=[text]), ["x"])
    assert protocol.content[-1].text.endswith("x")


def test_merge_puts_message_after_its_tool():
    final = [
        {"type": "text", "text": "a"},
        {"type": "tool_call", "id": "t1"},
        {"type": "tool_call", "id": "t2"},
    ]
    live = [
        {"type": "tool_call", "id": "t1"},
        {"type": "user", "text": "one", "after": "t1"},
        {"type": "user", "text": "two", "after": "t1"},
        {"type": "user", "text": "lost", "after": "gone"},
    ]
    merge_steered_blocks(final, live)
    assert [b.get("id") or b.get("text") for b in final] == ["a", "t1", "one", "two", "t2", "lost"]
