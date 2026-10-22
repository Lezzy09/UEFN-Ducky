"""Live editing for plugins on a team copy: teammates live in the same group see each
other's pointers, what each one is pressing (held controls grey out for the others) and
short messages, straight from PC to PC. The spaces provider carries them peer to peer
(:meth:`spaces.Provider.live_send`).

Changes never travel live: they go out with sync like any other change, and the moment one
is committed this PC tells its group (``ducky.change``), whose PCs pull it at once. So a
teammate's PC only ever shows a change whole (a doc with the files it names, landed in one
transaction), never half of it.

Every plugin gets this with no plugin code: the host script in every panel page
(``ui_kit.LIVE_PRESENCE_SCRIPT``) sends the pointer, selections and holds, and draws the
group's.

Holds (a control someone is pressing) reach everyone, live or not: the group at once, and
every teammate through presence (:func:`hold` puts them in this PC's presence, and
:func:`roster_holds` hands the panels what teammates' presence says). Each hold names the
view it was pressed in (``v``), so it only greys out the same control on the same screen.
A follower (Follow on the Live list) gets the host's view, scroll and tab clicks
(``ducky.view``, ``ducky.nav``).

A group is a room named after its host's PC (``h:<device id>``): Start live hosts one,
Join goes into someone else's, both from the scope bar's Live list (:func:`groups`).
Presence carries each PC's room, so everyone works out the same groups.

Plugins may add their own short-lived messages (``live.send`` / ``api.live.send``) and
join named rooms (``api.live.join(room)``). Topics under ``ducky.`` are the host's.
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
CHANGE = "ducky.change"  # "I committed: pull now"
HOLD = "ducky.hold"  # a control this PC is pressing (on) or let go of
NAV = "ducky.nav"  # a tab the host clicked: followers click it too
FAST_TOPICS = frozenset({"ducky.pointer", "ducky.select", "ducky.view"})  # may drop: the next one replaces it
HOST_TOPICS = FAST_TOPICS | {HOLD, NAV}
HOLD_STALE_S = 30.0  # the page renews a hold every 10 s; one not renewed this long is gone
HOLDS_MAX = 4  # holds per plugin a PC puts in its presence (the sealed blob is 8 KiB at most)
LINK_GRACE_S = 10.0  # a group member with no link this long after both were live is unreachable
_ANCHOR_RE = re.compile(r"^[^\x00-\x1f]{1,400}$")
_VIEW_RE = re.compile(r"^[A-Za-z0-9._:-]{0,64}$")
_TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_ROOM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
HOST_PREFIX = "h:"


class _State:
    __slots__ = ("account", "room", "since", "space")

    def __init__(self, account: str, space: str, room: str, since: float) -> None:
        self.account, self.space, self.room, self.since = account, space, room, since


_lock = threading.Lock()
_live: dict[str, _State] = {}  # plugin -> where it is live on this PC
_holds: dict[str, dict[str, tuple[float, str, float]]] = {}  # plugin -> anchor -> (pressed at, view, renewed)
_told_holds: dict[tuple[str, str], list[dict[str, Any]]] = {}  # (space, plugin) -> teammates' holds the panels have
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


def _device() -> str:
    from backend.store.repos import space_vcs

    return space_vcs.device_id()


def host_room(device: str = "") -> str:
    """The room of the group this PC hosts (another PC's with ``device``)."""
    return HOST_PREFIX + (device or _device())


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


def spaces_live() -> set[tuple[str, str]]:
    """``(account, space)`` of every team copy a plugin is live in here (the scheduler runs
    their rounds every few seconds)."""
    with _lock:
        return {(st.account, st.space) for st in _live.values()}


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


def join(plugin: str, room: str = "") -> dict[str, Any]:
    """``plugin`` goes live in ``room``: a teammate's group (``h:<their device>``) or any
    room a plugin names; no room hosts this PC's own group. Joining another room leaves the
    one it was in. A teammate's group is joined up to date: this PC pulls first."""
    from backend.uefn_plugins import spaces

    room = str(room or host_room())
    if not _ROOM_RE.match(room):
        return {"ok": False, "error": "A room name is letters, digits, . _ : - (up to 64)."}
    ok, why = supported(plugin)
    if not ok:
        return {"ok": False, "error": why}
    account, space = _team(plugin)  # type: ignore[misc]
    with _lock:
        old = _live.get(plugin)
    if old is not None and (old.account, old.space, old.room) == (account, space, room):
        return {"ok": True, **status(plugin)}
    if old is not None:
        leave(plugin)
    with _lock:
        _live[plugin] = _State(account, space, room, time.time())
    try:
        spaces.provider().live_join(account, space, plugin, room)
    except Exception as exc:  # noqa: BLE001 — not live after all; say why
        with _lock:
            _live.pop(plugin, None)
        return {"ok": False, "error": f"Couldn't go live: {exc}"}
    _pull_now(account, space, plugin)
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
    _reload_kept(plugin)
    if st is not None:
        try:
            spaces.provider().live_leave(st.account, st.space, plugin)
        except Exception:  # noqa: BLE001 — the room lease runs out by itself
            _log.debug("live leave of %s failed", plugin, exc_info=True)
        _beat_soon(st.account, st.space)
        peers_changed(st.account, st.space, plugin)
    return {"ok": True}


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
    if topic not in HOST_TOPICS and (topic.startswith("ducky.") or not _TOPIC_RE.match(topic)):
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
    fast = bool(fast or topic in FAST_TOPICS)
    if not _rate_ok(plugin, fast):
        return {"ok": False, "error": "Too many live messages: at most 30 a second."}
    try:
        sent = spaces.provider().live_send(st.account, st.space, plugin, topic, json.loads(text),
                                           to=str(to or ""), fast=fast)
    except Exception as exc:  # noqa: BLE001 — say why instead of failing the caller
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "sent": int(sent or 0)}


