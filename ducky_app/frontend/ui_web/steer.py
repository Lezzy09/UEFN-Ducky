"""A message the person sends into a running turn ("Send now").

It waits here until the agent's next Ducky tool call, which hands it over with that
tool's result (backend/server.py), so the turn takes it in and keeps going instead of
being stopped and re-run. Whatever no tool call picked up is dropped when the turn ends:
the composer still holds it in its queue and sends it as the next turn.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

PushFn = Callable[[dict[str, Any]], None]

_lock = threading.Lock()
_inbox: dict[str, list[dict[str, str]]] = {}
_run_push: dict[str, PushFn] = {}


def post(conv_id: str, steer_id: str, text: str) -> bool:
    """Hold ``text`` for the chat's running turn. False when no turn runs (send it normally)."""
    from frontend.ui_web.agent_modes import is_agent_running

    cid = str(conv_id or "").strip()
    body = str(text or "").strip()
    sid = str(steer_id or "").strip()
    if not body:  # taken back out of the queue (edited or deleted) before a tool call took it
        with _lock:
            if cid in _inbox:
                _inbox[cid] = [m for m in _inbox[cid] if m["id"] != sid]
        return False
    if not cid or not sid or not is_agent_running(cid):
        return False
    with _lock:
        box = _inbox.setdefault(cid, [])
        if not any(m["id"] == sid for m in box):
            box.append({"id": sid, "text": body})
    return True


def take(conv_id: str) -> list[str]:
    """The chat's held messages, oldest first; each shows as the person's bubble where it landed."""
    cid = str(conv_id or "").strip()
    with _lock:
        box = _inbox.pop(cid, [])
        push = _run_push.get(cid)
    if not box:
        return []
    if push is None:
        from frontend.ui_web.agent_modes import get_panel_push

        push = get_panel_push()
    for m in box:
        if push is not None:
            push({"type": "user_steered", "conv_id": cid, "steer_id": m["id"], "text": m["text"]})
    return [m["text"] for m in box]


def bind_run(conv_id: str, push: PushFn) -> None:
    """The running turn's own push, so its checkpoint keeps the message in the saved turn."""
    with _lock:
        _run_push[conv_id] = push


def end_run(conv_id: str) -> None:
    with _lock:
        _inbox.pop(conv_id, None)
        _run_push.pop(conv_id, None)
