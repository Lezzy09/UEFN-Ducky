"""proc_exec — Stop asks the adapter first and kills only after the grace time."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.coding_agents import proc_exec

_WAIT_FOR_FLAG = (
    "import os, sys, time\n"
    "flag = sys.argv[1]\n"
    "while not os.path.exists(flag):\n"
    "    time.sleep(0.05)\n"
    "print('clean exit', flush=True)\n"
)


def _run(tmp_path, conv_id, requester=None, cancel_after=0.2):
    script = tmp_path / "child.py"
    script.write_text(_WAIT_FOR_FLAG, encoding="utf-8")
    flag = tmp_path / f"{conv_id}.flag"
    proc_exec.set_stop_requester(conv_id, requester(flag) if requester else None)
    cancel = threading.Event()
    threading.Timer(cancel_after, cancel.set).start()
    lines: list[str] = []
    started = time.monotonic()
    try:
        result = proc_exec.run_streaming_process(
            argv=[sys.executable, str(script), str(flag)], cwd=str(tmp_path), env_extra={},
            conv_id=conv_id, on_line=lines.append, timeout_s=0.0, cancel=cancel,
        )
    finally:
        proc_exec.set_stop_requester(conv_id, None)
    return result, lines, time.monotonic() - started - cancel_after


def test_an_adapter_that_stops_is_never_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(proc_exec, "STOP_GRACE_S", 10.0)
    result, lines, _ = _run(tmp_path, "stop-ok", requester=lambda flag: (lambda: flag.write_text("x")))
    assert result.cancelled and result.returncode == 0
    assert lines == ["clean exit"]


def test_an_adapter_that_ignores_stop_is_killed_after_the_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(proc_exec, "STOP_GRACE_S", 0.5)
    result, lines, waited = _run(tmp_path, "stop-ignored", requester=lambda flag: (lambda: True))
    assert result.cancelled and result.returncode != 0 and lines == []
    assert waited >= 0.45


def test_no_request_stop_kills_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(proc_exec, "STOP_GRACE_S", 10.0)
    result, lines, waited = _run(tmp_path, "stop-none")
    assert result.cancelled and result.returncode != 0 and lines == []
    assert waited < 5.0


def test_a_second_stop_kills_during_the_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(proc_exec, "STOP_GRACE_S", 30.0)
    threading.Timer(0.8, lambda: proc_exec.terminate_conv_process("stop-twice")).start()
    result, lines, waited = _run(tmp_path, "stop-twice", requester=lambda flag: (lambda: True))
    assert result.cancelled and result.returncode != 0 and lines == []
    assert waited < 10.0