def groups(plugin: str, account: str, space: str) -> list[dict[str, Any]]:
    """The live groups of ``plugin`` in the space, from its last roster: ``room``, ``host``
    (name; '' while the host is away), ``members`` (``name``, ``user``, ``device``, ``label``,
    ``me``; the first to come first) and ``mine``. This PC counts at once, before its next
    beat. Its own group first, then the biggest."""
    from backend.store.repos import space_vcs
    from backend.uefn_plugins.ledger import person
    from backend.uefn_plugins.vcs_engine import other_pc

    me = _device()
    roster = space_vcs.presence_get(account, space)["roster"]
    people = roster.get("people") if isinstance(roster, dict) else None
    rooms: dict[str, list[dict[str, Any]]] = {}
    for p in people if isinstance(people, list) else []:
        if not isinstance(p, dict) or str(p.get("device") or "") in ("", me):
            continue
        row = p.get("plugins", {}).get(plugin) if isinstance(p.get("plugins"), dict) else None
        live = row.get("live") if isinstance(row, dict) else None
        room = str(live.get("room") or "") if isinstance(live, dict) else ""
        if not room:
            continue
        try:
            since = float(live.get("since") or 0)
        except (TypeError, ValueError):
            since = 0.0
        pc = other_pc(account, space, p.get("user"), p["device"])  # this account on another PC
        rooms.setdefault(room, []).append({
            "name": f"You on {pc}" if pc else person(p.get("user_name"), p.get("user"), fallback="A teammate"),
            "user": str(p.get("user") or ""), "device": str(p["device"]), "label": str(p.get("label") or ""),
            "me": False, "since": since})
    mine = room_of(plugin, account, space)
    if mine is not None:
        rooms.setdefault(mine["room"], []).append(
            {"name": "You", "user": "", "device": me, "label": "", "me": True, "since": mine["since"]})
    out = []
    for room, members in rooms.items():
        members.sort(key=lambda m: m["since"])
        host_device = room[len(HOST_PREFIX):] if room.startswith(HOST_PREFIX) else ""
        host = next((m for m in members if m["device"] == host_device), None)
        out.append({"room": room, "host": host["name"] if host else "", "hostIsMe": bool(host and host["me"]),
                    "members": [{k: m[k] for k in ("name", "user", "device", "label", "me", "since")} for m in members],
                    "mine": mine is not None and mine["room"] == room})
    out.sort(key=lambda g: (not g["mine"], -len(g["members"]), g["host"].lower()))
    return out


