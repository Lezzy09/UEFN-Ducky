"""A message the person sends into a running turn ("Send now").

It waits here until the agent's next Ducky tool call, which hands it over with that
tool's result (backend/server.py), so the turn takes it in and keeps going instead of
being stopped and re-run. Whatever no tool call picked up is dropped when the turn ends:
the composer still holds it in its queue and sends it as the next turn.

A tool call leases the messages (``take``) and confirms once it attached them (``ack``);
a lease nobody confirms within ``LEASE_S`` puts them back in the queue, so a tool server
that gave up waiting never loses what the person wrote.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

PushFn = Callable[[dict[str, Any]], None]

LEASE_S = 12.0  # just above the 10 s steer_take timeout

_lock = threading.Lock()
# Each item: {"id", "text", "lease": lease id or "" while queued, "at": lease time}.
_inbox: dict[str, list[dict[str, Any]]] = {}
_run_push: dict[str, PushFn] = {}
_now = time.monotonic


def _expire(box: list[dict[str, Any]]) -> None:
    """Return unconfirmed leases to the queue. Call under ``_lock``."""
    # ponytail: lazy on every take/post/has_queued instead of a 2 s timer; nothing else reads the box.
    now = _now()
    for m in box:
        if m["lease"] and now - m["at"] >= LEASE_S:
            m["lease"] = ""


def post(conv_id: str, steer_id: str, text: str) -> bool:
    """Hold ``text`` for the chat's running turn. False when no turn runs (send it normally)."""
    from frontend.ui_web.agent_modes import is_agent_running

    cid = str(conv_id or "").strip()
    body = str(text or "").strip()
    sid = str(steer_id or "").strip()
    if not body:  # taken back out of the queue (edited or deleted), leased copies too
        with _lock:
            if cid in _inbox:
                _inbox[cid] = [m for m in _inbox[cid] if m["id"] != sid]
        return False
    if not cid or not sid or not is_agent_running(cid):
        return False
    with _lock:
        box = _inbox.setdefault(cid, [])
        _expire(box)
        if not any(m["id"] == sid for m in box):
            box.append({"id": sid, "text": body, "lease": "", "at": 0.0})
    return True


def has_queued(conv_id: str) -> bool:
    """Whether the person wrote something no tool call holds yet (cheap: long tools poll it)."""
    with _lock:
        box = _inbox.get(conv_id)
        if not box:
            return False
        _expire(box)
        return any(not m["lease"] for m in box)


def take(conv_id: str) -> dict[str, Any]:
    """Lease the chat's held messages, oldest first: ``{lease_id, texts, steer_ids}``.

    Nothing while an earlier lease is still open, so a message never rides on two tool results.
    """
    cid = str(conv_id or "").strip()
    lease = {"lease_id": "", "texts": [], "steer_ids": []}
    with _lock:
        box = _inbox.get(cid) or []
        _expire(box)
        if not box or any(m["lease"] for m in box):
            return lease
        lease["lease_id"] = uuid.uuid4().hex
        at = _now()
        for m in box:
            m["lease"], m["at"] = lease["lease_id"], at
            lease["texts"].append(m["text"])
            lease["steer_ids"].append(m["id"])
    return lease


def ack(conv_id: str, lease_id: str) -> list[str]:
    """The tool call attached the leased messages: drop them; each shows as the person's bubble."""
    cid = str(conv_id or "").strip()
    lid = str(lease_id or "").strip()
    if not lid:
        return []
    with _lock:
        box = _inbox.get(cid) or []
        done = [m for m in box if m["lease"] == lid]
        if done:
            _inbox[cid] = [m for m in box if m["lease"] != lid]
        push = _run_push.get(cid)
    if not done:
        return []
    if push is None:
        from frontend.ui_web.agent_modes import get_panel_push

        push = get_panel_push()
    for m in done:
        if push is not None:
            push({"type": "user_steered", "conv_id": cid, "steer_id": m["id"], "text": m["text"]})
    return [m["text"] for m in done]


def bind_run(conv_id: str, push: PushFn) -> None:
    """The running turn's own push, so its checkpoint keeps the message in the saved turn."""
    with _lock:
        _run_push[conv_id] = push


def end_run(conv_id: str) -> None:
    with _lock:
        _inbox.pop(conv_id, None)
        _run_push.pop(conv_id, None)
