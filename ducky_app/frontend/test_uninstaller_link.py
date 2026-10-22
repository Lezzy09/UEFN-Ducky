"""The app keeps Apps & features' Uninstall on Ducky's own uninstaller after it updates itself."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from frontend import uninstaller_link as link


@pytest.fixture(autouse=True)
def _seams():
    yield
    link.info_override = None
    link.write_override = None


def _setup(tmp_path: Path, *, scope: str = "user", command: str = '"C:\\x\\unins000.exe"') -> tuple[Path, Path, list[str]]:
    version_dir = tmp_path / "versions" / "1.2.430"
    install_dir = tmp_path / "Programs" / "UEFN Ducky"
    version_dir.mkdir(parents=True)
    install_dir.mkdir(parents=True)
    (version_dir / link.EXE_NAME).write_bytes(b"MZ new uninstaller")
    info: dict[str, Any] = {
        "installed": True,
        "install_location": str(install_dir),
        "install_scope": scope,
        "uninstall_command": command,
    }
    written: list[str] = []
    link.info_override = lambda: info
    link.write_override = written.append
    return version_dir, install_dir, written


def test_copies_the_uninstaller_and_points_the_entry_at_it(tmp_path: Path) -> None:
    version_dir, install_dir, written = _setup(tmp_path)
    assert link.ensure(version_dir) == "copied+registered"
    dest = install_dir / link.EXE_NAME
    assert dest.read_bytes() == b"MZ new uninstaller"
    assert written == [f'"{dest}"']


def test_nothing_to_do_when_already_in_place(tmp_path: Path) -> None:
    version_dir, install_dir, written = _setup(tmp_path)
    dest = install_dir / link.EXE_NAME
    dest.write_bytes(b"MZ new uninstaller")
    link.info_override = lambda: {
        "installed": True, "install_location": str(install_dir), "install_scope": "user", "uninstall_command": f'"{dest}"',
    }
    assert link.ensure(version_dir) == "ok"
    assert written == []


def test_an_older_uninstaller_is_replaced(tmp_path: Path) -> None:
    version_dir, install_dir, _ = _setup(tmp_path)
    (install_dir / link.EXE_NAME).write_bytes(b"MZ old")
    assert link.ensure(version_dir).startswith("copied")
    assert (install_dir / link.EXE_NAME).read_bytes() == b"MZ new uninstaller"


def test_all_users_installs_and_builds_without_it_are_left_alone(tmp_path: Path) -> None:
    version_dir, install_dir, written = _setup(tmp_path, scope="machine")
    assert link.ensure(version_dir).startswith("skip")
    assert not (install_dir / link.EXE_NAME).exists() and written == []
    version_dir, install_dir, written = _setup(tmp_path / "b")
    (version_dir / link.EXE_NAME).unlink()
    assert link.ensure(version_dir).startswith("skip")
    assert written == []


def test_source_runs_never_touch_the_install() -> None:
    assert link.ensure().startswith("skip")
