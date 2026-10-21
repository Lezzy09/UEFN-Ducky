"""Another launch or another Ducky never closes the person's running Ducky.

Oct 21 2026: opening Ducky while it was starting killed it as "wedged" (its server is up
~10 s in), and a test copy of Ducky that quit took the person's Ducky down with it; both
showed as "Ducky closed by itself" with no crash trace.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from frontend import open_files
from frontend.ui_web import webview_app


def test_a_starting_ducky_is_waited_for_not_killed(monkeypatch) -> None:
    tries: list[float] = []
    monkeypatch.setattr(open_files, "read_living_panel_pid", lambda: 4242)
    monkeypatch.setattr(open_files, "try_handoff_to_running",
                        lambda paths, links=None, **kw: tries.append(kw.get("timeout_s", 0.35)) or len(tries) >= 4)
    monkeypatch.setattr(webview_app, "_ducky_process_alive", lambda pid: True)
    assert webview_app._hand_off_to_living_panel([], []) is True
    assert len(tries) == 4  # answered on the fourth try, ~6 s in: handed off, nothing reclaimed


def test_a_dead_or_stale_panel_pid_is_not_waited_on(monkeypatch) -> None:
    tries: list[int] = []
    monkeypatch.setattr(open_files, "read_living_panel_pid", lambda: 4242)
    monkeypatch.setattr(open_files, "try_handoff_to_running", lambda paths, links=None, **kw: tries.append(1) and False)
    monkeypatch.setattr(webview_app, "_ducky_process_alive", lambda pid: False)
    assert webview_app._hand_off_to_living_panel([], []) is False
    assert len(tries) == 1  # one short try, then a normal cold start


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell filter")
def test_quitting_reaps_bridges_never_another_ducky_window() -> None:
    from frontend.app_paths import bridge_ps_filter

    rows = (
        "@([pscustomobject]@{Name='UEFN-Ducky.exe'; CommandLine='\"C:\\x\\UEFN-Ducky.exe\"'},"
        "[pscustomobject]@{Name='UEFN-Ducky-Bridge.exe'; CommandLine='\"C:\\x\\UEFN-Ducky-Bridge.exe\" bridge --port 4200'},"
        "[pscustomobject]@{Name='UEFN-Ducky.exe'; CommandLine='\"C:\\x\\UEFN-Ducky.exe\" bridge --port 4200 --adapter'},"
        "[pscustomobject]@{Name='UEFN-Ducky.exe'; CommandLine='\"C:\\t\\UEFN-Ducky.exe\" --profile testbed'})"
    )
    script = f"{rows} | Where-Object {{ {bridge_ps_filter()} }} | ForEach-Object {{ $_.CommandLine }}"
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    picked = [line.strip() for line in out if line.strip()]
    assert len(picked) == 2 and all(" bridge " in line for line in picked)  # two bridges, no window
