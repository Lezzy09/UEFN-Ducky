"""ducky_health / ducky_self_care: Ducky names why it (or the PC) is slow and fixes its own part."""

from __future__ import annotations

import json

from frontend import self_health


def test_snapshot_has_every_part_and_findings():
    snap = self_health.snapshot()
    assert snap["ok"] is True
    for key in ("app", "helpers", "other_ducky_processes", "uefn", "pc", "sandboxes", "terminals", "storage",
                "findings"):
        assert key in snap, key
    assert snap["app"]["memory_mb"] > 0 and snap["app"]["threads"] > 0
    assert snap["pc"]["memory_total_gb"] > 0 and snap["pc"]["top_apps"]
    assert snap["findings"] and all({"severity", "what", "why", "fix"} <= set(f) for f in snap["findings"])
    json.dumps(snap, default=str)


def _base() -> dict:
    return {"app": {"cpu_percent": 1, "memory_mb": 300, "private_mb": 280, "handles": 900},
            "pc": {"cpus": 8, "memory_used_percent": 40, "memory_total_gb": 64, "top_apps": []},
            "helpers": [], "other_ducky_processes": [], "uefn": [], "sandboxes": {}, "terminals": {}, "storage": {}}


def test_a_healthy_app_says_nothing_is_wrong():
    out = self_health.findings(_base())
    assert [f["severity"] for f in out] == ["ok"]


def test_findings_name_the_cause_and_its_fix():
    snap = _base()
    snap["app"].update(cpu_percent=240, private_mb=3500, handles=40000)
    snap["other_ducky_processes"] = [{"pid": 9, "memory_mb": 120, "orphan": True}]
    snap["sandboxes"] = {"programs": [{"name": "node.exe", "memory_mb": 2048, "cpu_percent": 10}]}
    snap["terminals"] = {"agent_owned": 9}
    snap["uefn"] = [{"name": "UnrealEditorFortnite.exe", "private_mb": 45 * 1024, "memory_mb": 23 * 1024}]
    text = json.dumps(self_health.findings(snap))
    assert "stop_orphan_bridges" in text and "stop_sandbox" in text and "close_idle_terminals" in text
    assert "ducky_perf_report" in text and "ducky_memory_report" in text
    assert "reopen UEFN" in text and "not Ducky" in text
    assert self_health.findings(snap)[0]["severity"] == "high"


def test_a_full_pc_that_is_not_ducky_says_so():
    snap = _base()
    snap["pc"].update(memory_used_percent=96, top_apps=[{"name": "UnrealEditorFortnite.exe", "memory_mb": 46000}])
    out = self_health.findings(snap)
    assert out[0]["severity"] == "high"
    assert "UnrealEditorFortnite.exe" in out[0]["why"] and "not Ducky" in out[0]["why"]


def test_self_care_actions():
    assert self_health.self_care("collect_garbage")["ok"] is True
    stopped = self_health.self_care("stop_sandbox", "all")
    assert stopped["ok"] is True and stopped["app_memory_mb"]["before"] > 0
    assert self_health.self_care("trim_caches")["ok"] is True
    assert self_health.self_care("prune_sandboxes")["ok"] is True
    assert self_health.self_care("format_disk")["ok"] is False


def test_orphan_bridges_only_stop_tool_servers_whose_parent_is_gone(monkeypatch):
    from backend.util import proc_table

    def proc(pid, name, ppid, started=100.0):
        return proc_table.Proc(pid, ppid, name, 1 << 20, 1 << 20, 1, 1, 0.0, started)

    procs = {p.pid: p for p in (
        proc(1, "System", 0, 1.0),
        proc(11, "UEFN-Ducky-Bridge.exe", 999999),  # orphan
        proc(12, "UEFN-Ducky-Bridge.exe", 999999),  # shared daemon: kept
        proc(13, "UEFN-Ducky.exe", 999999),  # an app: kept
        proc(14, "UEFN-Ducky-Bridge.exe", 1),  # parent alive: kept
        proc(15, "notepad.exe", 999999),  # not Ducky: never looked at
        proc(16, "UEFN-Ducky-Bridge.exe", 17, 50.0),  # its parent's pid now belongs to a newer process
        proc(17, "explorer.exe", 1, 90.0),
    )}
    cmds = {11: ["x", "bridge", "--port", "4200"], 12: ["x", "bridge", "--shared-daemon"], 13: ["x"],
            14: ["x", "bridge", "--adapter"], 16: ["x", "bridge", "--adapter"]}
    asked, stopped = [], []
    monkeypatch.setattr(proc_table, "table", lambda: procs)
    monkeypatch.setattr(self_health, "_cmdline", lambda pid: (asked.append(pid), (cmds[pid], ""))[1])
    monkeypatch.setattr(self_health, "_terminate", lambda pid, name: (stopped.append(pid), True)[1])
    out = self_health.self_care("stop_orphan_bridges")
    assert [s["pid"] for s in out["stopped"]] == [11, 16] == stopped
    assert 15 not in asked and 14 not in asked  # command lines only for Ducky's orphaned processes


def test_a_look_reads_the_process_table_not_each_process(monkeypatch):
    """A busy PC answered psutil's per-process questions in 50-120 ms each: one look at
    ~700 processes took minutes. The snapshot reads one table (twice, for CPU) and asks
    only Ducky's own processes for their command lines."""
    import psutil

    from backend.util import proc_table

    def refuse(*_a, **_k):
        raise AssertionError("per-process scan of the whole PC")

    monkeypatch.setattr(psutil, "process_iter", refuse)
    tables = []
    real = proc_table.table
    monkeypatch.setattr(proc_table, "table", lambda: (tables.append(1), real())[1])
    asked = []
    monkeypatch.setattr(self_health, "_cmdline", lambda pid: (asked.append(pid), ([], ""))[1])
    snap = self_health.snapshot()
    assert snap["ok"] and snap["app"]["threads"] > 0 and snap["pc"]["processes"] > 20
    assert len(tables) == 2
    ducky = [p for p in real().values() if p.name.lower().startswith("uefn-ducky")]
    assert len(asked) <= min(20, len(ducky))


def test_tools_ask_the_window_from_an_agents_tool_server(monkeypatch):
    from backend.tools.core import self_care_tools

    monkeypatch.setattr("frontend.ui_web.agent_modes._in_bridge_process", lambda: False)
    monkeypatch.setattr(self_health, "snapshot", lambda detail=False: {"ok": True, "detail": detail})
    assert json.loads(self_care_tools.ducky_health(detail=True)) == {"ok": True, "detail": True}
    monkeypatch.setattr(self_health, "self_care", lambda action, target="": {"ok": True, "action": action})
    assert json.loads(self_care_tools.ducky_self_care("collect_garbage"))["action"] == "collect_garbage"
