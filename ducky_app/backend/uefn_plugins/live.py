"""Live editing for plugins on a team copy: teammates live in the same group see each
other's pointers, what each one is pressing (held controls grey out for the others) and
short messages, straight from PC to PC. The spaces provider carries them peer to peer
(:meth:`spaces.Provider.live_send`).

Changes go out with sync like any other change, and the moment one is committed this PC
tells its group (``ducky.change``), whose PCs pull it at once. A plugin with
``"data_live": true`` goes further: inside the group each change to its docs and files
travels at once over the link and lands as a pulled copy would (``ducky.data``, see "live
data" below), the newest change of an item wins and members never lock each other out;
sync still records every change, and teammates outside the group get it that way.

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
JOIN_RELOAD_S = 60.0  # the first pull this soon after joining a teammate's group reloads the panels
# Live data (manifest "data_live"): each change of the plugin's docs and files goes to the
# group at once over its link, and lands there as a pulled copy would (not this PC's to send).
DATA = "ducky.data"
DATA_INLINE_MAX = 36 * 1024  # bytes of a doc or file carried in the message; bigger ones are pulled
OUTBOX_EVERY_S = 0.25  # this PC's new writes are looked for this often while live
ROOM_KEY = "live_room:"  # workspace_state: where each plugin is live here (read by every process)
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
_join_reload: dict[str, float] = {}  # plugin -> until when its join's pull reloads its panels
_marks: dict[tuple[str, str, str], float] = {}  # (account, space, plugin) -> newest write sent live
_outbox: list[threading.Thread] = []


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
    teammates = room != host_room()
    with _lock:
        _live[plugin] = _State(account, space, room, time.time())
        if teammates:
            _join_reload[plugin] = time.time() + JOIN_RELOAD_S
    try:
        spaces.provider().live_join(account, space, plugin, room)
    except Exception as exc:  # noqa: BLE001 — not live after all; say why
        with _lock:
            _live.pop(plugin, None)
        return {"ok": False, "error": f"Couldn't go live: {exc}"}
    _publish_room(plugin, _live.get(plugin))
    _outbox_start()
    _pull_now(account, space, plugin)
    _beat_soon(account, space)
    peers_changed(account, space, plugin)
    return {"ok": True, **status(plugin)}


def panels_kept(plugin: str) -> None:
    """A folder plugin restarted for a teammate's pull while live, its panels kept loaded
    (``host._restart_moved``): they reload once when Live ends."""
    with _lock:
        _kept.add(plugin)


def keeps_panels(plugin: str) -> bool:
    """Whether a pull restarts ``plugin`` with its panels kept loaded (live: they merge it),
    or reloads them. The first pull after joining a teammate's group reloads them, so the
    page opens on the host's data instead of what it showed before the Join."""
    with _lock:
        if plugin not in _live:
            return False
        until = _join_reload.pop(plugin, 0.0)
    return time.time() >= until


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
        _join_reload.pop(plugin, None)
    _reload_kept(plugin)
    if st is not None:
        _publish_room(plugin, None)
        with _lock:
            _marks.pop((st.account, st.space, plugin), None)
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


def spaces_holding(*, now: float | None = None) -> set[tuple[str, str]]:
    """``(account, space)`` of every team copy this PC holds a control in now: its presence
    carries the holds, so the scheduler keeps beating there (live or not)."""
    now = time.time() if now is None else now
    with _lock:
        plugins = [p for p, mine in _holds.items() if any(now - at <= HOLD_STALE_S for _, _, at in mine.values())]
    return {team for team in map(_team, plugins) if team is not None}


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
    if topic == DATA:
        _apply_data(account, space, plugin, who, data)
        return
    _push({"type": "live_message", "plugin": plugin, "from": who, "topic": topic, "data": data})
    with _lock:
        callbacks = list(_listeners.get(plugin, {}).get(topic, ()))
    for cb in callbacks:
        try:
            cb(who, data)
        except Exception:  # noqa: BLE001 — a plugin's callback never breaks delivery
            _log.warning("%s: live callback for %s failed", plugin, topic, exc_info=True)


# --------------------------------------------------------------------------- live data
#
# A plugin with "data_live": while this PC is live in a group, every change it makes to the
# plugin's docs and files (a panel's, the person's, an agent's in the MCP bridge: they all
# land as rows here) goes to the group at once, and a teammate's lands here at once, as a
# pulled copy (not this PC's to send). Sync still records each change from the PC that made
# it; when that commit comes down it finds the same content here and nothing conflicts.
# Inside the group the newest change of an item wins and nobody locks anyone out
# (scopes._team_write); teammates outside the group get it with sync as before.


