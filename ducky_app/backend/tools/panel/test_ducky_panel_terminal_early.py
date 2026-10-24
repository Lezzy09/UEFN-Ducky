"""ducky_terminal_run and sandbox_run hand back the manager's early return with a read hint."""

from __future__ import annotations

import json

from backend.tools.panel import ducky_panel_terminal as term

EARLY = {"ok": True, "still_running": True, "session_id": "t3", "request_id": "r1", "command_id": "r1",
         "output_so_far": "collected 900 items", "note": "The person sent a message. Read it in this result."}


class _Mgr:
    def __init__(self, answer: dict) -> None:
        self.answer, self.calls = answer, []

    def run_agent_command(self, session_id: str, command: str, **kw) -> dict:
        self.calls.append((session_id, command, kw))
        return dict(self.answer)


def _run(monkeypatch, answer: dict) -> tuple[dict, _Mgr]:
    mgr = _Mgr(answer)
    monkeypatch.setattr(term, "_terminal_manager", lambda: mgr)
    monkeypatch.setattr(term, "_terminal_chat", lambda _c: "chat-1")
    monkeypatch.setattr("backend.tools.panel.permission_prompt.allows_everything", lambda _c: True)
    return json.loads(term.ducky_terminal_run("t3", "pytest")), mgr


def test_still_running_passes_through_with_the_read_call(monkeypatch) -> None:
    out, mgr = _run(monkeypatch, EARLY)
    assert {k: out[k] for k in EARLY} == EARLY  # unchanged
    assert out["read_with"] == 'ducky_terminal_read_output(session_id="t3")'
    assert mgr.calls[0][2]["conv_id"] == "chat-1"  # the manager's steer check needs the chat


def test_waiting_for_approval_gets_the_hint_too(monkeypatch) -> None:
    out, _ = _run(monkeypatch, {"ok": True, "waiting_for_approval": True, "session_id": "t3", "note": "card"})
    assert out["waiting_for_approval"] is True and "t3" in out["read_with"]


def test_a_finished_run_is_unchanged(monkeypatch) -> None:
    done = {"ok": True, "session_id": "t3", "request_id": "r1", "output_tail": "900 passed", "exit_code": 0}
    out, _ = _run(monkeypatch, done)
    assert out == done


def test_sandbox_run_carries_the_early_return(monkeypatch) -> None:
    from backend.tools.core import sandbox_tools

    monkeypatch.setattr(sandbox_tools, "_refused", lambda _c: "")
    monkeypatch.setattr(sandbox_tools, "_approved", lambda *_a: "")
    monkeypatch.setattr(sandbox_tools, "_forward", lambda call, **_a: dict(EARLY))
    out = json.loads(sandbox_tools.sandbox_run("pytest"))
    assert out["still_running"] is True and out["note"] == EARLY["note"]
    assert out["read_with"] == 'ducky_terminal_read_output(session_id="t3")'
    monkeypatch.setattr(sandbox_tools, "_forward", lambda call, **_a: {"ok": True, "exit_code": 0, "session_id": "t3"})
    assert "read_with" not in json.loads(sandbox_tools.sandbox_run("pytest"))
