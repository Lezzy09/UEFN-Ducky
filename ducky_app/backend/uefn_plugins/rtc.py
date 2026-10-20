"""WebRTC for the spaces provider: the app's main window opens peer connections to other
Duckies and moves bytes over them; this module carries the provider's asks to that window
(``rtc_cmd`` events) and the window's answers and news back (``PanelApi.rtc_reply`` /
``rtc_event``).

Bytes only. Which Duckies connect, rooms, keys and what the bytes mean belong to the
provider (:func:`backend.uefn_plugins.spaces.rtc_bridge` hands this out to it alone). Each
peer has two DataChannels: ``live`` (ordered, reliable) and ``live-fast`` (unordered, no
retransmits: pointers). An offer and an answer carry every ICE candidate, so one message
each way sets up a link.
"""

from __future__ import annotations

import base64
import logging
import re
import threading
import uuid
from typing import Any, Callable

_log = logging.getLogger(__name__)

CHANNELS = ("live", "live-fast")
REPLY_WAIT_S = 15.0
MAX_SEND_BYTES = 64 * 1024
STATES = frozenset({"new", "connecting", "connected", "disconnected", "failed", "closed"})
# The STUN list the phone's Remote View uses (web/src/remote/protocol.ts DEFAULT_ICE).
DEFAULT_ICE: list[dict[str, Any]] = [
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun.l.google.com:19302"},
]
_PEER_RE = re.compile(r"^[A-Za-z0-9:._-]{1,160}$")


class RtcError(RuntimeError):
    """The window couldn't do what was asked (no window, a bad description, a timeout)."""


def _window_push(event: dict[str, Any]) -> None:
    from frontend.ui_web.panel_httpd import publish_panel_events

    publish_panel_events([event])


def _sdp(desc: Any, kind: str) -> dict[str, str]:
    if not isinstance(desc, dict) or desc.get("type") != kind or not isinstance(desc.get("sdp"), str):
        raise RtcError(f"invalid {kind}")
    sdp = desc["sdp"]
    if not sdp or len(sdp) > 32 * 1024:
        raise RtcError(f"invalid {kind}")
    return {"type": kind, "sdp": sdp}


def _peer(peer: str) -> str:
    peer = str(peer or "")
    if not _PEER_RE.match(peer):
        raise RtcError("invalid peer id")
    return peer


class Bridge:
    """One app's peer connections, hosted by its main window."""

    def __init__(self, push: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._push = push or _window_push
        self._lock = threading.Lock()
        self._waiters: dict[str, threading.Event] = {}
        self._replies: dict[str, dict[str, Any]] = {}
        self.on_message: Callable[[str, str, bytes], None] | None = None
        self.on_state: Callable[[str, str], None] | None = None

    # -- the provider's asks

    def _ask(self, op: str, timeout: float = REPLY_WAIT_S, **params: Any) -> dict[str, Any]:
        rid = uuid.uuid4().hex
        ev = threading.Event()
        with self._lock:
            self._waiters[rid] = ev
        try:
            self._push({"type": "rtc_cmd", "id": rid, "op": op, **params})
            if not ev.wait(timeout):
                raise RtcError("No UEFN Ducky window answered (is the app window open?)")
            with self._lock:
                got = self._replies.pop(rid, {})
        finally:
            with self._lock:
                self._waiters.pop(rid, None)
                self._replies.pop(rid, None)
        if got.get("error"):
            raise RtcError(str(got["error"])[:300])
        return got

    def open(self, peer: str, ice: list[dict[str, Any]] | None = None) -> dict[str, str]:
        """A new connection to ``peer``: its offer, with every ICE candidate in it."""
        got = self._ask("open", peer=_peer(peer), ice=list(ice or DEFAULT_ICE))
        return _sdp(got.get("offer"), "offer")

    def accept(self, peer: str, offer: dict[str, Any], ice: list[dict[str, Any]] | None = None) -> dict[str, str]:
        """``peer``'s offer: the answer to send back."""
        got = self._ask("accept", peer=_peer(peer), offer=_sdp(offer, "offer"), ice=list(ice or DEFAULT_ICE))
        return _sdp(got.get("answer"), "answer")

    def finish(self, peer: str, answer: dict[str, Any]) -> None:
        """``peer`` answered the offer :meth:`open` made."""
        self._ask("finish", peer=_peer(peer), answer=_sdp(answer, "answer"))

    def send(self, peer: str, channel: str, data: bytes) -> None:
        """Bytes to ``peer`` (no wait: a closed link drops them; the provider sees its state)."""
        if channel not in CHANNELS:
            raise RtcError("unknown channel")
        if len(data) > MAX_SEND_BYTES:
            raise RtcError("message too big")
        self._push({"type": "rtc_cmd", "op": "send", "peer": _peer(peer), "channel": channel,
                    "data": base64.b64encode(bytes(data)).decode("ascii")})

    def close(self, peer: str) -> None:
        try:
            self._push({"type": "rtc_cmd", "op": "close", "peer": _peer(peer)})
        except RtcError:
            pass

    # -- the window's answers and news

    def reply(self, rid: str, result: Any) -> bool:
        with self._lock:
            ev = self._waiters.get(str(rid or ""))
            if ev is None:
                return False
            self._replies[str(rid)] = dict(result) if isinstance(result, dict) else {"error": "bad reply"}
        ev.set()
        return True

    def event(self, peer: str, kind: str, payload: Any) -> None:
        """``message`` (``{channel, data}`` base64) or ``state`` (``{state}``) from the window."""
        try:
            peer = _peer(peer)
        except RtcError:
            return
        body = payload if isinstance(payload, dict) else {}
        try:
            if kind == "message" and self.on_message is not None:
                channel = str(body.get("channel") or "")
                if channel in CHANNELS:
                    data = base64.b64decode(str(body.get("data") or ""), validate=True)
                    if len(data) <= MAX_SEND_BYTES:
                        self.on_message(peer, channel, data)
            elif kind == "state" and self.on_state is not None:
                state = str(body.get("state") or "")
                if state in STATES:
                    self.on_state(peer, state)
        except Exception:  # noqa: BLE001 — a provider callback never breaks the window's call
            _log.debug("rtc %s from %s failed", kind, peer, exc_info=True)


_BRIDGE: Bridge | None = None
_BRIDGE_LOCK = threading.Lock()


def bridge() -> Bridge:
    """This app's one bridge. Hand it out through :func:`spaces.rtc_bridge` only."""
    global _BRIDGE
    with _BRIDGE_LOCK:
        if _BRIDGE is None:
            _BRIDGE = Bridge()
        return _BRIDGE


def reset_for_tests(fake: Bridge | None = None) -> None:
    global _BRIDGE
    with _BRIDGE_LOCK:
        _BRIDGE = fake
