"""Batcher: token deltas join into at most 10 batches a second; hidden chats get a status a second."""

from __future__ import annotations

from frontend.agent_host.batching import Batcher


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _batcher():
    clock = _Clock()
    sent: list[tuple[float, str, list[dict]]] = []
    b = Batcher(lambda conv_id, events: sent.append((clock.t, conv_id, events)), clock=clock)
    return b, clock, sent


def _delta(i: int, conv: str = "c1") -> dict:
    return {"type": "text_delta", "text": f"t{i} ", "conv_id": conv, "run_id": "r1"}


def test_1000_deltas_in_1s_make_at_most_10_events_with_the_same_text():
    b, clock, sent = _batcher()
    for i in range(1000):
        clock.t = i / 1000
        b.feed(_delta(i))
        b.flush_due()
    clock.t = 1.2  # the last slot
    b.flush_due()
    assert 1 <= len(sent) <= 10
    events = [e for _, _, batch in sent for e in batch]
    assert all(e["type"] == "text_delta" for e in events)
    assert "".join(e["text"] for e in events) == "".join(f"t{i} " for i in range(1000))


def test_tool_event_between_deltas_keeps_its_order_and_goes_at_once():
    b, clock, sent = _batcher()
    b.feed(_delta(0))
    b.feed(_delta(1))
    b.feed({"type": "tool", "tool": {"name": "workspace_read_file"}, "conv_id": "c1", "run_id": "r1"})
    assert len(sent) == 1  # no waiting for the 100 ms slot
    b.feed(_delta(2))
    clock.t = 0.2
    b.flush_due()
    b.feed({"type": "agent_stopped", "reason": "done", "conv_id": "c1", "run_id": "r1"})
    kinds = [(e["type"], e.get("text")) for _, _, batch in sent for e in batch]
    assert kinds == [
        ("text_delta", "t0 t1 "),
        ("tool", None),
        ("text_delta", "t2 "),
        ("agent_stopped", None),
    ]


def test_hidden_chat_gets_at_most_one_status_a_second():
    b, clock, sent = _batcher()
    b.set_visible(["other"])
    b.feed({"type": "tool", "tool": {"name": "workspace_search"}, "conv_id": "c1", "run_id": "r1"})
    for i in range(3000):
        clock.t = i / 1000
        b.feed(_delta(i))
        b.flush_due()
    assert all(conv == "c1" for _, conv, _ in sent)
    events = [e for _, _, batch in sent for e in batch]
    assert all(e["type"] == "status" for e in events)
    assert 1 <= len(events) <= 3
    assert events[-1]["tool"] == "workspace_search"
    assert events[-1]["text"] == "workspace_search · 2s"
    times = [t for t, _, _ in sent]
    assert all(b2 - a >= 1.0 for a, b2 in zip(times, times[1:]))
    b.feed({"type": "agent_stopped", "reason": "done", "conv_id": "c1", "run_id": "r1"})
    assert sent[-1][2][0]["type"] == "agent_stopped"  # turn end still goes at once


def test_chat_going_off_screen_sends_its_waiting_text_first():
    b, clock, sent = _batcher()
    b.feed(_delta(0))
    assert sent == []
    b.set_visible([])
    assert [e["text"] for e in sent[0][2]] == ["t0 "]
