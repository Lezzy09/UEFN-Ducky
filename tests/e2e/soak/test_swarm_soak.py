"""The swarm soak's numbers from canned samples (no running app needed)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("swarm_soak", Path(__file__).with_name("swarm_soak.py"))
soak = importlib.util.module_from_spec(_spec)
sys.modules["swarm_soak"] = soak  # dataclasses look their module up while the class is built
_spec.loader.exec_module(soak)


def _run(**kw):
    run = soak.Run(started=1000.0, ended=1000.0 + 600, agents=16)
    for i in range(10):
        run.samples.append(soak.Sample(t=1000.0 + i * 5, core_wait_p50=2.0 + i, core_wait_p95=10.0 * (i + 1),
                                       threads=500 + i * 10, agents_running=i + 6, app_cpu=float(i),
                                       webview_cpu=2.0, tool_cpu=1.0, free_gb=4.0 - i * 0.2))
    for i, seconds in enumerate([0.5, 1.0, 1.5, 2.0, 30.0]):
        run.opens.append(soak.ChatOpen(t=1000.0 + i, seconds=seconds))
    run.opens += [soak.ChatOpen(t=1100.0, seconds=60.0, timed_out=True)] * 2
    run.stub_events = ([{"kind": "turn_start", "session": f"s{i}"} for i in range(16)]
                       + [{"kind": "tool", "tool": "workspace_search"}] * 300
                       + [{"kind": "message", "text": "hi"}] * 3)
    run.messages_sent = 16
    for key, value in kw.items():
        setattr(run, key, value)
    return run


def test_percentile_interpolates_and_handles_empty():
    assert soak.percentile([], 95) is None
    assert soak.percentile([5.0], 95) == 5.0
    assert soak.percentile([1, 2, 3, 4], 50) == 2.5
    assert soak.percentile([10, 20, 30, 40, 50], 95) == 48.0
    assert soak.percentile([3, 1, 2], 100) == 3


def test_summary_numbers():
    s = soak.summarize(_run(conv_save_p95_ms=123.456))
    assert s["minutes"] == 10.0 and s["agents"] == 16 and s["samples"] == 10
    assert s["core_wait_ms"]["p95"] == 95.5  # p95 of the per-sample p95s 10..100
    assert s["threads_max"] == 590
    assert s["min_free_gb"] == 2.2
    assert s["agents_running_max"] == 15
    assert s["cpu_pct_of_pc"]["app"] == {"avg": 4.5, "max": 9.0}
    assert s["conv_save_p95_ms"] == 123.5
    assert s["turns_started"] == 16 and s["tool_calls"] == 300 and s["tool_calls_per_min"] == 30.0
    assert s["messages_delivered"] == 3 and s["messages_sent"] == 16


def test_chat_opens_count_timeouts_apart_from_times():
    o = soak.summarize(_run())["chat_open_s"]
    assert o["count"] == 7 and o["timeouts"] == 2
    assert o["max"] == 30.0  # timed-out presses don't count as a time
    assert o["p50"] == 1.5


def test_an_empty_run_reports_nones_not_crashes():
    run = soak.Run(started=0.0, ended=60.0, agents=2)
    s = soak.summarize(run)
    assert s["chat_open_s"] == {"count": 0, "p50": None, "p95": None, "max": None, "timeouts": 0}
    assert s["min_free_gb"] is None and s["threads_max"] is None
    assert "Chat open timeouts" in soak.render_md(s)


def test_conv_save_is_found_in_a_nested_perf_report():
    perf = {"processes": [{"pid": 1, "timings": {"conv_save_ms": {"p50": 4, "p95": 88, "n": 40}}}]}
    assert soak.find_metric(perf, "conv_save") == {"p50": 4, "p95": 88, "n": 40}
    assert soak.find_metric({"x": 1}, "conv_save") is None


def test_results_md_shows_every_measure():
    md = soak.render_md(soak.summarize(_run()), {"PC before": {"free_gb": 9.1}})
    for label in ("Core-wait p50 / p95", "Threads max", "Chat open p50 / p95 / max", "conv_save p95",
                  "WebView2 CPU", "Tool servers CPU", "Min free memory", "Agents running at once",
                  "Tool calls / min", "Messages delivered", "## PC before"):
        assert label in md


def test_refuses_installed_app_and_real_appdata(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    installed = local / "Programs" / "UEFN-Ducky" / "UEFN-Ducky.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    built = tmp_path / "dist" / "UEFN-Ducky.exe"
    built.parent.mkdir()
    built.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert "installed" in soak.refuse_reason(installed, tmp_path / "dsbx")
    assert "real AppData" in soak.refuse_reason(built, local / "UEFN-Ducky" / "box")
    assert "not found" in soak.refuse_reason(tmp_path / "nope.exe", tmp_path / "dsbx")
    assert soak.refuse_reason(built, tmp_path / "dsbx") == ""


def test_panel_client_refuses_the_live_ports():
    for port in (4199, 4200):
        try:
            soak.Panel(port)
        except ValueError:
            continue
        raise AssertionError(f"Panel({port}) must refuse")
    assert soak.Panel(4399).base == "http://127.0.0.1:4399/__panel_api/"