def _publish_room(plugin: str, st: _State | None) -> None:
    """Where ``plugin`` is live here, for every process (an agent's write in the MCP bridge
    takes no lock in the group either)."""
    import os

    from backend.store.repos import kv

    try:
        if st is None:
            kv.delete_doc("workspace_state", ROOM_KEY + plugin)
        else:
            kv.set_doc("workspace_state", ROOM_KEY + plugin, {"account": st.account, "space": st.space,
                                                              "room": st.room, "pid": os.getpid()})
    except Exception:  # noqa: BLE001 — the app process still knows; others lock as before
        _log.debug("publishing the live room of %s failed", plugin, exc_info=True)


def room_anywhere(plugin: str, account: str, space: str) -> str:
    """The room ``plugin`` is live in on this PC for that team copy, from any process ('' when
    not live). A room left by an app that is gone (it crashed) doesn't count."""
    here = room_of(plugin, account, space)
    if here is not None:
        return str(here["room"])
    import os

    from backend.store.repos import kv

    doc = kv.get_doc("workspace_state", ROOM_KEY + plugin)
    if not isinstance(doc, dict) or (doc.get("account"), doc.get("space")) != (account, space):
        return ""
    pid = int(doc.get("pid") or 0)
    if pid == os.getpid() or not pid:
        return ""  # this process is the app and isn't live there
    try:
        import psutil

        alive = psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        alive = False
    return str(doc.get("room") or "") if alive else ""


def group_devices(plugin: str, account: str, space: str) -> set[str] | None:
    """The other PCs live in this PC's group for ``plugin`` (from the team's last roster),
    or None when this PC isn't live there."""
    room = room_anywhere(plugin, account, space)
    if not room:
        return None
    from backend.store.repos import space_vcs

    roster = space_vcs.presence_get(account, space)["roster"]
    people = roster.get("people") if isinstance(roster, dict) else None
    me = _device()
    out: set[str] = set()
    for p in people if isinstance(people, list) else []:
        row = (p.get("plugins") or {}).get(plugin) if isinstance(p, dict) and isinstance(p.get("plugins"), dict) else None
        live = row.get("live") if isinstance(row, dict) else None
        device = str(p.get("device") or "") if isinstance(p, dict) else ""
        if device and device != me and isinstance(live, dict) and live.get("room") == room:
            out.add(device)
    return out


def _outbox_start() -> None:
    with _lock:
        if _outbox and _outbox[0].is_alive():
            return
        thread = threading.Thread(target=_outbox_loop, name="live-outbox", daemon=True)
        _outbox[:] = [thread]
    thread.start()


def _outbox_loop() -> None:
    while True:
        time.sleep(OUTBOX_EVERY_S)
        with _lock:
            if not _live:
                _outbox.clear()
                return
        try:
            send_changes()
        except Exception:  # noqa: BLE001 — the next turn tries again; sync carries it anyway
            _log.debug("sending live changes failed", exc_info=True)


def _data_item(account: str, space: str, plugin: str, r: dict[str, Any]) -> dict[str, Any] | None:
    """One written row as a live message: the doc or file itself when it is small enough,
    else just what changed (the group pulls it)."""
    import base64

    from backend.uefn_plugins import data_crypto, scopes

    item: dict[str, Any] = {"k": r["kind"], "key": r["key"], "at": float(r["updated"]), "sha": str(r["sha256"] or ""),
                            "op": "del" if int(r["deleted"]) else "put"}
    if item["op"] == "del" or r["kind"] not in ("doc", "asset"):
        return item
    try:
        if r["kind"] == "doc" and r["value"] is not None:
            raw = data_crypto.open_text(r["value"], account)
            if len(raw.encode("utf-8")) <= DATA_INLINE_MAX:
                item["v"] = raw
        elif r["kind"] == "asset" and int(r["size"] or 0) <= DATA_INLINE_MAX * 3 // 4:
            sealed = scopes.asset_file(scopes.shared_scope(account, space), plugin, r["key"]).read_bytes()
            item["b"] = base64.b64encode(data_crypto.open_bytes(sealed, account)).decode("ascii")
    except Exception:  # noqa: BLE001 — sent without its content: the group pulls it
        _log.debug("reading %s %s for the live group failed", r["kind"], r["key"], exc_info=True)
    return item


