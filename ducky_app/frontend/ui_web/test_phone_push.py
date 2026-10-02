"""Agent and workflow finishes push the phone: which chat, never the reply, never sub-agents."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from backend.automations import runner
from frontend import duckyos_account
from frontend.ui_web import agent_modes


def _capture_collect(monkeypatch) -> tuple[list[tuple[str, dict]], threading.Event]:
    sent: list[tuple[str, dict]] = []
    done = threading.Event()

    def fake_collect(plugin_id, event, body=None, **_kw):
        sent.append((event, dict(body or {})))
        done.set()
        return {}

    monkeypatch.setattr(duckyos_account, "_plugin_collect", fake_collect)
    return sent, done


def test_push_names_the_target_and_runs_off_thread(monkeypatch) -> None:
    sent, done = _capture_collect(monkeypatch)
    duckyos_account.notify_desktop_agent_done(
        title="Build island " * 20, body="Finished.", kind="chat", target_id="c_1"
    )
    assert done.wait(5)
    event, body = sent[0]
    assert event == "desktop-agent-done"
    assert body["kind"] == "chat" and body["id"] == "c_1"
    assert len(body["title"]) <= 80
    # Unknown kinds don't send a target.
    sent.clear()
    done.clear()
    duckyos_account.notify_desktop_agent_done(kind="settings", target_id="x")
    assert done.wait(5)
    assert "kind" not in sent[0][1] and "id" not in sent[0][1]


def test_only_top_level_finishes_push(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_modes, "_notify_phone", lambda conv_id, reason: calls.append((conv_id, reason)))
    monkeypatch.setattr(agent_modes, "close_changeset_run", lambda *_a: None)
    events: list[dict] = []

    agent_modes._push_agent_stopped(events.append, "c1", "run-1", "done")
    assert calls == [("c1", "done")]

    agent_modes._quiet_runs.add("run-2")  # started by another chat
    agent_modes._push_agent_stopped(events.append, "c2", "run-2", "done")
    assert calls == [("c1", "done")]
    assert "run-2" not in agent_modes._quiet_runs

    agent_modes._push_agent_stopped(events.append, "c3", "run-3", "cancelled")
    assert calls == [("c1", "done")]
    agent_modes._push_agent_stopped(events.append, "c4", "run-4", "error")
    assert calls == [("c1", "done"), ("c4", "error")]


def test_group_members_stay_quiet_and_reply_text_never_leaves(monkeypatch) -> None:
    sent: list[dict] = []
    done = threading.Event()

    def fake_notify(**kw):
        sent.append(kw)
        done.set()

    monkeypatch.setattr(duckyos_account, "notify_desktop_agent_done", fake_notify)
    convs = {
        "member": SimpleNamespace(title="Artist", parent_conv_id="hub"),
        "solo": SimpleNamespace(
            title="Build island",
            parent_conv_id="",
            messages=[{"role": "assistant", "content": "secret plan"}],
        ),
    }
    monkeypatch.setattr(agent_modes, "load_conversation", lambda cid: convs.get(cid))

    agent_modes._notify_phone("member", "done")
    agent_modes._notify_phone("solo", "done")
    assert done.wait(5)
    for t in threading.enumerate():
        if t.name == "phone-push":
            t.join(5)
    assert len(sent) == 1
    assert sent[0]["kind"] == "chat" and sent[0]["target_id"] == "solo"
    assert sent[0]["title"] == "Build island"
    assert "secret" not in sent[0]["body"]


def test_workflow_push(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(duckyos_account, "notify_desktop_agent_done", lambda **kw: sent.append(kw))
    runner._notify_phone({"id": "wf1", "name": "Daily check"}, False)
    assert sent == [
        {
            "title": "Daily check",
            "body": "Workflow failed. Tap to see why.",
            "kind": "workflow",
            "target_id": "wf1",
        }
    ]
