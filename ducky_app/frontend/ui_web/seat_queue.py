"""One cap on team-member turns running at once, across every team (K3 seat queue).

Oct 24 2026: 16 agents made the app lag (GIL-capped app, a 539-thread UI herd, chats taking
10–45 s). Keeper wakes and plan dispatches ask ``request`` before starting a member's turn:
under the cap it starts now, over it the seat waits in one FIFO line and starts when a turn
ends (``on_turn_end``). The cap sits on top of the memory admission (admission.py), so there
is one gate: a seat starts only while fewer than ``limit()`` member turns run *and* admission
has memory room; the running count is admission's own slots plus seats this queue is starting.
``limit()`` defaults from CPU cores and RAM (``pc_limit``); the card's "Run at once" slider
(``set_run_at_once``) can lower it, never raise it past the PC limit.

First turns start in waves (``WAVE_SIZE`` per ``WAVE_GAP_S``): 3 of 14 seats opened with
"Ducky's tools didn't connect" when all started at once. A turn that ended that way never
really ran, so the seat is idle again (``is_busy`` False): a restart or recycle may go ahead.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from frontend.ui_web import admission

PushFn = Callable[[dict[str, Any]], None]

WAVE_SIZE = 3
WAVE_GAP_S = 5.0
_START_FAILED_RE = re.compile(
    r"tools didn.t connect|(?:backend|agent) (?:start error|failed to start)|could not start", re.I)


@dataclass
class _Seat:
    conv_id: str
    start: Callable[[], Any]


_lock = threading.RLock()
_line: deque[_Seat] = deque()
_starting: set[str] = set()  # handed to start(), not yet holding an admission slot
_user_cap: int | None = None
_seen: set[str] = set()  # seats whose first turn has started
_first_starts: deque[float] = deque()  # when first turns started, for the waves
_wave_timer = False
_now = time.monotonic


def _spawn(fn: Callable[[], None], name: str) -> None:
    threading.Thread(target=fn, daemon=True, name=name).start()


def _spawn_later(delay: float, fn: Callable[[], None]) -> None:
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    timer.start()


def start_failed(detail: str) -> bool:
    """The turn ended before the agent really ran (its tools or its backend never came up)."""
    return bool(_START_FAILED_RE.search(detail or ""))


def total_memory_gb() -> float:
    try:
        import ctypes

        kb = ctypes.c_ulonglong()
        if ctypes.WinDLL("kernel32").GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return kb.value / 1024**2
    except (AttributeError, OSError):
        pass
    try:
        import psutil

        return psutil.virtual_memory().total / 1024**3
    except Exception:
        return 16.0


def pc_limit() -> int:
    """Turns this PC can run at once: one per two cores and per 2 GB of RAM, at least 2."""
    # ponytail: fixed per-agent cost (half a core, 2 GB); measure real agent use if it misjudges.
    cores = os.cpu_count() or 4
    return max(2, min(cores // 2, int(total_memory_gb() // 2)))


def limit() -> int:
    pc = pc_limit()
    return min(pc, _user_cap) if _user_cap else pc


def set_run_at_once(n: int | None) -> int:
    """The "Run at once" slider: lowers the cap (0 / None = the PC limit). Returns the cap."""
    global _user_cap
    with _lock:
        _user_cap = max(1, min(int(n), pc_limit())) if n else None
    drain()
    return limit()


def _running() -> set[str]:
    """Call under ``_lock``."""
    with admission._lock:
        held = set(admission._running)
    return held | _starting


def _room(running: int) -> bool:
    if running >= limit():
        return False
    return running < admission.FLOOR or admission._read_free() >= admission.START_FREE_GB


def is_busy(conv_id: str) -> bool:
    """True while the seat runs a turn or waits in line (a restart would be refused)."""
    with _lock:
        return conv_id in _running() or any(s.conv_id == conv_id for s in _line)


def request(conv_id: str, start: Callable[[], Any]) -> str:
    """Start a member's turn under the cap. ``start`` begins the turn (e.g. run_message).

    Returns ``started``, ``queued`` (it starts when a turn ends) or ``busy`` (already running
    or waiting: nothing added).
    """
    with _lock:
        if is_busy(conv_id):
            return "busy"
        _line.append(_Seat(conv_id, start))
    drain()
    with _lock:
        return "queued" if any(s.conv_id == conv_id for s in _line) else "started"


def drop(conv_id: str) -> None:
    """Take the seat out of the line (Stop)."""
    with _lock:
        for seat in [s for s in _line if s.conv_id == conv_id]:
            _line.remove(seat)


def on_turn_end(conv_id: str, reason: str = "", detail: str = "") -> None:
    """A member's turn ended: free its place and start the next seats in line.

    ``detail`` is the turn's error or reply text; a failed start leaves the seat idle (its
    admission slot freed, its next start counted as a first turn again).
    """
    failed = start_failed(detail)
    with _lock:
        _starting.discard(conv_id)
        if failed:
            _seen.discard(conv_id)
    if failed:
        admission.release(conv_id)
    drain()


def drain() -> int:
    """Start waiting seats, oldest first, while there is room. Returns how many started."""
    global _wave_timer
    started: list[_Seat] = []
    wait = 0.0
    with _lock:
        running = len(_running())
        now = _now()
        while _first_starts and now - _first_starts[0] >= WAVE_GAP_S:
            _first_starts.popleft()
        for seat in list(_line):
            if not _room(running):
                break
            if seat.conv_id not in _seen:
                if len(_first_starts) >= WAVE_SIZE:  # this wave is full: later seats may go
                    wait = WAVE_GAP_S - (now - _first_starts[0])
                    continue
                _seen.add(seat.conv_id)
                _first_starts.append(now)
            _line.remove(seat)
            _starting.add(seat.conv_id)
            started.append(seat)
            running += 1
        if wait > 0 and not _wave_timer:
            _wave_timer = True
        else:
            wait = 0.0
    if wait:
        _spawn_later(wait, _next_wave)
    for seat in started:
        _spawn(lambda s=seat: _run(s), f"seat-{seat.conv_id[:8]}")
    return len(started)


def _next_wave() -> None:
    global _wave_timer
    with _lock:
        _wave_timer = False
    drain()


def _run(seat: _Seat) -> None:
    try:
        seat.start()
    except Exception:
        with _lock:
            _starting.discard(seat.conv_id)
        drain()
        return
    with _lock:
        # Started: admission now holds its slot until agent_stopped. Queued there or no turn: free.
        _starting.discard(seat.conv_id)
    drain()


def status() -> dict[str, Any]:
    """For the team bar, card and Settings: ``{running, waiting, limit, pc_limit, text}``."""
    with _lock:
        running, waiting = len(_running()), len(_line)
    return {"running": running, "waiting": waiting, "limit": limit(), "pc_limit": pc_limit(),
            "text": f"{running} running · {waiting} waiting"}
