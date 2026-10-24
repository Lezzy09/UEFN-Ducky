"""A waited command comes back early when the person writes, and keeps running."""

from __future__ import annotations

import threading
import time

from frontend.ui_web.terminal import manager as manager_mod
from frontend.ui_web.terminal.manager import TerminalManager


class _Long:
    """A long command (a test suite): ends when told to, prints as it goes."""

    shell = "bash"
    cwd = "C:/repo"

    def __init__(self) -> None:
        self.finish = threading.Event()
        self.output = "collected 900 items\n"
        self.runs = 0

    def is_busy(self) -> bool:
        return False

    def run_command(self, command: str, **_kw) -> dict:
        self.runs += 1
        self.finish.wait(10)
        self.output += "900 passed\n"
        return {"ok": True, "exit_code": 0, "output_tail": self.output}

    def read_output_tail(self, **_kw) -> str:
        return self.output


def _fast(monkeypatch) -> None:
    # Scaled down: 10 s first check, 2 s after -> 0.2 s and 0.05 s.
    monkeypatch.setattr(manager_mod, "_STEER_FIRST_S", 0.2)
    monkeypatch.setattr(manager_mod, "_STEER_EVERY_S", 0.05)


def _mgr(monkeypatch, session) -> tuple[TerminalManager, list[dict]]:
    mgr, events = TerminalManager(), []
    monkeypatch.setattr(mgr, "get_session", lambda _sid: session)
    mgr.set_push(events.append)
    return mgr, events


def test_a_queued_message_returns_early_and_the_command_goes_on(monkeypatch) -> None:
    _fast(monkeypatch)
    session = _Long()
    mgr, _ = _mgr(monkeypatch, session)
    started = time.monotonic()
    queued_at = started + 0.4  # "a message at 20 s"
    out = mgr.run_agent_command("s1", "pytest", auto_approve=True, command_timeout_s=180,
                                steer_pending=lambda: time.monotonic() >= queued_at)
    took = time.monotonic() - started
    assert out["ok"] is True and out["still_running"] is True
    assert out["session_id"] == "s1" and out["command_id"] == out["request_id"]
    assert "collected 900 items" in out["output_so_far"] and "ducky_terminal_read_output" in out["note"]
    assert 0.4 <= took < 0.6  # "returns by 22 s"
    assert session.runs == 1 and not session.finish.is_set()  # never killed or restarted
    session.finish.set()
    for _ in range(100):
        if "900 passed" in session.output:
            break
        time.sleep(0.02)
    assert "900 passed" in session.read_output_tail()  # the final output is readable later


def test_no_message_waits_for_the_end(monkeypatch) -> None:
    _fast(monkeypatch)
    session = _Long()
    mgr, _ = _mgr(monkeypatch, session)
    threading.Timer(0.5, session.finish.set).start()
    out = mgr.run_agent_command("s1", "pytest", auto_approve=True, command_timeout_s=180,
                                steer_pending=lambda: False)
    assert out["ok"] is True and "still_running" not in out and out["exit_code"] == 0
    assert "900 passed" in out["output_tail"]


def test_nothing_is_asked_before_the_first_ten_seconds(monkeypatch) -> None:
    _fast(monkeypatch)
    monkeypatch.setattr(manager_mod, "_STEER_FIRST_S", 5.0)
    session = _Long()
    mgr, _ = _mgr(monkeypatch, session)
    asked: list[float] = []
    threading.Timer(0.3, session.finish.set).start()
    out = mgr.run_agent_command("s1", "pytest", auto_approve=True,
                                steer_pending=lambda: asked.append(1) or True)
    assert out["ok"] is True and "still_running" not in out and asked == []


def test_a_message_while_the_card_waits_returns_and_allow_still_runs_it(monkeypatch) -> None:
    _fast(monkeypatch)
    session = _Long()
    session.finish.set()
    mgr, events = _mgr(monkeypatch, session)
    out = mgr.run_agent_command("s1", "pytest", conv_id="c1", approval_timeout_s=60,
                                steer_pending=lambda: True)
    assert out["ok"] is True and out["waiting_for_approval"] is True and "Allow/Deny" in out["note"]
    pending = [e for e in events if e["type"] == "terminal_command_pending"]
    assert [p["request_id"] for p in pending] == [out["request_id"]]
    assert mgr.list_pending()  # the card stays up
    assert mgr.approve_command(out["request_id"])["ok"]
    for _ in range(100):
        if session.runs:
            break
        time.sleep(0.02)
    assert session.runs == 1  # Allow ran it with nobody waiting