def status(plugin: str) -> dict[str, Any]:
    """What the bar shows: ``supported``, ``on``, ``room``, ``state``, ``peers`` (name, user,
    device, label, path: ``direct`` | ``forwarded`` | ``none``) and ``groups``."""
    from backend.uefn_plugins import spaces

    ok, why = supported(plugin)
    st = _current(plugin)  # a plugin no longer on that team copy leaves its room here
    if st is not None and not ok:
        leave(plugin)
        st = None
    out: dict[str, Any] = {"supported": ok, "reason": why, "on": st is not None,
                           "room": st.room if st else "", "state": "off", "peers": [], "groups": []}
    team = _team(plugin) if ok else None
    if team is not None:
        try:
            out["groups"] = groups(plugin, *team)
        except Exception:  # noqa: BLE001 — no list this read
            _log.debug("live groups of %s failed", plugin, exc_info=True)
    if st is None:
        return out
    try:
        got = spaces.provider().live_state(st.account, st.space, plugin) or {}
    except Exception:  # noqa: BLE001 — live, peers unknown for now
        got = {}
    out["state"] = str(got.get("state") or "live")
    out["peers"] = [dict(p) for p in got.get("peers") or [] if isinstance(p, dict)][:32]
    out["connecting"], out["unlinked"] = _unlinked(st, out["peers"], out["groups"])
    return out


def _unlinked(st: _State, peers: list[dict[str, Any]], groups_: list[dict[str, Any]],
              now: float | None = None) -> tuple[list[str], list[str]]:
    """Who in this PC's group the provider has no link to: ``(connecting, unlinked)`` by
    name. Presence can show someone in the group while nothing reaches them; past the
    grace they are unreachable, so the bar says so instead of showing nothing."""
    now = time.time() if now is None else now
    linked = {str(p.get("device") or "") for p in peers if p.get("path") in ("direct", "forwarded")}
    mine = next((g for g in groups_ if g.get("mine")), None)
    connecting: list[str] = []
    unlinked: list[str] = []
    for m in (mine or {}).get("members") or []:
        if m.get("me") or not m.get("device") or m["device"] in linked:
            continue
        both_since = max(st.since, float(m.get("since") or 0))
        (connecting if now - both_since < LINK_GRACE_S else unlinked).append(str(m.get("name") or "A teammate"))
    return connecting, unlinked


# --------------------------------------------------------------------------- holds


def hold(plugin: str, anchor: str, on: bool, t: float = 0.0, view: str = "") -> dict[str, Any]:
    """This PC presses (``on``) or lets go of the control at ``anchor`` (the page's live script,
    pressed at ``t`` ms, in ``view``): the group hears it at once, every teammate with this
    PC's next presence. Only on a team copy."""
    anchor, view = str(anchor or ""), str(view or "")
    if not _ANCHOR_RE.match(anchor) or not _VIEW_RE.match(view):
        return {"ok": False, "error": "A hold names an anchor (up to 400 characters) and a view id."}
    if _team(plugin) is None:
        return {"ok": False, "error": "Holds are for a team copy."}
    try:
        t = float(t or 0.0)
    except (TypeError, ValueError):
        t = 0.0
    with _lock:
        mine = _holds.setdefault(plugin, {})
        if on:
            mine[anchor] = (t, view, time.time())
        else:
            mine.pop(anchor, None)
    if is_live(plugin):
        send(plugin, HOLD, {"anchor": anchor, "on": bool(on), "t": t, "v": view})
    return {"ok": True}


