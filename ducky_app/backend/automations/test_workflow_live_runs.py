"""A running workflow says which step it is on, and Stop ends it at once."""

import threading
import time

import pytest

from backend.automations import runner, store


@pytest.fixture()
def events(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "use_db", lambda *_: False)
    monkeypatch.setattr(store, "_files_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "_announce_graphs_changed", lambda: None)
    seen: list[dict] = []
    monkeypatch.setattr("frontend.ui_web.agent_modes.push_ui_event", seen.append)
    return seen


def _workflow(wait_s: float) -> str:
    graph = {
        "nodes": [
            {"id": "s", "type": "start.manual", "x": 0, "y": 0, "config": {}},
            {"id": "w", "type": "flow.wait", "x": 300, "y": 0, "config": {"seconds": wait_s}, "label": "Pause"},
            {"id": "e", "type": "flow.end", "x": 600, "y": 0, "config": {}},
        ],
        "edges": [{"source": "s", "target": "w", "kind": "main"}, {"source": "w", "target": "e", "kind": "main"}],
    }
    return str(store.save_workflow({"name": "Live", "graph": graph})["id"])


def test_steps_report_where_the_run_is(events):
    wid = _workflow(0)
    out = runner.run_workflow(wid)
    assert out["ok"] is True
    live = [(e["type"], e.get("node"), e["state"], e.get("from")) for e in events if e["type"] in ("workflow_step", "workflow_run")]
    assert live == [
        ("workflow_run", None, "started", None),
        ("workflow_step", "s", "running", None),
        ("workflow_step", "s", "ok", None),
        ("workflow_step", "w", "running", "s"),  # it came along the wire from s
        ("workflow_step", "w", "ok", None),
        ("workflow_step", "e", "running", "w"),
        ("workflow_step", "e", "ok", None),
        ("workflow_run", None, "done", None),
    ]
    assert len({e["run"] for e in events if "run" in e}) == 1
    assert runner.is_running(wid) is False


def test_stop_ends_a_run_right_away(events):
    wid = _workflow(60)
    result: dict = {}
    worker = threading.Thread(target=lambda: result.update(runner.run_workflow(wid)))
    started = time.time()
    worker.start()
    deadline = time.time() + 5
    while not runner.is_running(wid) or not any(e.get("node") == "w" for e in events):
        assert time.time() < deadline
        time.sleep(0.02)
    assert runner.stop_workflow(wid) is True
    worker.join(5)
    assert not worker.is_alive()
    assert time.time() - started < 5  # not the 60 second wait
    assert result["ok"] is False and result["error"] == runner.STOPPED
    assert [e["state"] for e in events if e["type"] == "workflow_run"] == ["started", "stopped"]
    assert ("w", "stopped") in [(e.get("node"), e["state"]) for e in events if e["type"] == "workflow_step"]
    assert runner.stop_workflow(wid) is False  # nothing left running


def test_the_start_tells_the_calling_chat_every_step(events):
    """The chat that ran it shows a live card: workflow name and the steps in order."""
    wid = _workflow(0)
    runner.run_workflow(wid, caller_conv_id="chat-1")
    started = next(e for e in events if e["type"] == "workflow_run" and e["state"] == "started")
    assert started["conv"] == "chat-1"
    assert started["name"] == "Live"
    assert [(p["node"], p["label"]) for p in started["plan"]] == [("s", "start.manual"), ("w", "Pause"), ("e", "flow.end")]


def test_stop_also_stops_the_ducky_an_agent_step_waits_for(monkeypatch):
    """A stopped workflow's launch ducky kept going and started a Fortnite session."""
    stopped: list[str] = []
    monkeypatch.setattr("frontend.ui_web.agent_modes.cancel_agent", lambda conv_id=None: stopped.append(conv_id))
    cancel = threading.Event()
    token = runner._CANCEL.set(cancel)
    try:
        release = runner._cancel_agent_on_stop("launch-ducky")
        cancel.set()  # the user pressed Stop
        deadline = time.time() + 3
        while not stopped and time.time() < deadline:
            time.sleep(0.05)
        release()
    finally:
        runner._CANCEL.reset(token)
    assert stopped == ["launch-ducky"]


def test_a_ducky_that_answered_is_not_cancelled_later(monkeypatch):
    stopped: list[str] = []
    monkeypatch.setattr("frontend.ui_web.agent_modes.cancel_agent", lambda conv_id=None: stopped.append(conv_id))
    cancel = threading.Event()
    token = runner._CANCEL.set(cancel)
    try:
        runner._cancel_agent_on_stop("done-ducky")()  # answered, watch ended
        cancel.set()
        time.sleep(0.8)
    finally:
        runner._CANCEL.reset(token)
    assert stopped == []
