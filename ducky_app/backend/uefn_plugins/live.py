"""Live editing for plugins on a team copy: while a plugin is live, teammates live in the
same room get each of its changes, pointers and short messages straight from this PC. The
spaces provider carries them peer to peer (:meth:`spaces.Provider.live_send`); the team
repo stays the record, so every change still becomes a normal commit.

Every plugin gets this with no plugin code:

- a change a live plugin writes (``api.data`` / ``files``) goes to the room at once;
  teammates keep it as a provisional value that reads return until the matching commit
  lands (or :data:`PROVISIONAL_S` pass), and their open panels hear it as a sync
  (``plugin_scope_changed``, ``reason: "synced"``, ``live: true``, the keys);
- the host script in every panel page shows teammates' pointers, names and selections.

A plugin is live in a room: the open project unless it names one, so teammates on other
projects of the same team never see its pointers; a project switch moves it along.

Plugins may add their own short-lived messages (``live.send`` / ``api.live.send``).
Topics under ``ducky.`` are the host's.
"""

from __future__ import annotations

import collections
import json
import logging
import re
import threading
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)

LIMIT_BYTES = 16 * 1024  # one message, as JSON
LIMIT_PER_S = 30  # messages a second per plugin
FAST_PER_S = 25  # pointers and selections a second per plugin
PROVISIONAL_S = 30.0
DOC_INLINE_MAX = 64 * 1024  # a bigger doc travels as a ref and comes with the next pull
CHANGE = "ducky.change"
HOST_TOPICS = frozenset({"ducky.pointer", "ducky.select"})
_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_ROOM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
DEFAULT_ROOM = "all"  # no project open


class _State:
    __slots__ = ("account", "follow", "room", "since", "space")

    def __init__(self, account: str, space: str, room: str, since: float, follow: bool) -> None:
        self.account, self.space, self.room, self.since = account, space, room, since
        self.follow = follow  # the room is the open project's: a switch moves it


_lock = threading.Lock()
_live: dict[str, _State] = {}  # plugin -> where it is live on this PC
# (account, space, plugin, key) -> (doc text or None for a delete, sha, when it came)
_prov: dict[tuple[str, str, str, str], tuple[str | None, str, float]] = {}
_sent: dict[tuple[str, bool], collections.deque[float]] = {}
_listeners: dict[str, dict[str, list[Callable[..., Any]]]] = {}
_kept: set[str] = set()  # folder plugins restarted while live with their panels kept loaded


def _push(event: dict[str, Any]) -> None:
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event(event)
    except Exception:  # noqa: BLE001 — the next status read shows it
        _log.debug("live push failed", exc_info=True)


def _in_bridge() -> bool:
    import os

    return os.environ.get("UEFN_DUCKY_MCP_BRIDGE") == "1"


def _team(plugin: str) -> tuple[str, str] | None:
    """``(account, space)`` of ``plugin``'s team copy, or None when it shows Local."""
    from backend.uefn_plugins import scopes

    scope = scopes.active_scope(plugin)
    if scope.get("kind") != "shared" or scope.get("readOnly"):
        return None
    return str(scope["account"]), str(scope["id"])


def supported(plugin: str) -> tuple[bool, str]:
    """Whether ``plugin`` can go live here, and why not."""
    from backend.uefn_plugins import spaces

    if _in_bridge():
        return False, "Live runs in the UEFN Ducky window."
    team = _team(plugin)
    if team is None:
        return False, "Live works on a team copy."
    try:
        from backend.store.repos import space_vcs

        v2 = space_vcs.head_get(team[0], team[1], plugin)["engine"] == "v2"
    except Exception:  # noqa: BLE001 — an app without heads: no presence to meet in
        v2 = False
    if not v2:
        return False, "Live works once this copy is on the team's new sync."
    impl = spaces.provider()
    try:
        ok = bool(impl.live_supported())
    except Exception:  # noqa: BLE001 — a provider that can't say has no live
        ok = False
    return (True, "") if ok else (False, "This team service has no live editing.")


def _current(plugin: str) -> _State | None:
    """Where ``plugin`` is live, dropped when its data no longer shows that team."""
    with _lock:
        st = _live.get(plugin)
    if st is None:
        return None
    team = _team(plugin)
    if team != (st.account, st.space):
        leave(plugin)
        return None
    return st


def is_live(plugin: str) -> bool:
    with _lock:
        return plugin in _live


