"""reload_listener re-imports from AppData even when another tree is ahead of it.

Regression: reload only inserted AppData when it was absent from ``sys.path``.
After launch_listener.py ran from the repo, the repo sat at index 0, every
reload re-imported the repo copy, the stamp never matched AppData, and the
host auto-reloaded 112 times in one session.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_LISTENER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def system(monkeypatch):
    monkeypatch.setitem(sys.modules, "unreal", MagicMock(name="unreal"))
    for name in [m for m in sys.modules if m == "listener" or m.startswith("listener.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", [str(_LISTENER_ROOT), *sys.path])

    import listener.handlers.system as mod

    return mod


def test_appdata_moves_ahead_of_dev_checkout(system, monkeypatch):
    repo, appdata = r"C:\dev\uefn_listener", r"C:\Users\x\AppData\Local\UEFN-Ducky\listener"
    monkeypatch.setattr(sys, "path", [repo, appdata, r"C:\python\Lib"])

    system._put_first_on_sys_path(appdata)

    assert sys.path == [appdata, repo, r"C:\python\Lib"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path case and separator folding")
def test_duplicates_with_other_spelling_are_dropped(system, monkeypatch):
    appdata = r"C:\Users\x\AppData\Local\UEFN-Ducky\listener"
    monkeypatch.setattr(sys, "path", ["C:/Users/x/AppData/Local/UEFN-Ducky/listener", r"C:\other"])

    system._put_first_on_sys_path(appdata)

    assert sys.path == [appdata, r"C:\other"]
