"""In-flight call counter (frontend.ui_web.inflight)."""

from __future__ import annotations

import threading

import pytest

from frontend.ui_web import inflight


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(inflight, "_live", {})
    monkeypatch.setattr(inflight, "_lost", 0)
    yield


def test_concurrent_enter_leave_totals():
    start = threading.Barrier(50)
    held: list[int] = []
    lock = threading.Lock()

    def work(i: int) -> None:
        start.wait()
        tokens = [inflight.enter("bridge", f"m{i % 5}") for _ in range(20)]
        for t in tokens[:10]:
            inflight.leave(t)
        with lock:
            held.extend(tokens[10:])

    threads = [threading.Thread(target=work, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert inflight.total() == 500
    assert sum(r["count"] for r in inflight.top(10)) == 500
    for t in held:
        inflight.leave(t)
    assert inflight.total() == 0
    inflight.leave(held[0])  # twice is harmless
    inflight.leave(None)
    assert inflight.total() == 0


def test_top_orders_by_count_then_age(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(inflight, "_clock", lambda: now[0])
    inflight.enter("bridge", "old_one")
    now[0] = 103.9
    for _ in range(3):
        inflight.enter("bridge", "group_members")
    inflight.enter("http", "POST /__panel_rpc")
    rows = inflight.top()
    assert rows[0] == {"source": "bridge", "method": "group_members", "count": 3, "oldest_s": 0.0}
    assert rows[1]["method"] == "old_one" and rows[1]["oldest_s"] == 3.9
    assert rows[2]["source"] == "http"
    assert len(inflight.top(1)) == 1


def test_old_entries_move_to_lost(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(inflight, "_clock", lambda: now[0])
    inflight.enter("bridge", "never_answered")
    keep = inflight.enter("bridge", "answered")
    now[0] = 599.0
    assert inflight.total() == 2 and inflight.lost() == 0
    now[0] = 600.0
    assert inflight.total() == 0
    assert inflight.lost() == 2
    inflight.leave(keep)
    assert inflight.top() == []


def test_bridge_return_leaves_and_flags_big_replies(monkeypatch):
    from frontend import perf_trace
    from frontend.ui_web import ui_dispatch, win_frameless

    traced: list[tuple] = []
    sent: list[str] = []
    monkeypatch.setattr(perf_trace, "trace", lambda kind, name="", ms=0.0, **meta: traced.append((kind, meta)))
    monkeypatch.setattr(ui_dispatch, "schedule_evaluate_js", lambda w, js, source="": sent.append(source))

    token = inflight.enter("bridge", "get_skill_info")
    win_frameless._QueuedReturn(object(), "get_skill_info", token).evaluate_js("x" * 100_000)
    assert inflight.total() == 0
    assert traced == [("ui_js_big", {"source": "get_skill_info", "js_bytes": 100_000})]

    traced.clear()
    win_frameless._QueuedReturn(object(), "list_workflows").evaluate_js("x" * 10_000)
    assert traced == []
    assert sent == ["get_skill_info", "list_workflows"]


def test_js_api_func_skips_pywebview_internals():
    from frontend.ui_web import win_frameless

    class Api:
        def group_members(self):
            return []

        nested = None

    class Win:
        _functions: dict = {}
        _js_api = Api()

    assert win_frameless._js_api_func(Win(), "group_members") is not None
    assert win_frameless._js_api_func(Win(), "pywebviewEventHandler") is None
    assert win_frameless._js_api_func(Win(), "_private") is None
    assert win_frameless._js_api_func(Win(), "nested.x") is None