def room_of(plugin: str, account: str, space: str) -> dict[str, Any] | None:
    """What presence says of ``plugin`` while it is live in that space."""
    with _lock:
        st = _live.get(plugin)
    if st is None or (st.account, st.space) != (account, space):
        return None
    return {"room": st.room, "since": st.since}


def _beat_soon(account: str, space: str) -> None:
    """Presence carries the room: tell the team now instead of at the next minute's beat."""
    def work() -> None:
        try:
            from backend.store.repos import plugin_data as repo
            from backend.uefn_plugins import spaces, vcs_engine

            plugins = sorted(p for p, s in repo.links(account).items() if s == space)
            team = spaces.ledgers(account, space, plugins)
            if team:
                vcs_engine.beat(account, space, next(iter(team.values())), list(team), force=True)
        except Exception:  # noqa: BLE001 — the scheduler's next beat says it anyway
            _log.debug("live beat failed", exc_info=True)

    threading.Thread(target=work, name="live-beat", daemon=True).start()


def project_room() -> str:
    """The open project's room: its name, the same on every teammate's PC."""
    try:
        from frontend.ui_web.project_switch import get_panel_project_info

        info = get_panel_project_info()
        name = str(info.get("mount") or info.get("name") or "") if info.get("path") else ""
    except Exception:  # noqa: BLE001 — no project: the whole plugin
        name = ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:62]
    return f"p:{name}" if name else DEFAULT_ROOM


def join(plugin: str, room: str = "") -> dict[str, Any]:
    """``plugin`` goes live in ``room`` (default: the open project's, which follows a
    project switch). Joining another room leaves the one it was in."""
    from backend.uefn_plugins import spaces

    follow = not room
    room = str(room or project_room())
    if not _ROOM_RE.match(room):
        return {"ok": False, "error": "A room name is letters, digits, . _ : - (up to 64)."}
    ok, why = supported(plugin)
    if not ok:
        return {"ok": False, "error": why}
    account, space = _team(plugin)  # type: ignore[misc]
    with _lock:
        old = _live.get(plugin)
    if old is not None and (old.account, old.space, old.room) == (account, space, room):
        old.follow = follow
        return {"ok": True, **status(plugin)}
    if old is not None:
        leave(plugin)
    with _lock:
        _live[plugin] = _State(account, space, room, time.time(), follow)
    try:
        spaces.provider().live_join(account, space, plugin, room)
    except Exception as exc:  # noqa: BLE001 — not live after all; say why
        with _lock:
            _live.pop(plugin, None)
        return {"ok": False, "error": f"Couldn't go live: {exc}"}
    _beat_soon(account, space)
    peers_changed(account, space, plugin)
    return {"ok": True, **status(plugin)}


def panels_kept(plugin: str) -> None:
    """A folder plugin restarted for a teammate's pull while live, its panels kept loaded
    (``host._restart_moved``): they reload once when Live ends."""
    with _lock:
        _kept.add(plugin)


def _reload_kept(plugin: str) -> None:
    with _lock:
        if plugin not in _kept:
            return
        _kept.discard(plugin)
    try:
        from backend.store.repos import folder_files

        folder_files.reload_bump(plugin, "live ended")  # the app restarts it with its panels
    except Exception:  # noqa: BLE001 — its next pull or switch reloads them
        _log.debug("reload after live of %s failed", plugin, exc_info=True)


def leave(plugin: str) -> dict[str, Any]:
    from backend.uefn_plugins import spaces

    with _lock:
        st = _live.pop(plugin, None)
        for k in [k for k in _prov if k[2] == plugin]:
            _prov.pop(k, None)
    _reload_kept(plugin)
    if st is not None:
        try:
            spaces.provider().live_leave(st.account, st.space, plugin)
        except Exception:  # noqa: BLE001 — the room lease runs out by itself
            _log.debug("live leave of %s failed", plugin, exc_info=True)
        _beat_soon(st.account, st.space)
        peers_changed(st.account, st.space, plugin)
    return {"ok": True}


def project_changed() -> None:
    """Another project is open: plugins live in the project's room move to the new one's
    (or leave, when the plugin's data no longer shows that team)."""
    with _lock:
        moving = [p for p, st in _live.items() if st.follow]
    room = project_room()
    for plugin in moving:
        with _lock:
            st = _live.get(plugin)
        if st is None or st.room == room:
            continue
        leave(plugin)
        if supported(plugin)[0]:
            join(plugin)


