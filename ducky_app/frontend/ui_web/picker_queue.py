"""A queued answer for the next file picker, so an agent can check a plugin's import flow.

The Windows file picker needs a person at the PC. A plugin team's panel builder could not
check picking, cancelling or importing (Oct 12 2026), so its step waited on the person.
An agent queues the next picker's answer instead: files that exist, or a cancel. It is
used once and expires after ``QUEUE_S``; the picker opens normally otherwise.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

QUEUE_S = 120.0
_lock = threading.Lock()
_queued: dict[str, Any] | None = None


def queue_pick(paths: list[str] | None = None, cancel: bool = False) -> dict[str, Any]:
    global _queued
    files = [str(Path(str(p))) for p in (paths or []) if str(p).strip()]
    missing = [p for p in files if not Path(p).is_file()]
    if missing:
        return {"ok": False, "error": f"not a file: {missing[0]}"}
    if not files and not cancel:
        return {"ok": False, "error": "pass the files to pick, or cancel=true"}
    with _lock:
        _queued = {"paths": [] if cancel else files, "until": time.time() + QUEUE_S}
    return {"ok": True, "next_pick": "cancel" if cancel else files, "expires_in_s": int(QUEUE_S)}


def take_queued_pick() -> list[str] | None:
    """The queued answer (``[]`` = cancel), once; None when nothing is queued."""
    global _queued
    with _lock:
        queued, _queued = _queued, None
    if queued is None or queued["until"] < time.time():
        return None
    return list(queued["paths"])
