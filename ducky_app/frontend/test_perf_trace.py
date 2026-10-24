"""perf_trace.per_process_report: chat load / save times per Ducky process, not just the caller's."""

from __future__ import annotations

import time

from frontend import perf_trace


def _row(pid: int, **entry) -> dict:
    return {"ts": time.time(), "source": f"session-20261024-101500-{pid}", "message": entry.get("name", ""),
            "payload": entry}


def test_two_processes_get_their_own_blocks(monkeypatch):
    app, tools = 111, 222
    perf = [_row(app, kind="ui_lane_wait", name="ui_lane_wait", method="load_messages", duration_ms=ms)
            for ms in (1000, 2000, 30000)]
    perf += [_row(app, kind="conv_save", name="c1", duration_ms=ms) for ms in (100, 300, 1800)]
    perf += [_row(app, kind="ui_js", name="evaluate_js", duration_ms=20, js_bytes=60 * 1024 * 1024,
                  source="list_project_file_paths")]
    perf += [_row(app, kind="ui_js", name="evaluate_js", duration_ms=20, js_bytes=12 * 1024 * 1024, source="push")]
    perf += [_row(app, kind="ui_stall", name="longtask", duration_ms=ms) for ms in (200, 900)]
    perf += [_row(tools, kind="conv_save", name="c2", duration_ms=ms) for ms in (3, 3, 5)]
    errors = [{"ts": time.time(), "source": "chat_timeout", "message": "x"}] * 2 + [
        {"ts": time.time(), "source": "chat_slow", "message": "y"}]

    class _Events:
        @staticmethod
        def newest(kind, *, limit, since=None):
            assert limit == perf_trace.PER_PROCESS_ROW_CAP and since is not None
            return perf if kind == "perf" else errors

    monkeypatch.setattr(perf_trace, "_events", lambda: _Events)
    monkeypatch.setattr(perf_trace, "_process_role", lambda pid: {app: "app window", tools: "tool server"}[pid])
    out = perf_trace.per_process_report(hours=2)
    blocks = {b["role"]: b for b in out["processes"]}
    assert set(blocks) == {"app window", "tool server"}
    a, t = blocks["app window"], blocks["tool server"]
    assert a["pid"] == app and a["chat_loads"] == 3 and a["chat_load_p50_s"] == 2.0 and a["chat_load_p95_s"] > 25
    assert a["conv_saves"] == 3 and a["conv_save_p50_ms"] == 300 and a["conv_save_max_ms"] == 1800
    assert a["ui_js_mb_per_min"] == round(72 / 120, 2)
    assert a["top_ui_js"] == [["list_project_file_paths", 60.0], ["push", 12.0]]
    assert a["ui_stalls"] == 2 and a["chat_timeouts_2h"] == 2 and a["chat_slow_2h"] == 1
    assert t["pid"] == tools and t["conv_save_p50_ms"] == 3 and t["chat_loads"] == 0 and "chat_timeouts_2h" not in t
    assert out["chat_errors"] == {"chat_slow": 1, "chat_timeout": 2}


def test_biggest_bridge_replies_sorted_by_bytes_with_counts():
    rows = [_row(1, kind="ui_js_big", name=m, source=m, js_bytes=b) for m, b in (
        ("get_skill_info", 706_000), ("get_skill_info", 500_000), ("list_project_file_paths", 900_000),
        ("group_members", 70_000), ("group_members", 80_000), ("group_members", 90_000))]
    rows.append(_row(1, kind="ui_js", name="evaluate_js", source="push", js_bytes=5_000_000))  # not a big reply
    assert perf_trace.ui_js_big_top(rows) == [["get_skill_info", 2, 706_000], ["list_project_file_paths", 1, 900_000],
                                              ["group_members", 3, 90_000]]


def test_pid_comes_from_the_session_id():
    assert perf_trace._pid_of("session-20261024-101500-4321") == 4321
    assert perf_trace._pid_of("weird") == 0
