"""Calls in flight right now, per source and method (window bridge, panel HTTP).

A freeze had 539 bridge calls waiting at once and nothing showed it while it
happened; ``top()`` is what ducky_health prints for that.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

# A call this old never comes back (its reply was lost): count it, stop listing it.
LOST_AFTER_S = 600.0

_clock = time.monotonic
_lock = threading.Lock()
_live: dict[int, tuple[str, str, float]] = {}
_tokens = itertools.count(1)
_lost = 0


def enter(source: str, method: str) -> int:
    """Start counting one call; pass the token to ``leave`` when it is answered."""
    token = next(_tokens)
    with _lock:
        _live[token] = (str(source), str(method), _clock())
    return token


def leave(token: int | None) -> None:
    if token is None:
        return
    with _lock:
        _live.pop(token, None)


def _sweep(now: float) -> None:
    global _lost
    old = [t for t, (_s, _m, t0) in _live.items() if now - t0 >= LOST_AFTER_S]
    for t in old:
        del _live[t]
    _lost += len(old)


def top(n: int = 5) -> list[dict[str, Any]]:
    """The ``n`` busiest (source, method) pairs, most calls first, then oldest."""
    now = _clock()
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    with _lock:
        _sweep(now)
        for source, method, t0 in _live.values():
            row = rows.get((source, method))
            if row is None:
                row = rows[(source, method)] = {"source": source, "method": method, "count": 0, "oldest_s": 0.0}
            row["count"] += 1
            row["oldest_s"] = max(row["oldest_s"], round(now - t0, 1))
    return sorted(rows.values(), key=lambda r: (-r["count"], -r["oldest_s"]))[: max(0, int(n))]


def total() -> int:
    with _lock:
        _sweep(_clock())
        return len(_live)


def lost() -> int:
    with _lock:
        _sweep(_clock())
        return _lost
