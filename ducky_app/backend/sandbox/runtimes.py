"""Portable runtimes for sandboxes: Node, uv (and Python through it), Git.

Pinned versions, each zip checked against its publisher's SHA-256 before it is unpacked
into one shared folder (``tools/sandbox``) every sandbox's PATH includes. Nothing is
installed system-wide and nothing outside that folder changes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

from backend.sandbox import paths
from backend.sandbox.fetch import FetchError, download

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

RUNTIMES: dict[str, dict[str, str]] = {
    "node": {
        "version": "24.21.0",
        "url": "https://nodejs.org/dist/v24.21.0/node-v24.21.0-win-x64.zip",
        "sha256": "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
        "folder": "node-24.21.0",
        "strip": "node-v24.21.0-win-x64",
        "check": "node.exe",
    },
    "uv": {
        "version": "0.12.23",
        "url": "https://github.com/astral-sh/uv/releases/download/0.12.23/uv-x86_64-pc-windows-msvc.zip",
        "sha256": "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90",
        "folder": "uv-0.12.23",
        "strip": "",
        "check": "uv.exe",
    },
    "git": {
        "version": "2.56.0.2",
        "url": "https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.2/MinGit-2.56.0.2-64-bit.zip",
        "sha256": "da35e72aa21c005a5a0d298cfbae110bc1609a815730ea0dde84b01a1b3cd3be",
        "folder": "git-2.56.0.2",
        "strip": "",
        "check": "cmd/git.exe",
    },
}
PYTHON_VERSION = "3.12"
_lock = threading.Lock()


def installed() -> dict[str, str]:
    """Runtimes ready now: name -> folder."""
    base = paths.tools_root()
    out: dict[str, str] = {}
    for name, spec in RUNTIMES.items():
        folder = base / spec["folder"]
        if (folder / spec["check"]).is_file():
            out[name] = str(folder)
    py = python_exe()
    if py:
        out["python"] = py
    return out


def python_exe() -> str:
    for exe in sorted((paths.tools_root() / "uv-python").glob("cpython-*/python.exe"), reverse=True):
        return str(exe)
    return ""


def _unzip(zip_path: Path, dest: Path, strip: str) -> None:
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        base = tmp.resolve()
        for member in zf.infolist():
            target = (tmp / member.filename).resolve()
            if os.path.commonpath([str(base), str(target)]) != str(base):
                raise FetchError(f"unsafe path in the archive: {member.filename}")
        zf.extractall(tmp)
    src = tmp / strip if strip else tmp
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    os.replace(src, dest)
    shutil.rmtree(tmp, ignore_errors=True)


def setup(runtime: str) -> dict[str, Any]:
    """Make ``runtime`` (node, uv, python, git) ready; does nothing when it already is."""
    name = (runtime or "").strip().lower()
    if name == "python":
        uv = setup("uv")
        if not uv.get("ok"):
            return uv
        if python_exe():
            return {"ok": True, "runtime": "python", "path": python_exe(), "already": True}
        env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(paths.tools_root() / "uv-python"))
        uv_exe = str(Path(uv["path"]) / "uv.exe")
        proc = subprocess.run([uv_exe, "python", "install", PYTHON_VERSION], env=env, capture_output=True, text=True,
                              errors="replace", timeout=900, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
        if proc.returncode != 0 or not python_exe():
            return {"ok": False, "error": (proc.stderr or proc.stdout or "uv python install failed").strip()[-800:]}
        return {"ok": True, "runtime": "python", "path": python_exe(), "version": PYTHON_VERSION}
    spec = RUNTIMES.get(name)
    if spec is None:
        return {"ok": False, "error": "runtime must be node, python, uv or git."}
    if sys.platform != "win32":
        return {"ok": False, "error": "Portable runtimes are set up on Windows only."}
    base = paths.tools_root()
    folder = base / spec["folder"]
    with _lock:
        if (folder / spec["check"]).is_file():
            return {"ok": True, "runtime": name, "path": str(folder), "version": spec["version"], "already": True}
        base.mkdir(parents=True, exist_ok=True)
        zip_path = base / f"{spec['folder']}.zip"
        try:
            got = download(spec["url"], zip_path, expect_sha256=spec["sha256"], max_bytes=300 * 1024 * 1024)
            _unzip(zip_path, folder, spec["strip"])
        except (FetchError, OSError, zipfile.BadZipFile) as exc:
            return {"ok": False, "error": f"Setting up {name} failed: {exc}"}
        finally:
            zip_path.unlink(missing_ok=True)
    return {"ok": True, "runtime": name, "path": str(folder), "version": spec["version"], "sha256": got["sha256"]}
