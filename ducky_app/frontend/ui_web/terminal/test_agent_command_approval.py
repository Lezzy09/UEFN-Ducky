"""An agent's terminal command: the Allow/Deny pop-up, or none when its chat allows everything."""

from __future__ import annotations

from frontend.ui_web.terminal.manager import TerminalManager


class _Session:
    shell = "bash"
    cwd = "C:/repo"

    def __init__(self) -> None:
        self.ran: list[str] = []

    def is_busy(self) -> bool:
        return False

    def run_command(self, command: str, **_kw) -> dict:
        self.ran.append(command)
        return {"ok": True}

    def read_output_tail(self, **_kw) -> str:
        return "done"


def _manager(monkeypatch) -> tuple[TerminalManager, _Session, list[dict]]:
    mgr, session, events = TerminalManager(), _Session(), []
    monkeypatch.setattr(mgr, "get_session", lambda _sid: session)
    mgr.set_push(events.append)
    return mgr, session, events


def test_allow_everything_runs_without_the_popup(monkeypatch) -> None:
    mgr, session, events = _manager(monkeypatch)
    out = mgr.run_agent_command("s1", "npm test", conv_id="c1", auto_approve=True, command_timeout_s=5)
    assert out["ok"] is True and out["output_tail"] == "done"
    for _ in range(50):  # it runs on its own thread
        if session.ran:
            break
        __import__("time").sleep(0.02)
    assert session.ran == ["npm test"]
    assert not [e for e in events if e.get("type") == "terminal_command_pending"]


def test_without_it_the_popup_asks(monkeypatch) -> None:
    mgr, session, events = _manager(monkeypatch)
    out = mgr.run_agent_command("s1", "npm test", conv_id="c1", approval_timeout_s=1)
    assert out == {"ok": False, "error": "command not approved (timed out)"}
    assert [e["type"] for e in events] == ["terminal_command_pending"] and session.ran == []
