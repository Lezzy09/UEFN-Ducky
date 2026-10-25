"""A send while a turn runs never stops it: the text is queued and offered as a steer.

Only the Stop button (cancel_agent, by_user=True) ends a turn; the follow-up typed after
it runs once that turn is idle.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.agent import a2a_broker
from frontend.ui_web import agent_modes, steer


def test_run_message_queues_follow_up_instead_of_cancelling_live_run():
    pushes: list[dict] = []
    conv = SimpleNamespace(id="chat-1", title="t", messages=[], model="gpt-test", provider="openai",
                           coding_agent="ducky", folder_id=None, file_path="")

    with (
        patch.object(agent_modes, "_in_bridge_process", return_value=False),
        patch.object(agent_modes, "is_agent_running", return_value=True),
        patch.object(agent_modes, "cancel_agent") as cancel,
        patch.object(agent_modes, "wait_for_idle") as wait,
        patch.object(agent_modes, "load_conversation", return_value=conv) as load,
        patch.object(agent_modes, "_pending_agent_messages", {}),
        patch.object(agent_modes, "_pending_steered", {}),
        patch.object(a2a_broker, "_retry_queue_later", lambda cid: None),
    ):
        try:
            out = agent_modes.run_message("chat-1", "fix spacing", "agent", "gpt-test", push=pushes.append)
            assert out == "queued"
            assert agent_modes._pending_agent_messages["chat-1"] == ["fix spacing"]
            assert [m["text"] for m in steer._inbox.get("chat-1", [])] == ["fix spacing"]
        finally:
            steer.end_run("chat-1")

    assert not cancel.called and not wait.called
    assert not load.called  # no second turn started over the live one
    assert not any("already running" in str(e.get("text")) for e in pushes)