def leave_all() -> None:
    with _lock:
        plugins = list(_live)
    for plugin in plugins:
        leave(plugin)


def _rate_ok(plugin: str, fast: bool) -> bool:
    now = time.monotonic()
    cap = FAST_PER_S if fast else LIMIT_PER_S
    with _lock:
        q = _sent.setdefault((plugin, fast), collections.deque())
        while q and now - q[0] >= 1.0:
            q.popleft()
        if len(q) >= cap:
            return False
        q.append(now)
    return True


def send(plugin: str, topic: str, data: Any, *, to: str = "", fast: bool = False) -> dict[str, Any]:
    """A short message to the room (or to one Ducky, ``to`` = its device id)."""
    from backend.uefn_plugins import spaces

    topic = str(topic or "")
    if topic != CHANGE and topic not in HOST_TOPICS and (topic.startswith("ducky.") or not _TOPIC_RE.match(topic)):
        return {"ok": False, "error": "A topic is a-z, 0-9, . _ - (up to 40); ducky.* is the host's."}
    try:
        text = json.dumps(data, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Live data must be JSON."}
    if len(text) > LIMIT_BYTES:
        return {"ok": False, "error": f"A live message is at most {LIMIT_BYTES // 1024} KB."}
    st = _current(plugin)
    if st is None:
        return {"ok": False, "error": "This plugin isn't live."}
    if not _rate_ok(plugin, fast or topic in HOST_TOPICS):
        return {"ok": False, "error": "Too many live messages: at most 30 a second."}
    try:
        sent = spaces.provider().live_send(st.account, st.space, plugin, topic, json.loads(text),
                                           to=str(to or ""), fast=bool(fast or topic in HOST_TOPICS))
    except Exception as exc:  # noqa: BLE001 — say why instead of failing the caller
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "sent": int(sent or 0)}


def status(plugin: str) -> dict[str, Any]:
    """What the bar shows: ``supported``, ``on``, ``room``, ``state`` and ``peers`` (name,
    user, device, label, path: ``direct`` | ``forwarded`` | ``none``)."""
    from backend.uefn_plugins import spaces

    ok, why = supported(plugin)
    st = _current(plugin)  # a plugin no longer on that team copy leaves its room here
    if st is not None and not ok:
        leave(plugin)
        st = None
    out: dict[str, Any] = {"supported": ok, "reason": why, "on": st is not None,
                           "room": st.room if st else "", "state": "off", "peers": []}
    if st is None:
        return out
    try:
        got = spaces.provider().live_state(st.account, st.space, plugin) or {}
    except Exception:  # noqa: BLE001 — live, peers unknown for now
        got = {}
    out["state"] = str(got.get("state") or "live")
    out["peers"] = [dict(p) for p in got.get("peers") or [] if isinstance(p, dict)][:32]
    return out


# --------------------------------------------------------------------------- changes


def local_change(account: str, space: str, plugin: str, kind: str, key: str, text: str | None, sha: str) -> None:
    """A write of this PC to a team copy (from :class:`scopes.PluginData`): the room gets it
    at once when the plugin is live there. This PC's own write wins over a provisional one."""
    with _lock:
        _prov.pop((account, space, plugin, key), None)
        st = _live.get(plugin)
    if st is None or (st.account, st.space) != (account, space):
        return
    change: dict[str, Any] = {"kind": kind, "key": key, "sha": sha, "deleted": text is None}
    if kind == "doc" and text is not None and len(text) <= DOC_INLINE_MAX:
        change["value"] = text
    try:
        from backend.uefn_plugins import spaces

        spaces.provider().live_send(account, space, plugin, CHANGE, change, to="", fast=False)
    except Exception:  # noqa: BLE001 — the commit brings it anyway
        _log.debug("live change of %s/%s failed", plugin, key, exc_info=True)