def holds_of(plugin: str, *, now: float | None = None) -> list[dict[str, Any]]:
    """What this PC holds in ``plugin`` (for its presence): ``a`` anchor, ``t``, ``v``."""
    now = time.time() if now is None else now
    with _lock:
        mine = _holds.get(plugin) or {}
        for anchor in [a for a, (_, _, at) in mine.items() if now - at > HOLD_STALE_S]:
            mine.pop(anchor, None)
        rows = sorted(mine.items(), key=lambda kv: kv[1][0])[:HOLDS_MAX]
    return [{"a": a, "t": t, "v": v} for a, (t, v, _) in rows]


def roster_holds(account: str, space: str, roster: Any) -> None:
    """A roster came in (a beat or heads): each plugin's panels get what teammates hold in it
    (``live_holds``: device, name, anchor, ``t``, ``v``), when that changed."""
    from backend.uefn_plugins.ledger import person

    me = _device()
    found: dict[str, list[dict[str, Any]]] = {}
    people = roster.get("people") if isinstance(roster, dict) else None
    for p in people if isinstance(people, list) else []:
        device = str(p.get("device") or "") if isinstance(p, dict) else ""
        plugins = p.get("plugins") if device and device != me else None
        for plugin, row in plugins.items() if isinstance(plugins, dict) else ():
            for h in (row.get("holds") or [])[:HOLDS_MAX] if isinstance(row, dict) else ():
                if isinstance(h, dict) and isinstance(h.get("a"), str) and _ANCHOR_RE.match(h["a"]):
                    found.setdefault(str(plugin), []).append({
                        "device": device, "name": person(p.get("user_name"), p.get("user"), fallback="A teammate"),
                        "anchor": h["a"], "t": h.get("t") or 0, "v": str(h.get("v") or "")})
    with _lock:
        told = {p: v for (s, p), v in _told_holds.items() if s == space}
        moved = [p for p in set(told) | set(found) if told.get(p, []) != found.get(p, [])]
        for plugin in moved:
            _told_holds[(space, plugin)] = found.get(plugin, [])
    for plugin in moved:
        _push({"type": "live_holds", "plugin": plugin, "holds": found.get(plugin, [])})


def holds_now(plugin: str) -> list[dict[str, Any]]:
    """What the panels were last told teammates hold in ``plugin`` (a page that just loaded)."""
    team = _team(plugin)
    with _lock:
        return list(_told_holds.get((team[1], plugin), [])) if team else []


# --------------------------------------------------------------------------- changes


def _pull_now(account: str, space: str, plugin: str) -> None:
    try:
        from backend.uefn_plugins import sync_scheduler

        sync_scheduler.wake(account, space, plugin)
    except Exception:  # noqa: BLE001 — the next round brings it
        _log.debug("live wake failed", exc_info=True)


def committed(account: str, space: str, plugin: str) -> None:
    """This PC's changes to a team copy were just committed: its live group pulls them now."""
    if room_of(plugin, account, space) is None:
        return
    try:
        from backend.uefn_plugins import spaces

        spaces.provider().live_send(account, space, plugin, CHANGE, {}, to="", fast=False)
    except Exception:  # noqa: BLE001 — their next round brings it
        _log.debug("live change note of %s failed", plugin, exc_info=True)


# --------------------------------------------------------------------------- from the provider


def deliver(account: str, space: str, plugin: str, sender: dict[str, Any], topic: str, data: Any) -> None:
    """A message from a teammate live in the same room (the provider opened and checked it)."""
    st = room_of(plugin, account, space)
    if st is None:
        return
    who = {k: str(sender.get(k) or "") for k in ("name", "user", "device", "label")}
    try:
        from backend.uefn_plugins.vcs_engine import other_pc

        pc = other_pc(account, space, who["user"], who["device"])
    except Exception:  # noqa: BLE001 — their own name then
        pc = ""
    if pc:  # this account on another PC: pointers say which PC, not the same name twice
        who["name"] = f"You on {pc}"
    if topic == CHANGE:
        _pull_now(account, space, plugin)
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
        _holds.pop(plugin, None)


def reset_for_tests() -> None:
    with _lock:
        _live.clear()
        _holds.clear()
        _told_holds.clear()
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
