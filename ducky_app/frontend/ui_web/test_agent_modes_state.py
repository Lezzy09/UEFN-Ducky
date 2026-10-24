"""agent_modes.running_tool / last_output_age_s: what a chat's live turn is doing, read without waiting."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from frontend.ui_web import agent_modes


@pytest.fixture
def live(monkeypatch):
    alive = {"yes": True}
    session = SimpleNamespace(run_id="run-1", _thread=SimpleNamespace(is_alive=lambda: alive["yes"]))
    monkeypatch.setitem(agent_modes._sessions, "c1", session)
    monkeypatch.setattr(agent_modes, "_turn_activity", {})
    return alive


def test_nothing_without_a_turn(monkeypatch):
    monkeypatch.setattr(agent_modes, "_turn_activity", {})
    assert agent_modes.running_tool("nope") is None and agent_modes.last_output_age_s("nope") is None


def test_the_open_tool_and_the_last_output(live):
    agent_modes._note_activity("c1", "run-1", {"type": "text", "text": "hi"})
    assert agent_modes.running_tool("c1") is None
    assert 0 <= agent_modes.last_output_age_s("c1") < 1
    t0 = time.time()
    agent_modes._note_activity("c1", "run-1", {"type": "tool", "tool": {"id": "t1", "name": "ducky_terminal_run",
                                                                         "status": "pending"}})
    got = agent_modes.running_tool("c1")
    assert got["name"] == "ducky_terminal_run" and got["started_at"] >= t0
    agent_modes._note_activity("c1", "run-1", {"type": "tool_done", "tool": {"id": "t1", "name": "ducky_terminal_run"}})
    assert agent_modes.running_tool("c1") is None


def test_a_finished_or_replaced_run_reads_as_none(live):
    agent_modes._note_activity("c1", "run-1", {"type": "tool", "tool": {"id": "t1", "name": "x", "status": "pending"}})
    live["yes"] = False
    assert agent_modes.running_tool("c1") is None and agent_modes.last_output_age_s("c1") is None
    live["yes"] = True
    agent_modes._sessions["c1"].run_id = "run-2"
    assert agent_modes.running_tool("c1") is None