def _changed(account: str, space: str, plugin: str, sender: dict[str, Any], change: dict[str, Any]) -> None:
    kind, key = str(change.get("kind") or ""), str(change.get("key") or "")
    if kind not in ("doc", "file") or not key or len(key) > 300:
        return
    from backend.uefn_plugins import scopes

    if scopes.is_local_key(plugin, key):
        return  # this PC's own items never come from a teammate
    if kind == "doc" and (change.get("deleted") or isinstance(change.get("value"), str)):
        value = None if change.get("deleted") else str(change["value"])
        with _lock:
            _prov[(account, space, plugin, key)] = (value, str(change.get("sha") or ""), time.time())
    else:
        # A file, or a doc too big to travel live: the next pull brings it, now.
        try:
            from backend.uefn_plugins import sync_scheduler

            sync_scheduler.wake(account, space, plugin)
        except Exception:  # noqa: BLE001 — the next round brings it
            _log.debug("live wake failed", exc_info=True)
    _push({"type": "plugin_scope_changed", "plugins": [plugin], "synced": True, "live": True,
           "keys": {plugin: [key]}, "by": str(sender.get("name") or "")})


def provisional(account: str, space: str, plugin: str, key: str, row: dict[str, Any] | None) -> tuple[bool, str | None]:
    """``(found, text)``: a teammate's live value for ``key`` that reads return over the
    stored row (``text`` None: they deleted it). The row wins once its content matches, a
    write or pull landed after the live value came, or :data:`PROVISIONAL_S` passed."""
    k = (account, space, plugin, key)
    with _lock:
        got = _prov.get(k)
    if got is None:
        return False, None
    text, sha, at = got
    now = time.time()
    landed = row is not None and (str(row.get("sha256") or "") == sha and sha
                                  or float(row.get("updated") or 0) > at)
    if landed or now - at > PROVISIONAL_S:
        with _lock:
            if _prov.get(k) == got:
                _prov.pop(k, None)
        return False, None
    return True, text


def provisional_keys(account: str, space: str, plugin: str, prefix: str) -> list[str]:
    """Docs under ``prefix`` that only a teammate's live change has so far."""
    with _lock:
        return sorted(k[3] for k in _prov if k[:3] == (account, space, plugin) and k[3].startswith(prefix))


# --------------------------------------------------------------------------- from the provider


def deliver(account: str, space: str, plugin: str, sender: dict[str, Any], topic: str, data: Any) -> None:
    """A message from a teammate live in the same room (the provider opened and checked it)."""
    st = room_of(plugin, account, space)
    if st is None:
        return
    who = {k: str(sender.get(k) or "") for k in ("name", "user", "device", "label")}
    if topic == CHANGE:
        if isinstance(data, dict):
            _changed(account, space, plugin, who, data)
        return
    _push({"type": "live_message", "plugin": plugin, "from": who, "topic": topic, "data": data})
    with _lock:
        callbacks = list(_listeners.get(plugin, {}).get(topic, ()))
    for cb in callbacks:
        try:
            cb(who, data)
        except Exception:  # noqa: BLE001 — a plugin's callback never breaks delivery
            _log.warning("%s: live callback for %s failed", plugin, topic, exc_info=True)


def peers_changed(account: str, space: str, plugin: str) -> None:
    """Who is live with this PC moved: bars and panels hear it."""
    if room_of(plugin, account, space) is None and not is_live(plugin):
        _push({"type": "live_peers", "plugin": plugin, "on": False, "peers": []})
        return
    st = status(plugin)
    _push({"type": "live_peers", "plugin": plugin, "on": st["on"], "state": st["state"], "peers": st["peers"]})


def forget(plugin: str) -> None:
    """The plugin unloaded."""
    leave(plugin)
    with _lock:
        _listeners.pop(plugin, None)


def reset_for_tests() -> None:
    with _lock:
        _live.clear()
        _prov.clear()
        _sent.clear()
        _listeners.clear()
        _kept.clear()


class LiveApi:
    """``api.live`` for plugin backends."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id

    def join(self, room: str = "") -> dict[str, Any]:
        return join(self.plugin_id, room)

    def leave(self) -> dict[str, Any]:
        return leave(self.plugin_id)

    def send(self, topic: str, data: Any, to: str = "") -> dict[str, Any]:
        return send(self.plugin_id, topic, data, to=to)

    def on(self, topic: str, callback: Callable[[dict[str, str], Any], Any]) -> None:
        """``callback(sender, data)`` for each ``topic`` message from a teammate."""
        if not callable(callback):
            raise TypeError("live.on needs a function: callback(sender, data)")
        with _lock:
            _listeners.setdefault(self.plugin_id, {}).setdefault(str(topic), []).append(callback)

    def state(self) -> dict[str, Any]:
        return status(self.plugin_id)
