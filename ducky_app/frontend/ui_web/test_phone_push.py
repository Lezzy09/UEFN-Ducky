"""Agent and workflow ends alert: which chat, never the reply, never sub-agents, never a quick reply."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from backend.automations import runner
from frontend import notifications
from frontend.ui_web import agent_modes


def test_only_top_level_failures_and_long_finishes_alert(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_modes, "_alert_finished", lambda conv_id, reason: calls.append((conv_id, reason)))
    monkeypatch.setattr(agent_modes, "close_changeset_run", lambda *_a: None)
    events: list[dict] = []

    agent_modes._push_agent_stopped(events.append, "c1", "run-1", "done")
    assert calls == [("c1", "done")]

    agent_modes._quiet_runs.add("run-2")  # started by another chat or a workflow
    agent_modes._push_agent_stopped(events.append, "c2", "run-2", "error")
    assert calls == [("c1", "done")]
    assert "run-2" not in agent_modes._quiet_runs

    agent_modes._push_agent_stopped(events.append, "c3", "run-3", "cancelled")
    assert calls == [("c1", "done")]

    # A quick reply was watched as it happened; a quick failure still alerts.
    agent_modes._run_started["run-4"] = agent_modes.time.monotonic()
    agent_modes._push_agent_stopped(events.append, "c4", "run-4", "done")
    assert calls == [("c1", "done")]
    agent_modes._run_started["run-5"] = agent_modes.time.monotonic()
    agent_modes._push_agent_stopped(events.append, "c5", "run-5", "error")
    assert calls[-1] == ("c5", "error")
    agent_modes._run_started["run-6"] = agent_modes.time.monotonic() - agent_modes.PHONE_PUSH_MIN_SECONDS - 1
    agent_modes._push_agent_stopped(events.append, "c6", "run-6", "done")
    assert calls[-1] == ("c6", "done")
    assert not {"run-4", "run-5", "run-6"} & set(agent_modes._run_started)


def test_runs_a_workflow_starts_are_quiet(monkeypatch) -> None:
    assert agent_modes._started_by_workflow() is False
    token = runner._LIVE.set(("wf1", "r1"))
    try:
        assert agent_modes._started_by_workflow() is True
    finally:
        runner._LIVE.reset(token)


def test_group_members_stay_quiet_and_reply_text_never_leaves(monkeypatch) -> None:
    sent: list[tuple[tuple, dict]] = []
    done = threading.Event()

    def fake_alert(*args, **kw):
        sent.append((args, kw))
        done.set()
        return True

    monkeypatch.setattr(notifications, "alert", fake_alert)
    convs = {
        "member": SimpleNamespace(title="Artist", parent_conv_id="hub"),
        "solo": SimpleNamespace(
            title="Build island",
            parent_conv_id="",
            messages=[{"role": "assistant", "content": "secret plan"}],
        ),
    }
    monkeypatch.setattr(agent_modes, "load_conversation", lambda cid: convs.get(cid))

    agent_modes._alert_finished("member", "done")
    agent_modes._alert_finished("solo", "done")
    assert done.wait(5)
    for t in threading.enumerate():
        if t.name == "chat-alert":
            t.join(5)
    assert len(sent) == 1
    args, kw = sent[0]
    assert args == ("Build island", "Finished.")
    assert kw["kind"] == "chat" and kw["target_id"] == "solo" and kw["level"] == "ok"
    assert "secret" not in repr(sent)


def test_workflow_alerts(monkeypatch) -> None:
    sent: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(notifications, "alert", lambda *a, **kw: sent.append((a, kw)))
    wf = {"id": "wf1", "name": "Daily check"}

    runner._alert_run(wf, True, triggered=True, seconds=600)  # a trigger's success: its Message me talks
    runner._alert_run(wf, True, triggered=False, seconds=3)  # watched as it ran
    assert sent == []

    runner._alert_run(wf, False, triggered=True, seconds=1)
    runner._alert_run(wf, True, triggered=False, seconds=45)
    assert sent == [
        (("Daily check", "Workflow failed."), {"level": "error", "kind": "workflow", "target_id": "wf1"}),
        (("Daily check", "Workflow finished."), {"level": "ok", "kind": "workflow", "target_id": "wf1"}),
    ]
