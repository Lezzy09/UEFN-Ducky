"""swarm_build: seat pings go through K3's seat queue (the real one, capped)."""

from __future__ import annotations

import threading
import time

import pytest

from backend.tools.panel import swarm_build as sb
from backend.tools.panel.test_swarm_build import Api, _flat_plan
from frontend.ui_web import admission, seat_queue


@pytest.fixture
def queue(monkeypatch):
    """The real seat queue at a fixed cap, no memory gate, no first-turn waves, empty."""
    cap = {"n": 2}
    monkeypatch.setattr(seat_queue, "limit", lambda: cap["n"])
    monkeypatch.setattr(seat_queue, "WAVE_SIZE", 1000)
    monkeypatch.setattr(admission, "_read_free", lambda: 1e6)
    for name in ("_line", "_starting", "_seen", "_first_starts", "_starts", "_retried"):
        monkeypatch.setattr(seat_queue, name, type(getattr(seat_queue, name))())
    return cap


class QueuedApi(Api):
    """Pings through seat_queue.request; ``answer(conv_id)`` is the turn."""

    def __init__(self, root, answer):
        super().__init__(root)
        self.answer, self.now, self.most = answer, 0, 0
        self.count = threading.Lock()

    def ping(self, conv_id, text, timeout_s, later=None):
        def ask(cid, msg, secs):
            with self.count:
                self.now += 1
                self.most = max(self.most, self.now)
            try:
                return self.answer(cid, secs)
            finally:
                with self.count:
                    self.now -= 1

        return sb.queued_ping(seat_queue.request, ask, conv_id, text, timeout_s, later)


def _ok(cid, secs):
    time.sleep(0.2)
    return {"status": "done", "assistant_text": "ok"}


def test_pings_run_two_at_a_time_and_all_four_seat(tmp_path, queue):
    api = QueuedApi(tmp_path, _ok)
    out = sb.build_swarm(api=api, from_plan=_flat_plan(4))
    assert api.most == 2
    assert [s["status"] for s in out["tree"]] == ["assigned"] * 4 and len(api.names("assign")) == 4


def test_a_seat_that_starts_and_never_answers_fails(tmp_path, queue, monkeypatch):
    monkeypatch.setattr(sb, "PING_TIMEOUT_S", 0.3)

    def silent(cid, secs):
        time.sleep(secs)
        return {"status": "timeout", "error": f"No reply within {secs}s"}

    out = sb.build_swarm(api=QueuedApi(tmp_path, silent), from_plan=_flat_plan(1))
    assert out["tree"][0]["status"] == "seat_failed" and "No reply" in out["failed"][0]


def test_a_seat_still_queued_at_the_timeout_is_not_failed(tmp_path, queue, monkeypatch):
    monkeypatch.setattr(sb, "PING_TIMEOUT_S", 0.3)
    queue["n"] = 1
    hold = threading.Event()
    assert seat_queue.request("other", hold.wait) == "started"  # another seat holds the only slot
    api = QueuedApi(tmp_path, _ok)
    out = sb.build_swarm(api=api, from_plan=_flat_plan(1))
    seat = out["tree"][0]
    assert seat["status"] == "queued" and out["failed"] == [] and api.names("assign") == []
    hold.set()  # the slot frees: the ping runs, answers, and the seat is assigned
    for _ in range(50):
        if seat["status"] == "assigned":
            break
        time.sleep(0.05)
    assert seat["status"] == "assigned" and len(api.names("assign")) == 1