def send_changes() -> int:
    """This PC's writes since the last turn, to each live group of a ``data_live`` plugin.
    Returns how many went."""
    from backend.store.repos import plugin_data as repo
    from backend.uefn_plugins import scopes, spaces

    with _lock:
        live_now = list(_live.items())
    sent = 0
    for plugin, st in live_now:
        if not scopes.data_live(plugin):
            continue
        mark = (st.account, st.space, plugin)
        with _lock:
            since = _marks.setdefault(mark, st.since)  # what was written before joining goes with sync
        for r in repo.written_since(st.account, st.space, plugin, since):
            if not scopes.is_local_key(plugin, r["key"]):
                item = _data_item(st.account, st.space, plugin, r)
                if item is not None:
                    spaces.provider().live_send(st.account, st.space, plugin, DATA, item, to="", fast=False)
                    sent += 1
            with _lock:
                _marks[mark] = max(_marks.get(mark, 0.0), float(r["updated"]))
    return sent


def _apply_data(account: str, space: str, plugin: str, who: dict[str, str], data: Any) -> bool:
    """A groupmate's change: it lands here as a pulled copy would, unless this PC changed the
    same item later (the newest change wins; this PC's goes to them). Returns whether it
    landed."""
    import base64
    import hashlib

    from backend.store import db
    from backend.store.repos import plugin_data as repo
    from backend.store.repos import space_vcs
    from backend.uefn_plugins import data_crypto, scopes

    if not scopes.data_live(plugin) or not isinstance(data, dict):
        return False
    kind, key, op = str(data.get("k") or ""), str(data.get("key") or ""), str(data.get("op") or "")
    valid = scopes.valid_doc_key(key) if kind == "doc" else scopes.valid_asset_path(key) if kind == "asset" else False
    if not valid or op not in ("put", "del") or scopes.is_local_key(plugin, key):
        return False
    try:
        at = float(data.get("at") or 0.0)
    except (TypeError, ValueError):
        return False
    cur = repo.get(account, space, plugin, kind, key)
    if cur is not None and int(cur["sensitive"]):
        return False
    if cur is not None and int(cur["dirty"]) and (float(cur["updated"]), _device()) > (at, who.get("device", "")):
        return False  # changed here later: mine wins, and goes to them
    sha = str(data.get("sha") or "")
    if op == "put":
        if cur is not None and not int(cur["deleted"]) and cur["sha256"] == sha:
            return False
        payload = data.get("v") if kind == "doc" else data.get("b")
        if not isinstance(payload, str):
            _pull_now(account, space, plugin)  # too big to carry: sync brings it
            return False
        try:
            raw = payload.encode("utf-8") if kind == "doc" else base64.b64decode(payload, validate=True)
        except ValueError:
            return False
        if hashlib.sha256(raw).hexdigest() != sha or len(raw) > (scopes.DOC_MAX_BYTES if kind == "doc" else scopes.ASSET_MAX_BYTES):
            return False
        if kind == "doc":
            conn = db.connect()
            with db.write_txn(conn):
                repo.upsert(conn, account, space, plugin, "doc", key, value=data_crypto.seal_text(payload, account),
                            size=len(raw), sha256=sha, dirty=False)
                space_vcs.change_log_bump(conn, plugin, [key])
        else:
            scopes._write_asset(scopes.shared_scope(account, space), plugin, key, data_crypto.seal_bytes(raw, account),
                                size=len(raw), sha256=sha, dirty=False)
            conn = db.connect()
            with db.write_txn(conn):
                space_vcs.change_log_bump(conn, plugin, [key])
    else:
        if cur is None or int(cur["deleted"]):
            return False
        conn = db.connect()
        with db.write_txn(conn):
            repo.delete_row(conn, account, space, plugin, kind, key)
            space_vcs.change_log_bump(conn, plugin, [key])
        if kind == "asset":
            scopes.asset_file(scopes.shared_scope(account, space), plugin, key).unlink(missing_ok=True)
    scopes.deliver_data_changes(plugin)  # the plugin's backend hears it like a pull
    _push({"type": "plugin_scope_changed", "plugins": [plugin], "synced": True, "keys": {plugin: [key]}})
    return True


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
        _join_reload.clear()
        _marks.clear()


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
