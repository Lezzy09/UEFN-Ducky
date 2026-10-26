"""Two app releases in one checkout refuse to run together (Oct 26: both bumped
__version__ and the first failed packing a version that no longer existed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RELEASE = Path(__file__).resolve().parents[1] / "release"


def _load():
    spec = importlib.util.spec_from_file_location("publish_app_lock_test", RELEASE / "publish_app.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_a_second_release_exits_while_the_first_holds_the_lock(tmp_path: Path):
    pa = _load()
    lock = tmp_path / "dist" / ".publish_app.lock"
    first = pa.hold_release_lock(lock)
    with pytest.raises(SystemExit, match="Another release is already running"):
        pa.hold_release_lock(lock)
    first.close()
    pa.hold_release_lock(lock).close()  # free again once the first run is gone
