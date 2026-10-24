"""Live text only for chats a viewer shows; the rest get one status line per second."""

import threading

import pytest

from frontend.ui_web import panel_api


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(panel_api, "_visible_by_viewer", {})
    monkeypatch.setattr(panel_api, "_live_batcher", None)
    monkeypatch.setattr(panel_api, "_live_tick_loop", lambda batcher: None)  # the test ticks
    a = panel_api.PanelApi.__new__(panel_api.PanelApi)  # no __init__: no plugins or models
    a._all_windows = lambda: ["main"]
    a._agent_push_lock = threading.Lock()
    a.sent = []
    a._queue_agent_pushes = a.sent.extend
    return a


def _run_one_second(api, now, start):
    """16 chats each stream a token every 10 ms for one second."""
    api.sent.clear()
    for ms in range(start, start + 1000, 10):
        now[0] = ms / 1000.0
        for c in range(16):
            api._push({"type": "text_delta", "text": "t ", "conv_id": f"c{c}", "run_id": f"r{c}"})
        if ms % 50 == 0:
            panel_api._live_batcher.flush_due()
    return list(api.sent)


def test_one_visible_chat_of_sixteen(api) -> None:
    now = [0.0]
    api.set_visible_chats(["c0"], "main")
    panel_api._live_batcher._clock = lambda: now[0]

    sent = _run_one_second(api, now, 0)
    assert len(sent) <= 26
    texts = [e for e in sent if e["type"] == "text_delta"]
    assert texts and {e["conv_id"] for e in texts} == {"c0"}
    assert all(e["viewers"] == ["main"] for e in texts)
    assert {e["conv_id"] for e in sent if e["type"] == "status"} == {f"c{c}" for c in range(1, 16)}

    api.set_visible_chats(["c1"], "main")  # the person switched tabs
    sent = _run_one_second(api, now, 1000)
    assert {e["conv_id"] for e in sent if e["type"] == "text_delta"} == {"c1"}
    assert "c0" in {e["conv_id"] for e in sent if e["type"] == "status"}


def test_no_report_streams_everything(api) -> None:
    api._push({"type": "text_delta", "text": "hi", "conv_id": "c9", "run_id": "r"})
    assert [e["conv_id"] for e in api.sent] == ["c9"]
