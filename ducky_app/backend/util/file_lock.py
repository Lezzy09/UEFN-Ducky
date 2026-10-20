"""Named OS file locks shared by every UEFN Ducky process (the app and its MCP bridges)."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Any, Iterator

_log = logging.getLogger(__name__)
_HELD = threading.local()  # lock names this thread holds


def _try_lock(handle: Any) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def held_file_lock(name: str, wait: float) -> Iterator[bool]:
    """Hold ``locks/<name>.lock`` in the app data folder: an OS lock, so two processes never
    hold it at once and one that dies frees it. Yields False when another holder still has
    it after ``wait`` seconds. A thread that already holds it gets it again at once (a
    locked step may call another). No lock folder → yields True and runs unlocked."""
    held: set[str] = getattr(_HELD, "names", None) or set()
    _HELD.names = held
    if name in held:
        yield True
        return
    from frontend.app_paths import resolve_app_data_dir

    try:
        folder = resolve_app_data_dir() / "locks"
        folder.mkdir(parents=True, exist_ok=True)
        handle = open(folder / f"{name}.lock", "a+b")  # noqa: SIM115 — closed below
    except OSError:
        _log.debug("no %s lock; running without it", name, exc_info=True)
        yield True
        return
    with handle:
        deadline = time.monotonic() + max(0.0, wait)
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.2)
        held.add(name)
        try:
            yield True
        finally:
            held.discard(name)
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
