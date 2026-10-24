"""Runs left ``running`` by an earlier start of the app are closed once, by the app process."""

import time

from backend.store import db
from backend.store.repos import ledger


def _run(run_id: str, started: float, status: str = "running") -> dict:
    return {"run_id": run_id, "conv_id": "c", "status": status, "started": started, "entries": [], "seen": {}}


def test_runs_older_than_this_start_are_interrupted_and_newer_ones_kept(monkeypatch):
    for run in (_run("old-1", 100.0), _run("old-2", 200.0), _run("old-done", 100.0, "done"),
                _run("new", ledger._PROCESS_START + 5)):
        ledger.run_put("p", run)
    assert ledger.close_stale_runs(now=1000.0) == 2
    assert ledger.run_get("p", "old-1")["status"] == "interrupted"
    assert ledger.run_get("p", "old-1")["ended"] == 1000.0
    assert ledger.run_get("p", "old-done")["status"] == "done"
    assert ledger.run_get("p", "new")["status"] == "running"
    assert {r["run_id"] for r in ledger.runs_with_status("p", ("running",))} == {"new"}


def test_a_dead_hosts_runs_close_by_id():
    ledger.run_put("p", _run("host-a", time.time() + 10))
    ledger.run_put("p", _run("host-b", time.time() + 10))
    assert ledger.close_stale_runs(run_ids=["host-a"]) == 1
    assert ledger.run_get("p", "host-a")["status"] == "interrupted"
    assert ledger.run_get("p", "host-b")["status"] == "running"
    assert ledger.close_stale_runs(run_ids=[]) == 0


def test_the_app_process_sweeps_once_and_a_bridge_never(monkeypatch):
    ledger.run_put("p", _run("left-open", 100.0))  # a bridge process: not swept
    assert ledger.run_get("p", "left-open")["status"] == "running"
    monkeypatch.setattr(db, "_rebuild_here", True)
    monkeypatch.setattr(ledger, "_stale_closed", set())
    calls = []
    real = ledger.close_stale_runs
    monkeypatch.setattr(ledger, "close_stale_runs", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert ledger.run_get("p", "left-open")["status"] == "interrupted"
    ledger.run_put("p", _run("left-open-2", 100.0))
    assert ledger.run_get("p", "left-open-2")["status"] == "running"  # once per process
    assert calls == [1]
