"""Supervisor: one host per 4 agents, hosts die with the app, idle hosts exit."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from frontend.agent_host import supervisor

_DUCKY_APP = str(Path(__file__).resolve().parents[2])
_FAKE_APP = """
import sys, time
sys.path.insert(0, sys.argv[1])
from frontend.agent_host import supervisor
sup = supervisor.Supervisor(log_dir=__import__("pathlib").Path(sys.argv[2]))
for i in range(6):
    sup.assign(f"c{i}")
for h in sup.hosts():
    assert h.ready.wait(60), "host never connected"
print(" ".join(str(h.pid) for h in sup.hosts()), flush=True)
time.sleep(120)
"""


def _gone(pids: list[int], within_s: float) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if not any(psutil.pid_exists(p) for p in pids):
            return True
        time.sleep(0.1)
    return False


def test_six_agents_get_two_hosts(tmp_path):
    sup = supervisor.Supervisor(log_dir=tmp_path)
    try:
        seats = [sup.assign(f"c{i}") for i in range(6)]
        hosts = sup.hosts()
        assert len(hosts) == 2
        assert sorted(len(h.agents) for h in hosts) == [2, 4]
        assert sup.assign("c0") is seats[0]  # a chat keeps its host
        for h in hosts:
            assert h.ready.wait(60), (tmp_path / f"host-{h.slot}.log").read_text(errors="replace")
        assert [r["agents"] for r in sorted(sup.snapshot(), key=lambda r: r["slot"])] == [len(h.agents) for h in
                                                                                           sorted(hosts, key=lambda h: h.slot)]
    finally:
        sup.stop_all()


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows-only")
def test_killing_the_app_kills_its_hosts(tmp_path):
    app = subprocess.Popen([sys.executable, "-c", _FAKE_APP, _DUCKY_APP, str(tmp_path)], stdout=subprocess.PIPE,
                           text=True)
    try:
        line = app.stdout.readline()  # type: ignore[union-attr]
        pids = [int(p) for p in line.split()]
        assert len(pids) == 2, line
        assert all(psutil.pid_exists(p) for p in pids)
        app.kill()
        assert _gone(pids, 10.0)
    finally:
        app.kill()
        app.wait(10)


def test_idle_host_exits_after_timeout(tmp_path):
    sup = supervisor.Supervisor(log_dir=tmp_path, idle_exit_s=0.5, reap_s=0.1)
    try:
        host = sup.assign("c1")
        assert host.ready.wait(60)
        sup.reap()
        assert host.alive(), "a host with an agent never idles out"
        sup.release("c1")
        assert _gone([host.pid], 10.0)
        assert sup.hosts() == []
        assert sup.assign("c2") is not host  # the next turn starts a fresh host
    finally:
        sup.stop_all()
