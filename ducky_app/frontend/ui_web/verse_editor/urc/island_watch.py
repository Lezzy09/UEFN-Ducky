"""Something new arrived: tells the person (and agents) when another PC pushed to the island.

Two PCs share one island through Unreal Revision Control (``revision_push`` /
``revision_pull``). A thread in the app process watches the island UEFN has open:

- the listener's health GET names it (``island_dir``: served off the editor thread, nothing
  queues in UEFN); no listener or no island, nothing runs but that GET;
- one ``lore --remote history 1 --branch main`` per round reads the remote head (~1 s); while
  the island is behind, ``lore status`` too, so a pull made anywhere clears the alert;
- only when one of them moved, ``lore_cli.repo_state`` (3 calls) says which remote revisions
  the island lacks and who made them.

Revisions made on another PC (a check-in of this PC's own autosave doesn't count) give one
alert per new remote head: a Windows notification when no Ducky window is in front, the
account's bell, and an ``island_updates`` panel event (a row in the header's activity list).
It never pulls: a pull swaps the map, so only the person, or a Ducky they ask
(``revision_pull``, which refuses over unsaved work), does it.

What it found is kept in ``workspace_state`` (:data:`KEY`) for every process:
``ducky_get_status`` shows it to agents (:func:`for_agents`).

Rounds: every :data:`ACTIVE_S` while the person uses this PC, :data:`IDLE_S` once they've
been away :data:`notifications.AWAY_S`; a failing lore call backs off to :data:`ERROR_MAX_S`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

ACTIVE_S = 10.0  # the person is at this PC: news shows in ~5 s on average, 10-15 s at worst
IDLE_S = 60.0  # away from the keyboard: the toast waits for them anyway
NO_ISLAND_S = 15.0  # no listener / no island open: only the local health GET
NOT_LORE_S = 120.0  # the open island has no .lore folder
ERROR_MAX_S = 300.0
KEY = "island_updates"  # workspace_state doc

_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_st: dict[str, Any] = {}


def _reset(island: str = "") -> None:
    _st.clear()
    _st.update(island=island, remote_sig="", local_sig="", behind=False, told="", fails=0)
    if island:
        doc = _read_doc()
        if doc and doc.get("island") == island:
            _st["told"] = str(doc.get("told") or "")  # a restart doesn't tell the same news twice


_reset()


# --------------------------------------------------------------------------- seams (tests patch)


def _lore():
    from frontend.ui_web.verse_editor.urc import lore_cli

    return lore_cli


def _open_island() -> str:
    from backend.bridge import listener_get_health
    from frontend.settings import PANEL_LISTENER_PORT

    health = listener_get_health(PANEL_LISTENER_PORT)
    if not health or health.get("status") != "ok":
        return ""
    return os.path.normpath(str(health.get("island_dir") or "")) if health.get("island_dir") else ""


def _person_away() -> bool:
    from frontend import notifications

    idle = notifications._idle_seconds()
    return idle is not None and idle >= notifications.AWAY_S


def _alert(title: str, status: str, detail: str) -> None:
    from frontend.notifications import alert

    alert(title, status, level="info", detail=detail)


def _push(event: dict[str, Any]) -> None:
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event(event)
    except Exception:  # noqa: BLE001 — the alert and the status still say it
        _log.debug("island_updates push failed", exc_info=True)


def _read_doc() -> dict[str, Any] | None:
    try:
        from backend.store.repos import kv

        doc = kv.get_doc("workspace_state", KEY)
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _write_doc(doc: dict[str, Any] | None) -> None:
    try:
        from backend.store.repos import kv

        if doc is None:
            kv.delete_doc("workspace_state", KEY)
        else:
            kv.set_doc("workspace_state", KEY, doc)
    except Exception:  # noqa: BLE001 — agents just don't see it this round
        _log.debug("island_updates doc write failed", exc_info=True)


# --------------------------------------------------------------------------- one round


def news_text(name: str, news: list[dict[str, Any]]) -> str:
    """ "3 new changes on test_ducky_v2 from Mich ou: “moved the cube”" """
    n = len(news)
    authors = list(dict.fromkeys(r["creator"] for r in news if r.get("creator")))
    text = f"{n} new change{'s' if n != 1 else ''} on {name}"
    if authors:
        text += " from " + ", ".join(authors)
    if news and news[0].get("message"):
        text += f": “{news[0]['message']}”"
    return text


def _interval() -> float:
    try:
        return IDLE_S if _person_away() else ACTIVE_S
    except Exception:  # noqa: BLE001
        return ACTIVE_S


def _failed(error: str) -> float:
    _st["fails"] += 1
    _log.debug("island watch: %s", error)
    return min(ERROR_MAX_S, _interval() * (2 ** _st["fails"]))


def _apply(island: str, state: dict[str, Any]) -> None:
    name = Path(island).name
    was_behind = _st["behind"]
    incoming = list(state.get("incoming") or [])
    news = [r for r in incoming if not r.get("own")]
    behind = bool(state.get("behind"))
    _st.update(remote_sig=str(state.get("remote_signature") or ""),
               local_sig=str(state.get("local_signature") or ""), behind=behind)
    text = news_text(name, news) if news else ""
    if behind and news and _st["remote_sig"] != _st["told"]:
        _st["told"] = _st["remote_sig"]
        _alert(name, f"{len(news)} new change{'s' if len(news) != 1 else ''} to pull.",
               f"{text}. Pull when you're ready: ask a Ducky to run revision_pull "
               "(it never pulls over unsaved work).")
        _push({"type": "island_updates", "island": island, "name": name, "behind": True,
               "count": len(news), "detail": text})
    elif was_behind and not behind:
        _push({"type": "island_updates", "island": island, "name": name, "behind": False, "count": 0,
               "detail": f"{name} is up to date."})
    _write_doc({
        "island": island,
        "name": name,
        "behind": behind,
        "new_changes": len(news) if behind else 0,
        "authors": list(dict.fromkeys(r["creator"] for r in news if r.get("creator"))) if behind else [],
        "latest": ({"revision": news[0]["revision"], "by": news[0]["creator"], "message": news[0]["message"]}
                   if behind and news else None),
        "text": text if behind else "",
        "local_revision": state.get("local_revision"),
        "remote_revision": state.get("remote_revision"),
        "told": _st["told"],
        "checked_at": int(time.time()),
        "pid": os.getpid(),
    })


def tick() -> float:
    """One round. Returns the seconds until the next one. Never raises."""
    try:
        island = _open_island()
    except Exception:  # noqa: BLE001
        island = ""
    with _lock:
        if island != _st["island"]:
            _reset(island)
            if not island:
                _write_doc(None)
        if not island:
            return NO_ISLAND_S
        if not (Path(island) / ".lore").is_dir():
            return NOT_LORE_S
        lore = _lore()
        head = lore.remote_head(island)
        if not head.get("ok"):
            return _failed(str(head.get("error") or "remote head"))
        local_moved = False
        if _st["behind"]:
            local = lore.local_head(island)
            if not local.get("ok"):
                return _failed(str(local.get("error") or "local head"))
            local_moved = local["signature"] != _st["local_sig"]
        if head["signature"] == _st["remote_sig"] and not local_moved:
            _st["fails"] = 0
            return _interval()
        state = lore.repo_state(island)
        if not state.get("ok"):
            return _failed(str(state.get("error") or "repo state"))
        _st["fails"] = 0
        _apply(island, state)
        return _interval()


# --------------------------------------------------------------------------- for agents


def for_agents() -> dict[str, Any] | None:
    """What ``ducky_get_status`` shows (any process): the open island's news, or None when
    nothing watches it (the app is closed, no Lore island open)."""
    doc = _read_doc()
    if not doc or not doc.get("island"):
        return None
    pid = int(doc.get("pid") or 0)
    if pid and pid != os.getpid():
        try:
            import psutil

            if not psutil.pid_exists(pid):
                return None
        except Exception:  # noqa: BLE001
            pass
    out = {k: doc.get(k) for k in ("island", "name", "behind", "new_changes", "authors", "latest",
                                   "local_revision", "remote_revision", "checked_at")}
    if doc.get("behind"):
        out["hint"] = ("Another PC pushed changes to this island. Tell the person; pull only when they "
                       "agree (revision_pull never pulls over unsaved work).")
    return out


# --------------------------------------------------------------------------- the thread


def wake() -> None:
    """Check again now (after a pull or push made from this process)."""
    _wake.set()


def _loop() -> None:
    while not _stop.is_set():
        delay = tick()
        _wake.wait(delay)
        _wake.clear()


def start() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="island-watch")
        _thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()


def reset_for_tests() -> None:
    with _lock:
        _reset()
    _wake.clear()
