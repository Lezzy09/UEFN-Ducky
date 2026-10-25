"""seat_queue — one cap on member turns at once; the rest wait in order."""

from __future__ import annotations

from collections import deque

import pytest

from frontend.ui_web import admission as adm
from frontend.ui_web import seat_queue as sq


@pytest.fixture
def q(monkeypatch):
    monkeypatch.setattr(adm, "_running", set())
    monkeypatch.setattr(adm, "_read_free", lambda: 64.0)
    monkeypatch.setattr(sq, "_line", deque())
    monkeypatch.setattr(sq, "_starting", set())
    monkeypatch.setattr(sq, "_user_cap", None)
    monkeypatch.setattr(sq, "pc_limit", lambda: 4)
    monkeypatch.setattr(sq, "_spawn", lambda fn, name: fn())  # start turns inline
    monkeypatch.setattr(sq, "_seen", set())
    monkeypatch.setattr(sq, "_first_starts", deque())
    monkeypatch.setattr(sq, "_wave_timer", False)
    monkeypatch.setattr(sq, "WAVE_SIZE", 100)  # the cap tests start no waves
    clock = {"t": 1000.0}
    monkeypatch.setattr(sq, "_now", lambda: clock["t"])
    timers: list[float] = []
    monkeypatch.setattr(sq, "_spawn_later", lambda delay, fn: timers.append(delay))
    started: list[str] = []

    def starter(cid):
        def go():
            started.append(cid)
            adm._running.add(cid)  # admission holds the slot until agent_stopped
        return go

    def end(cid, reason="done", detail=""):
        adm._running.discard(cid)  # agent_modes releases the memory slot
        sq.on_turn_end(cid, reason, detail)

    return {"started": started, "starter": starter, "end": end, "clock": clock, "timers": timers}


def test_cap_four_runs_four_and_the_fifth_starts_when_one_ends(q):
    results = [sq.request(f"s{i}", q["starter"](f"s{i}")) for i in range(10)]
    assert results == ["started"] * 4 + ["queued"] * 6
    assert q["started"] == ["s0", "s1", "s2", "s3"]
    assert sq.status()["text"] == "4 running · 6 waiting"
    q["end"]("s2")
    assert q["started"][4:] == ["s4"]  # oldest waiting seat, exactly one
    assert sq.status()["running"] == 4 and sq.status()["waiting"] == 5


def test_the_slider_lowers_the_cap_but_never_past_the_pc_limit(q):
    assert sq.set_run_at_once(2) == 2
    assert sq.set_run_at_once(99) == 4
    sq.set_run_at_once(2)
    for i in range(3):
        sq.request(f"s{i}", q["starter"](f"s{i}"))
    assert q["started"] == ["s0", "s1"]
    sq.set_run_at_once(0)  # back to the PC limit: the waiting seat starts
    assert q["started"] == ["s0", "s1", "s2"]


def test_memory_admission_is_part_of_the_same_gate(q, monkeypatch):
    monkeypatch.setattr(adm, "_read_free", lambda: 1.0)  # low memory: admission's floor of 2
    for i in range(4):
        sq.request(f"s{i}", q["starter"](f"s{i}"))
    assert q["started"] == ["s0", "s1"]


def test_a_running_or_waiting_seat_is_busy_and_stop_drops_it(q):
    sq.set_run_at_once(1)
    assert sq.request("a", q["starter"]("a")) == "started"
    assert sq.request("a", q["starter"]("a")) == "busy"
    assert sq.request("b", q["starter"]("b")) == "queued"
    assert sq.is_busy("b")
    sq.drop("b")
    assert not sq.is_busy("b")


def test_first_turns_start_three_at_a_time_five_seconds_apart(q, monkeypatch):
    monkeypatch.setattr(sq, "WAVE_SIZE", 3)
    monkeypatch.setattr(sq, "pc_limit", lambda: 16)
    for i in range(10):
        sq.request(f"s{i}", q["starter"](f"s{i}"))
    assert q["started"] == ["s0", "s1", "s2"]
    assert q["timers"] == [sq.WAVE_GAP_S]  # one timer for the next wave
    q["clock"]["t"] += 2
    sq.drain()
    assert len(q["started"]) == 3  # still inside the 5 s gap
    q["clock"]["t"] += 3
    sq._next_wave()
    assert q["started"][3:] == ["s3", "s4", "s5"]


def test_a_later_turn_of_a_started_seat_skips_the_wave(q, monkeypatch):
    monkeypatch.setattr(sq, "WAVE_SIZE", 1)
    sq.request("a", q["starter"]("a"))
    q["end"]("a")
    assert sq.request("b", q["starter"]("b")) == "queued"  # a first turn, the wave is full
    assert sq.request("a", q["starter"]("a")) == "started"  # not a first turn: no wave


def test_a_seat_whose_tools_did_not_connect_is_idle_and_can_restart(q):
    assert sq.request("a", q["starter"]("a")) == "started"
    assert sq.is_busy("a")
    # The turn ended without a real start; nothing else freed its slot yet.
    sq.on_turn_end("a", "error", "claude_code finished with no captured reply.\n\nDucky's tools didn't connect")
    assert not sq.is_busy("a") and not adm.holds("a")
    assert sq.request("a", q["starter"]("a")) == "started"
    assert q["started"] == ["a", "a"]


def test_pc_limit_reads_something():
    assert sq.pc_limit() >= 2 and sq.total_memory_gb() > 0
