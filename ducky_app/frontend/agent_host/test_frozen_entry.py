"""The installed EXE starts at frontend.launcher.main: ``agent-host`` runs the host there, never a second app."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from frontend import launcher
from frontend.agent_host import main as host_main


def test_agent_host_argv_runs_the_host_not_the_app(monkeypatch):
    got = []
    monkeypatch.setattr(sys, "argv", ["UEFN-Ducky.exe", "agent-host", "--slot", "0", "--pipe", "p"])
    monkeypatch.setattr(host_main, "main", lambda args: got.append(args) or 0)
    monkeypatch.setattr(launcher, "scrub_pyinstaller_boot_env", lambda: None)
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(inject_into_ssl=lambda: None))

    def _app(*_a, **_k):
        raise AssertionError("agent-host booted the app (splash, hand-off) instead of the host")

    for name in ("_sweep_stale_extracts", "_wait_for_previous_version", "_hand_off_to_newest", "run_bridge"):
        monkeypatch.setattr(launcher, name, _app)
    with pytest.raises(SystemExit) as ended:
        launcher.main()
    assert ended.value.code == 0
    assert got == [["--slot", "0", "--pipe", "p"]]
