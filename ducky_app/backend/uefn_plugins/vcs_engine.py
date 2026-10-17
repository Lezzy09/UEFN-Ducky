"""The version engine of a shared space's copy: push and pull rounds per (space, plugin)
against the provider's ledger backend (:mod:`backend.uefn_plugins.ledger`).

``plugin_data`` is this PC's working copy (``rev`` = the item's seq on the server).

Push. Dirty rows become changesets: one per closed write group (the rows one tool call
or panel call wrote; a big group goes as parts of at most :data:`MAX_ITEMS`, the last one
marked), and the plugin's other rows in changesets of at most :data:`MAX_ITEMS` each.
Each changeset is written to ``space_changesets`` before anything is uploaded, so a crash
replays the same cs_id; a row another call rewrote since stays out of it, and a file
rewritten while it was read for the upload goes again. Rows under someone else's live
lock are ``locked_out`` and stay here. The answer:

- committed or replay: per-row compare-and-set (:func:`space_vcs.mark_committed`): a row
  edited meanwhile stays dirty on the new base; a replay is checked against what the
  first try sent, so an edit made since is never taken as sent;
- conflict: pull to the head (merging or keeping both), rebuild, retry; three moves in a
  row back off 30 to 120 s;
- locked, refused: those rows wait with the reason; the rest go on;
- retry, offline, error: the round backs off (30 s, 2 min, 5 min, 15 min).

Pull. Changesets apply in seq order; a grouped one waits for its last part (24 h at
most). Content is downloaded and verified first (files to a temp file in their own
folder), then everything lands in one ``db.write_txn``, file moves included, so a writer
in any process sees all of it or none. Each item lands in its own savepoint with its file
moves journalled: one that fails rolls back alone, files too, and a transaction that
rolls back puts every file back. Per item:

- clean (or absent) here: theirs wins;
- a doc edited here: three-way JSON merge (:mod:`json_merge`) against the version mine is
  an edit of (kept here, else fetched; never merged without it); clean merges stay dirty
  and push as "Merged with Ana's change", true conflicts keep theirs and file mine in
  ``space_conflicts`` (sealed);
- a file edited here: theirs wins, mine is kept as a sealed side copy under ``conflicts/``;
- a remote delete of something edited here (or kept as mine in an unresolved conflict),
  or an edit of something deleted here: a conflict, never a silent loss;
- workflows also keep "Your copy before sync" in their History.

An item that can't be applied (a bad download, a file held open) is set aside in
``space_incoming_blocked`` and retried alone at its current version; the cursor moves on.
A pull from below what the server keeps lists every item and reconciles (resync), and so
does a plugin's first round after it moved from the provider's older sync (its rows carry
that sync's revisions). After a pull changed a plugin's data, its backend's
``api.data.on_change`` callbacks hear the keys. Nothing moves while the space is reset,
lost, unavailable or paused.

Callers hold the space's round lock (:func:`backend.uefn_plugins.sync_scheduler._round_lock`);
the functions here take it themselves when it isn't held on this thread.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import random
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from backend.store import db
from backend.store.repos import plugin_data as repo
from backend.store.repos import space_vcs
from backend.uefn_plugins import data_crypto, json_merge, scopes
from backend.uefn_plugins.ledger import (
    Behind,
    Committed,
    Conflict,
    Denied,
    Done,
    Error,
    Granted,
    Heads,
    Held,
    History,
    Importing,
    IncomingChangeset,
    IncomingItem,
    ItemId,
    LockInfo,
    LockUnit,
    Locked,
    Missing,
    Offline,
    OutgoingChangeset,
    OutgoingItem,
    Paused,
    PullPage,
    Refused,
    Replay,
    Retry,
    Roster,
    failed,
    reason_of,
    unit_of,
)

_log = logging.getLogger(__name__)

WORKFLOWS = "ducky.automations"  # owned.DOC_PLUGIN
FOLDERS_KEY = "_folders"  # owned.FOLDERS_KEY: concurrent folder adds keep both
KINDS = ("doc", "asset")  # what this engine syncs; tree items are the folder engine's
PULL_LIMIT = 50
MAX_PAGES = 20
MAX_ITEMS = 400  # per commit call; a bigger group goes as parts
CONFLICT_MOVES = 3
MOVES_BACKOFF_S = (30.0, 120.0)
GROUP_WAIT_S = 24 * 3600.0
FETCH_WORKERS = 4
LOCK_RENEW_S = 60.0
AUTO_RELEASE_S = 300.0
BEAT_EVERY_S = 60.0
BEAT_MIN_S = 10.0  # presence goes out at most this often (the server takes 6 a minute)
MODES = ("auto", "manual")
RESOLVE_CHOICES = ("mine", "theirs")
CHANGED_WHILE_SENDING = "This PC's copy changed while it was being sent; it goes again."
SYNC_PAUSED = "Team sync paused"
# Space states (the sync row) in which nothing moves: the person chooses first (a reset),
# access is gone or unsure, or the space is read-only.
HELD_STATES = {
    "reset": "This space's data was reset on the server. Choose Upload my copy or Clear my copy first.",
    "lost": "You no longer have access to this space.",
    "unavailable": "This space isn't available right now.",
    "paused": "This space is paused. Read-only.",
}


@dataclass(frozen=True)
class Ctx:
    account: str
    space: str
    plugin: str
    backend: Any

    @property
    def scope(self) -> dict[str, Any]:
        return {"account": self.account, "id": self.space, "kind": "shared"}


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Backends never raise; one that does is an error answer, never the round's crash."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        _log.warning("ledger call %s raised", getattr(fn, "__name__", fn), exc_info=True)
        return Error(f"{type(exc).__name__}: {exc}")


def _lock(account: str, space: str, wait: float) -> Any:
    from backend.uefn_plugins.sync_scheduler import _round_lock

    return _round_lock(account, space, wait)


def device_id() -> str:
    return space_vcs.device_id()


def _sha(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _asset_path(ctx: Ctx, key: str) -> Path:
    return scopes.asset_file(ctx.scope, ctx.plugin, key)


def _conflicts_dir(ctx: Ctx) -> Path:
    return scopes.plugin_dir(ctx.scope, ctx.plugin) / "conflicts"


def _unit_name(unit: str) -> str:
    return unit.split(":", 1)[1] if unit.startswith(("doc:", "asset:")) else unit


def _row_of_unit(unit: str) -> tuple[str, str] | None:
    kind, _, key = unit.partition(":")
    return (kind, key) if kind in KINDS and key else None


# --------------------------------------------------------------------------- push


def _snapshot(r: Mapping[str, Any]) -> dict[str, Any]:
    """A row as it goes out: what the compare-and-set after the commit checks."""
    return {"kind": r["kind"], "key": r["key"], "unit": unit_of(r["kind"], r["key"]),
            "op": "del" if int(r["deleted"]) else "put", "sha256": r["sha256"], "deleted": int(r["deleted"]),
            "updated": float(r["updated"])}


def _build(ctx: Ctx, *, message: str = "", now: float) -> int:
    """New changesets from rows ready to go out, written before any upload. Returns how many."""
    rows = [r for r in space_vcs.outgoing_rows(ctx.account, ctx.space, ctx.plugin, now) if r["kind"] in KINDS]
    if not rows:
        return 0
    busy = space_vcs.cs_items_open(ctx.account, ctx.space, ctx.plugin) | _waiting(ctx)
    groups = space_vcs.groups(r["group_id"] for r in rows)
    batches: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if (r["kind"], r["key"]) in busy:
            continue
        held = space_vcs.foreign_lock(ctx.account, ctx.space, ctx.plugin, unit_of(r["kind"], r["key"]), now=now)
        if held:
            repo.set_state(ctx.account, ctx.space, ctx.plugin, r["kind"], r["key"], "locked_out",
                           f"Locked by {held['holder_name'] or held['holder_user'] or 'someone'}")
            continue
        info = groups.get(r["group_id"]) if r["group_id"] else None
        if info and info["open"]:
            continue  # the call that writes this group is still running
        batches.setdefault(r["group_id"] if info else "", []).append(r)
    seq = int(space_vcs.head_get(ctx.account, ctx.space, ctx.plugin)["seq"])
    made = 0
    for gid, batch in batches.items():
        info = groups.get(gid) or {}
        parts = [batch[i:i + MAX_ITEMS] for i in range(0, len(batch), MAX_ITEMS)]
        for n, part in enumerate(parts, 1):
            # A write group's parts share its id and the final one says it is the last. Rows
            # of no group carry no promise to land together: each slice is a changeset of its
            # own, never a group made up here that a rebuild would never close.
            space_vcs.cs_add(ctx.account, ctx.space, ctx.plugin, uuid.uuid4().hex, base_seq=seq,
                             items=[_snapshot(r) for r in part], group_id=gid, part=n if gid else 1,
                             last=n == len(parts) or not gid, message=message or str(info.get("message") or ""),
                             actor=str(info.get("actor") or "user"), ducky=str(info.get("ducky") or ""))
            made += 1
    return made


def _waiting(ctx: Ctx) -> set[ItemId]:
    """Items whose newer version waits to be applied here (set aside): mine can't go out on
    top of a version this PC hasn't got, and would hold up the rows going with it."""
    return {(b["kind"], b["key"]) for b in space_vcs.blocked(ctx.account, ctx.space, ctx.plugin)}


def _outgoing(ctx: Ctx, r: Mapping[str, Any], failures: dict[ItemId, str]) -> OutgoingItem | None:
    """The row as an item to send, its content plaintext. A row that can't be read here
    backs off (and is blocked after a few tries); None then."""
    kind, key = r["kind"], r["key"]
    unit = unit_of(kind, key)
    base = int(r["rev"])
    if int(r["deleted"]):
        return OutgoingItem(kind=kind, key=key, unit=unit, op="del", base_seq=base)
    try:
        if kind == "doc":
            if r["value"] is None:
                raise ValueError("the doc has no content")
            raw = data_crypto.open_text(r["value"], ctx.account).encode("utf-8")
            return OutgoingItem(kind=kind, key=key, unit=unit, op="put", base_seq=base, sha256=_sha(raw),
                                size=len(raw), data=raw)
        path = _asset_path(ctx, key)
        if not path.is_file():
            raise FileNotFoundError("This PC's copy of the file is missing.")
    except data_crypto.Locked:
        raise
    except Exception as exc:  # noqa: BLE001 — one unreadable row never holds up the rest
        repo.note_attempt(ctx.account, ctx.space, ctx.plugin, kind, key, f"{type(exc).__name__}: {exc}")
        return None
    account = ctx.account
    sha, size = str(r["sha256"]), int(r["size"])

    def read() -> bytes:
        # The backend reads when it uploads, maybe more than once and minutes later: a file
        # rewritten meanwhile would go out under the sha256 and size of the row as it was.
        try:
            raw = data_crypto.open_bytes(path.read_bytes(), account)
        except Exception as exc:  # noqa: BLE001 — recorded against the row, re-raised to the backend
            failures[(kind, key)] = f"{type(exc).__name__}: {exc}"
            raise
        if len(raw) != size or _sha(raw) != sha:
            failures[(kind, key)] = CHANGED_WHILE_SENDING
            raise ValueError(CHANGED_WHILE_SENDING)
        return raw

    return OutgoingItem(kind=kind, key=key, unit=unit, op="put", base_seq=base, sha256=sha, size=size, reader=read)


@dataclass
class _Out:
    kind: str  # committed | dropped | conflict | locked | refused | missing | stop
    seq: int = 0
    state: str = ""
    error: str = ""


def _push_cs(ctx: Ctx, cs: dict[str, Any], *, now: float) -> _Out:
    first_try = cs["state"] == "pending"
    items: list[OutgoingItem] = []
    sent: list[dict[str, Any]] = []
    bases: dict[str, tuple[str, str]] = {}
    failures: dict[ItemId, str] = {}
    waiting = _waiting(ctx)
    going: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for snap in cs["items"]:
        r = space_vcs.row(None, ctx.account, ctx.space, ctx.plugin, str(snap.get("kind")), str(snap.get("key")))
        if (not r or not int(r["dirty"]) or int(r["sensitive"]) or r["sync_state"] in space_vcs.HELD_STATES
                or float(r["next_try"]) > now):
            continue  # settled meanwhile (pulled, dropped, held): it no longer goes with this changeset
        if (r["kind"], r["key"]) in waiting or (r["group_id"] and r["group_id"] != cs["group_id"]):
            # A newer version of it waits to be applied here, or another call (or a merge)
            # rewrote it since this changeset was made: it goes later, with that call's
            # changeset once the call returned, never half of that call in this one.
            later.append(r)
            continue
        going.append(r)
    if not going and not first_try:
        going = later  # sent before: the server's answer (a commit whose reply got lost) is still needed
    for r in going:
        item = _outgoing(ctx, r, failures)
        if item is None:
            continue
        items.append(item)
        sent.append(_snapshot(r))
        if r["kind"] == "doc" and not int(r["deleted"]):
            bases[r["key"]] = (str(r["sha256"]), r["value"])
    if not items:
        space_vcs.cs_delete(ctx.account, ctx.space, cs["cs_id"])
        return _Out("dropped")
    # Written before the upload. Once a try went out, what it sent stays the record: a
    # replay is checked against it, so an edit made after it is never taken as sent.
    if first_try:
        space_vcs.cs_set(ctx.account, ctx.space, cs["cs_id"], state="pushing", items=sent)
    first = sent if first_try else cs["items"]
    units = sorted({i.unit for i in items})
    fences = {lk["unit"]: int(lk["fence"]) for lk in space_vcs.locks(ctx.account, ctx.space, ctx.plugin, now=now)
              if lk["mine"] and lk["unit"] in units}
    head = space_vcs.head_get(ctx.account, ctx.space, ctx.plugin)
    out = OutgoingChangeset(cs_id=cs["cs_id"], base_seq=int(head["seq"]), items=tuple(items), device=device_id(),
                            group=cs["group_id"], part=int(cs["part"]), last=bool(cs["last"]), message=cs["message"],
                            actor=cs["actor"], ducky=cs["ducky"], fences=fences)
    res = _call(ctx.backend.push, ctx.space, ctx.plugin, out)
    if failures and not isinstance(res, (Committed, Replay)):
        went = {(str(s_["kind"]), str(s_["key"])): s_ for s_ in sent}
        for (kind, key), err in failures.items():
            if err == CHANGED_WHILE_SENDING and _rewritten(ctx, went.get((kind, key))):
                continue  # written again while it was sent: it goes again with what it is now
            repo.note_attempt(ctx.account, ctx.space, ctx.plugin, kind, key, err)
        return _Out("dropped")  # the changeset goes again without the rows that couldn't be read
    if isinstance(res, (Committed, Replay)):
        snaps = sent if isinstance(res, Committed) else first
        if isinstance(res, Replay):  # an earlier try committed: its content is known only where nothing changed
            sent_sha = {str(s["key"]): str(s["sha256"]) for s in first if s["kind"] == "doc"}
            bases = {k: v for k, v in bases.items() if sent_sha.get(k) == v[0]}
        space_vcs.mark_committed(ctx.account, ctx.space, ctx.plugin, res.seq, snaps, bases=bases, units=units)
        space_vcs.cs_set(ctx.account, ctx.space, cs["cs_id"], state="committed", seq=res.seq)
        space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, moves=0)
        return _Out("committed", seq=res.seq)
    if isinstance(res, Conflict):
        _gone_for_good(ctx, res)
        space_vcs.cs_delete(ctx.account, ctx.space, cs["cs_id"])
        return _Out("conflict")
    if isinstance(res, Locked):
        space_vcs.cs_delete(ctx.account, ctx.space, cs["cs_id"])
        for lk in res.units:
            _cache_lock(ctx, lk, now)
            row = _row_of_unit(lk.unit)
            if row:
                repo.set_state(ctx.account, ctx.space, ctx.plugin, *row, "locked_out",
                               f"Locked by {lk.user_name or lk.user or 'someone'}")
        return _Out("locked")
    if isinstance(res, Refused):
        space_vcs.cs_delete(ctx.account, ctx.space, cs["cs_id"])
        for it in res.items:
            repo.set_state(ctx.account, ctx.space, ctx.plugin, it.kind, it.key, "refused", it.reason)
        return _Out("refused")
    if isinstance(res, Missing):
        return _Out("missing", error=reason_of(res))
    return _stop(ctx, res, now=now)


def _rewritten(ctx: Ctx, snap: Mapping[str, Any] | None) -> bool:
    """The row is no longer what went out (a newer write landed since)."""
    if snap is None:
        return False
    r = space_vcs.row(None, ctx.account, ctx.space, ctx.plugin, str(snap["kind"]), str(snap["key"]))
    return r is None or r["sha256"] != snap["sha256"] or float(r["updated"]) != float(snap["updated"])


def _gone_for_good(ctx: Ctx, conflict: Conflict) -> None:
    """Items the server no longer has at all (purged): an edit here is an edit against a
    delete (Restore mine makes it again); a delete here is simply settled."""
    purged = [c for c in conflict.items if c.deleted and not c.seq]
    if not purged:
        return
    conn = db.connect()
    with db.write_txn(conn):
        for c in purged:
            cur = space_vcs.row(conn, ctx.account, ctx.space, ctx.plugin, c.kind, c.key)
            if cur is None or not int(cur["dirty"]):
                continue
            if int(cur["deleted"]):
                space_vcs.delete_row(conn, ctx.account, ctx.space, ctx.plugin, c.kind, c.key)
                continue
            space_vcs.conflict_put(conn, ctx.account, ctx.space, ctx.plugin, c.kind, c.key,
                                   unit=unit_of(c.kind, c.key), reason="deleted", mine_value=cur["value"],
                                   mine_sha=cur["sha256"], mine_size=int(cur["size"]), base_seq=int(cur["rev"]),
                                   theirs_by=c.by, theirs_at=c.at, theirs_deleted=True)
            space_vcs.set_row_state(conn, ctx.account, ctx.space, ctx.plugin, c.kind, c.key, "conflict",
                                    "This was deleted for good; you changed it.", rev=0)
            space_vcs.base_delete(conn, ctx.account, ctx.space, ctx.plugin, c.key)


def _stop(ctx: Ctx, res: Any, *, now: float) -> _Out:
    """A round can't go on: record why and when to try again."""
    reason = reason_of(res)
    if isinstance(res, Retry):
        space_vcs.backoff(ctx.account, ctx.space, ctx.plugin, "retry", reason, after=res.after, now=now)
        return _Out("stop", state="retry", error=reason)
    if isinstance(res, Importing):
        space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, state="importing", error=reason)
        return _Out("stop", state="importing", error=reason)
    if isinstance(res, Paused):
        space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, state="paused", error="")
        return _Out("stop", state="paused", error="")
    state = "offline" if isinstance(res, Offline) else "error"
    space_vcs.backoff(ctx.account, ctx.space, ctx.plugin, state, reason, now=now)
    return _Out("stop", state=state, error=reason)


def _push_round(ctx: Ctx, *, message: str = "", now: float, pull: bool = True) -> dict[str, Any]:
    """Send what is ready. ``pull`` False (the exit flush): a conflict ends the round instead
    of pulling, so nothing is applied while the app is closing; the rows go next time."""
    pushed = 0
    missing: dict[str, int] = {}
    for _ in range(50):
        _build(ctx, message=message, now=now)
        pending = space_vcs.cs_open(ctx.account, ctx.space, ctx.plugin)
        if not pending:
            break
        again = False
        for cs in pending:
            out = _push_cs(ctx, cs, now=now)
            if out.kind == "committed":
                pushed += 1
                continue
            if out.kind in ("dropped", "locked", "refused"):
                again = True
                continue
            if out.kind == "missing":
                missing[cs["cs_id"]] = missing.get(cs["cs_id"], 0) + 1
                if missing[cs["cs_id"]] > 1:
                    stop = _stop(ctx, Error(out.error), now=now)
                    return {"state": stop.state, "error": stop.error, "pushed": pushed}
                again = True  # the backend sends what went missing on the next try
                break
            if out.kind == "conflict":
                if not pull:
                    return {"state": "ok", "error": "", "pushed": pushed}
                moves = int(space_vcs.head_get(ctx.account, ctx.space, ctx.plugin)["moves"]) + 1
                space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, moves=moves)
                if moves >= CONFLICT_MOVES:
                    space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, moves=0)
                    space_vcs.backoff(ctx.account, ctx.space, ctx.plugin, "ok", "",
                                      after=random.uniform(*MOVES_BACKOFF_S), now=now)
                    return {"state": "retry", "error": "Others keep changing this; trying again soon.",
                            "pushed": pushed}
                pulled = _pull_round(ctx, now=now)
                if pulled["state"] != "ok":
                    return {**pulled, "pushed": pushed}
                again = True
                break
            return {"state": out.state, "error": out.error, "pushed": pushed}
        if not again:
            break
    return {"state": "ok", "error": "", "pushed": pushed}


# --------------------------------------------------------------------------- pull


def _groups_open(buffer: list[IncomingChangeset], now: float) -> bool:
    """A group in ``buffer`` still waits for its last part (24 h at most)."""
    started: dict[str, float] = {}
    done: set[str] = set()
    for cs in buffer:
        if not cs.group:
            continue
        started.setdefault(cs.group, cs.at or now)
        if cs.last:
            done.add(cs.group)
    return any(g not in done and now - at < GROUP_WAIT_S for g, at in started.items())


def _download(ctx: Ctx, items: list[IncomingItem]) -> dict[ItemId, Any]:
    """Each put's content (4 at a time). An item that already carries it is used as is."""
    out: dict[ItemId, Any] = {it.id: it for it in items if it.data is not None or it.path}
    todo = [it for it in items if it.id not in out]
    if not todo:
        return out

    def one(it: IncomingItem) -> tuple[ItemId, Any]:
        return it.id, _call(ctx.backend.fetch, ctx.space, ctx.plugin, it.kind, it.key, it.seq or None)

    if len(todo) == 1:
        vid, res = one(todo[0])
        out[vid] = res
        return out
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="space-fetch") as pool:
        for vid, res in pool.map(one, todo):
            out[vid] = res
    return out


def _drop_temp(got: Any) -> None:
    path = getattr(got, "path", "")
    if path:
        Path(path).unlink(missing_ok=True)


@dataclass
class _Prep:
    """An incoming put made ready before the transaction: a doc parsed and sealed, a file
    sealed into a temp file next to its target. ``error``: why it can't be applied."""

    sha256: str = ""
    size: int = 0
    raw: bytes = b""
    sealed: str | None = None
    temp: Path | None = None
    target: Path | None = None
    error: str = ""


def _prepare(ctx: Ctx, it: IncomingItem, got: Any) -> _Prep:
    if failed(got) or not isinstance(got, IncomingItem):
        return _Prep(error=reason_of(got) or "The download failed.")
    if got.op == "del":
        return _Prep()
    try:
        raw = got.read()
        sha = _sha(raw)
        want = got.sha256 or it.sha256
        if want and want != sha:
            return _Prep(error="The download didn't match what was sent.")
        if it.kind == "doc":
            json.loads(raw)
            return _Prep(sha256=sha, size=len(raw), raw=raw, sealed=data_crypto.seal_text(raw.decode("utf-8"),
                                                                                         ctx.account))
        target = _asset_path(ctx, it.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        temp.write_bytes(data_crypto.seal_bytes(raw, ctx.account))
        return _Prep(sha256=sha, size=len(raw), temp=temp, target=target)
    except data_crypto.Locked:
        raise
    except Exception as exc:  # noqa: BLE001 — set aside, retried alone
        return _Prep(error=f"{type(exc).__name__}: {exc}")
    finally:
        _drop_temp(got)


def _has_conflict(conn: Any, ctx: Ctx, kind: str, key: str) -> bool:
    return space_vcs.conflict_get(ctx.account, ctx.space, ctx.plugin, kind, key, conn=conn) is not None


def _holds_mine(c: Mapping[str, Any] | None) -> bool:
    """A conflict that keeps a version of mine (not a delete of mine)."""
    return bool(c) and not int(c["mine_deleted"]) and (c["mine_value"] is not None or bool(c["mine_path"]))


def _why(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "The file is open in another program here; it is tried again soon."
    return f"{type(exc).__name__}: {exc}"


class _Files:
    """File moves made inside a transaction, so a rollback puts the files back too. A move
    marked ``keep`` stays once the transaction commits; any other one was a file moved out
    of the way, removed then."""

    def __init__(self) -> None:
        self.moves: list[tuple[Path, Path, bool]] = []  # (from, to, keep)

    def move(self, src: Path, dst: Path, *, keep: bool) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        self.moves.append((src, dst, keep))

    def aside(self, path: Path) -> None:
        """``path`` out of the way of what replaces it (a file held open raises here, before
        anything changed)."""
        if path.exists():
            self.move(path, path.with_name(f"{path.name}.{uuid.uuid4().hex}.old"), keep=False)

    def undo(self, mark: int = 0) -> None:
        """Every move since ``mark`` back, newest first."""
        while len(self.moves) > mark:
            src, dst, _ = self.moves.pop()
            try:
                os.replace(dst, src)
            except OSError:
                _log.warning("putting back %s failed", src, exc_info=True)

    def committed(self) -> None:
        for _, dst, keep in self.moves:
            if not keep:
                dst.unlink(missing_ok=True)
        self.moves = []


class _Apply:
    """One transaction's worth of incoming items. Each item lands in its own savepoint, its
    file moves journalled: an item that can't be applied (a file held open, a copy that
    won't open) rolls back alone, files included, and is set aside to be retried; a
    transaction that rolls back as a whole puts every file back. ``merge`` False: a doc
    edited here is never merged (a conflict unless both are the same). ``bases``: merge
    bases fetched for this apply, ``{(key, seq): plaintext}``."""

    def __init__(self, ctx: Ctx, conn: Any, *, force: bool, merge: bool = True,
                 bases: Mapping[tuple[str, int], bytes] | None = None) -> None:
        self.ctx, self.conn, self.force, self.merge = ctx, conn, force, merge
        self.bases = dict(bases or {})
        self.files = _Files()
        self.changed: list[str] = []
        self.blocked: set[str] = set()
        self.cleanup: list[Path] = []  # side copies replaced by a newer one: removed after the commit
        self.conflicts = 0
        self.merges = 0
        self._merge_groups: dict[str, str] = {}

    def _merge_group(self, by: str) -> str:
        gid = self._merge_groups.get(by)
        if gid is None:
            gid = self._merge_groups[by] = f"merge-{uuid.uuid4().hex}"
            space_vcs.group_add_closed(self.conn, gid, self.ctx.plugin,
                                       message=f"Merged with {by}'s change" if by else "Merged with a change")
        return gid

    def one(self, it: IncomingItem, seq: int, by: str, at: float, prep: _Prep | None, *,
            action: Callable[[], None] | None = None) -> None:
        """:meth:`item` (or ``action``) in a savepoint. A failure rolls back just this item and
        sets it aside; a missing data key (``Locked``) stops the whole apply."""
        mark = (len(self.files.moves), len(self.changed), len(self.cleanup), self.conflicts, self.merges,
                dict(self._merge_groups))
        self.conn.execute("SAVEPOINT apply_item")
        try:
            (action or (lambda: self.item(it, seq, by, at, prep)))()
        except Exception as exc:
            self.conn.execute("ROLLBACK TO apply_item")
            self.conn.execute("RELEASE apply_item")
            self.files.undo(mark[0])
            del self.changed[mark[1]:]
            del self.cleanup[mark[2]:]
            self.conflicts, self.merges, self._merge_groups = mark[3], mark[4], mark[5]
            if isinstance(exc, data_crypto.Locked):
                raise
            _log.warning("%s %s couldn't be applied; set aside", it.kind, it.key, exc_info=True)
            unit = it.unit or unit_of(it.kind, it.key)
            space_vcs.blocked_put(self.conn, self.ctx.account, self.ctx.space, self.ctx.plugin, it.kind, it.key,
                                  unit=unit, seq=seq, error=_why(exc))
            self.blocked.add(unit)
            return
        self.conn.execute("RELEASE apply_item")

    def item(self, it: IncomingItem, seq: int, by: str, at: float, prep: _Prep | None) -> None:
        ctx, conn = self.ctx, self.conn
        a = (ctx.account, ctx.space, ctx.plugin, it.kind, it.key)
        cur = space_vcs.row(conn, *a)
        if cur is not None and int(cur["sensitive"]):
            return
        dirty = bool(cur and int(cur["dirty"]))
        if cur is not None and int(cur["rev"]) >= seq and (dirty or not self.force):
            space_vcs.blocked_delete(conn, *a)
            return  # this version or a newer one is already the base here
        if it.op == "del":
            self._delete(it, seq, by, at, cur)
            return
        if prep is None or prep.error:
            space_vcs.blocked_put(conn, *a, unit=it.unit or unit_of(it.kind, it.key), seq=seq,
                                  error=(prep.error if prep else "") or "The download failed.")
            self.blocked.add(it.unit or unit_of(it.kind, it.key))
            return
        space_vcs.blocked_delete(conn, *a)
        old = space_vcs.conflict_get(*a, conn=conn)
        if old is not None and old["reason"] == "deleted":
            space_vcs.conflict_delete(conn, *a)  # they made it again: the delete it was about is over
        if cur is None or not dirty or (not int(cur["deleted"]) and cur["sha256"] == prep.sha256):
            self._theirs(it, seq, prep, keep_conflict=cur is not None and _has_conflict(conn, ctx, it.kind, it.key))
            return
        if int(cur["deleted"]):
            # Deleted here, changed there: theirs is applied, the delete waits for the person.
            self._theirs(it, seq, prep, keep_conflict=True, error=f"{by or 'Someone'} changed this; you deleted it.")
            space_vcs.conflict_put(conn, *a, unit=unit_of(it.kind, it.key), reason="mine_deleted", mine_deleted=True,
                                   base_seq=int(cur["rev"]), theirs_seq=seq, theirs_by=by, theirs_at=at)
            self.conflicts += 1
            return
        if it.kind == "doc":
            self._merge_doc(it, seq, by, at, cur, prep)
        else:
            self._keep_both_files(it, seq, by, at, cur, prep)

    def _theirs(self, it: IncomingItem, seq: int, prep: _Prep, *, keep_conflict: bool, error: str = "") -> None:
        ctx, conn = self.ctx, self.conn
        state = "conflict" if keep_conflict else ""
        if it.kind == "doc":
            space_vcs.apply_row(conn, ctx.account, ctx.space, ctx.plugin, "doc", it.key, value=prep.sealed,
                                size=prep.size, sha256=prep.sha256, rev=seq, dirty=False, state=state, error=error)
            space_vcs.base_put(conn, ctx.account, ctx.space, ctx.plugin, it.key, seq, prep.sha256, prep.sealed)
        else:
            space_vcs.apply_row(conn, ctx.account, ctx.space, ctx.plugin, "asset", it.key, value=None,
                                size=prep.size, sha256=prep.sha256, rev=seq, dirty=False, state=state, error=error)
            # Last, inside the transaction: the row and the file land together, and a file
            # held open fails here, before anything of this item changed.
            self.files.aside(prep.target)
            self.files.move(prep.temp, prep.target, keep=True)
        self.changed.append(it.key)

    def _delete(self, it: IncomingItem, seq: int, by: str, at: float, cur: dict[str, Any] | None) -> None:
        ctx, conn = self.ctx, self.conn
        a = (ctx.account, ctx.space, ctx.plugin, it.kind, it.key)
        space_vcs.blocked_delete(conn, *a)
        if cur is None:
            space_vcs.base_delete(conn, ctx.account, ctx.space, ctx.plugin, it.key)
            return
        if int(cur["dirty"]) and not int(cur["deleted"]):
            # Deleted there, changed here: mine stays (out of pushes) until the person picks.
            space_vcs.conflict_put(conn, *a, unit=unit_of(it.kind, it.key), reason="deleted",
                                   mine_value=cur["value"], mine_sha=cur["sha256"], mine_size=int(cur["size"]),
                                   base_seq=int(cur["rev"]), theirs_seq=seq, theirs_by=by, theirs_at=at,
                                   theirs_deleted=True)
            space_vcs.set_row_state(conn, *a, "conflict", f"{by or 'Someone'} deleted this; you changed it.", rev=seq)
            space_vcs.base_delete(conn, ctx.account, ctx.space, ctx.plugin, it.key)
            self.conflicts += 1
            return
        old = space_vcs.conflict_get(*a, conn=conn)
        if not int(cur["dirty"]) and _holds_mine(old) and self._mine_back(it, seq, by, at, old):
            return
        space_vcs.delete_row(conn, *a)
        space_vcs.conflict_delete(conn, *a)
        space_vcs.base_delete(conn, ctx.account, ctx.space, ctx.plugin, it.key)
        if it.kind == "asset":
            self.files.aside(_asset_path(ctx, it.key))
        self.changed.append(it.key)

    def _mine_back(self, it: IncomingItem, seq: int, by: str, at: float, c: Mapping[str, Any]) -> bool:
        """Deleted there while an unresolved conflict still keeps my version (the row holds
        theirs): mine becomes the row again, an edit against the delete, so the delete never
        takes it with it. False when mine's side copy is gone (nothing left to keep)."""
        ctx, conn = self.ctx, self.conn
        a = (ctx.account, ctx.space, ctx.plugin, it.kind, it.key)
        error = f"{by or 'Someone'} deleted this; you changed it."
        mine_value = c["mine_value"] if it.kind == "doc" else None
        if it.kind == "asset" and not Path(c["mine_path"]).is_file():
            return False
        space_vcs.apply_row(conn, *a, value=mine_value, size=int(c["mine_size"]), sha256=str(c["mine_sha"]), rev=seq,
                            dirty=True, state="conflict", error=error)
        space_vcs.conflict_put(conn, *a, unit=unit_of(it.kind, it.key), reason="deleted", mine_value=mine_value,
                               mine_sha=str(c["mine_sha"]), mine_size=int(c["mine_size"]), base_seq=int(c["base_seq"]),
                               theirs_seq=seq, theirs_by=by, theirs_at=at, theirs_deleted=True)
        space_vcs.base_delete(conn, ctx.account, ctx.space, ctx.plugin, it.key)
        if it.kind == "asset":
            target = _asset_path(ctx, it.key)
            self.files.aside(target)
            self.files.move(Path(c["mine_path"]), target, keep=True)
        self.changed.append(it.key)
        return True

    def _merge_doc(self, it: IncomingItem, seq: int, by: str, at: float, cur: dict[str, Any], prep: _Prep) -> None:
        ctx, conn = self.ctx, self.conn
        a = (ctx.account, ctx.space, ctx.plugin, "doc", it.key)
        rev = int(cur["rev"])
        mine = json.loads(data_crypto.open_text(cur["value"], ctx.account))
        theirs = json.loads(prep.raw)
        # The base is the version mine is an edit of: kept here, or fetched for this apply.
        # rev 0: both sides made the doc (the base is "no doc"). A base that is no longer
        # known never merges: keys only one side holds would be taken as additions, and a
        # teammate's delete would come back.
        base: Any = json_merge.MISSING
        known = self.merge and rev == 0
        base_row = space_vcs.base_get(ctx.account, ctx.space, ctx.plugin, it.key, conn=conn)
        if self.merge and base_row and int(base_row["seq"]) == rev and base_row["value"] is not None:
            base, known = json.loads(data_crypto.open_text(base_row["value"], ctx.account)), True
        elif self.merge and (it.key, rev) in self.bases:
            base, known = json.loads(self.bases[(it.key, rev)]), True
        if known:
            result = json_merge.merge(base, theirs, mine, set_arrays=ctx.plugin == WORKFLOWS and it.key == FOLDERS_KEY)
        else:
            result = json_merge.MergeResult(theirs, [] if json_merge.same(theirs, mine) else ["$"])
        if result.clean:
            raw = scopes.encode_doc(result.value)
            sha = _sha(raw)
            if sha == prep.sha256:
                self._theirs(it, seq, prep, keep_conflict=_has_conflict(conn, ctx, "doc", it.key))
                return
            sealed = data_crypto.seal_text(raw.decode("utf-8"), ctx.account)
            space_vcs.apply_row(conn, *a, value=sealed, size=len(raw), sha256=sha, rev=seq, dirty=True,
                                group_id=self._merge_group(by))
            space_vcs.base_put(conn, ctx.account, ctx.space, ctx.plugin, it.key, seq, prep.sha256, prep.sealed)
            self.changed.append(it.key)
            self.merges += 1
            return
        if ctx.plugin == WORKFLOWS:
            from backend.automations import owned

            owned.archive_before_adopt(ctx.scope, it.key)  # "Your copy before sync" in its History
        space_vcs.conflict_put(conn, *a, unit=unit_of("doc", it.key), reason="changed", mine_value=cur["value"],
                               mine_sha=cur["sha256"], mine_size=int(cur["size"]), base_seq=rev,
                               theirs_seq=seq, theirs_by=by, theirs_at=at)
        self._theirs(it, seq, prep, keep_conflict=True, error=f"{by or 'Someone'} changed this too.")
        self.conflicts += 1

    def _keep_both_files(self, it: IncomingItem, seq: int, by: str, at: float, cur: dict[str, Any],
                         prep: _Prep) -> None:
        """Files are never merged: theirs is applied, mine is kept as a sealed side copy."""
        ctx, conn = self.ctx, self.conn
        a = (ctx.account, ctx.space, ctx.plugin, "asset", it.key)
        old = space_vcs.conflict_get(*a, conn=conn)
        mine_path = ""
        side = _conflicts_dir(ctx) / f"{uuid.uuid4().hex}.bin"
        src = _asset_path(ctx, it.key)
        if src.is_file():
            self.files.move(src, side, keep=True)  # mine, sealed as it is; put back if this rolls back
            mine_path = str(side)
        if old is not None and old["mine_path"] and old["mine_path"] != mine_path:
            self.cleanup.append(Path(old["mine_path"]))
        space_vcs.conflict_put(conn, *a, unit=unit_of("asset", it.key), reason="changed", mine_path=mine_path,
                               mine_sha=cur["sha256"], mine_size=int(cur["size"]), base_seq=int(cur["rev"]),
                               theirs_seq=seq, theirs_by=by, theirs_at=at)
        self._theirs(it, seq, prep, keep_conflict=True, error=f"{by or 'Someone'} changed this file too.")
        self.conflicts += 1

    def undo(self) -> None:
        self.files.undo()

    def committed(self) -> None:
        self.files.committed()
        for path in self.cleanup:
            path.unlink(missing_ok=True)


def _fetch_bases(ctx: Ctx, wanted: Iterable[tuple[str, int]]) -> dict[tuple[str, int], bytes]:
    """Merge bases this PC doesn't keep (a doc edited here whose base was never stored, or
    went with a replay): each version mine is an edit of, fetched. One that can't be fetched
    is left out (the doc then doesn't merge)."""
    out: dict[tuple[str, int], bytes] = {}
    for key, seq in dict.fromkeys(wanted):
        got = _call(ctx.backend.fetch, ctx.space, ctx.plugin, "doc", key, seq)
        try:
            if isinstance(got, IncomingItem) and got.op == "put":
                raw = got.read()
                if (not got.sha256 or got.sha256 == _sha(raw)) and isinstance(json.loads(raw), (dict, list)):
                    out[(key, seq)] = raw
        except Exception:  # noqa: BLE001 — no base: no merge
            _log.debug("base %s@%s of %s couldn't be read", key, seq, ctx.plugin, exc_info=True)
        finally:
            _drop_temp(got)
    return out


def _apply(ctx: Ctx, changesets: list[IncomingChangeset], *, force: bool = False) -> dict[str, Any]:
    """Download, then apply ``changesets`` in one transaction (the head moves to the last
    one's seq). ``force``: a clean row takes theirs even at the same or a newer rev (a
    resync). Returns ``{state, changed, conflicts, merges, blocked, blocked_units}``."""
    latest: dict[ItemId, tuple[IncomingItem, int, str, float]] = {}
    units: dict[str, int] = {}
    for cs in changesets:
        for it in cs.items:
            if it.kind not in KINDS:
                continue
            seq = int(it.seq or cs.seq)
            latest[it.id] = (it, seq, it.by or cs.by, float(it.at or cs.at))
            unit = it.unit or unit_of(it.kind, it.key)
            units[unit] = max(units.get(unit, 0), seq)
    work = []
    wanted: list[tuple[str, int]] = []
    for it, seq, by, at in latest.values():
        cur = space_vcs.row(None, ctx.account, ctx.space, ctx.plugin, it.kind, it.key)
        if cur is not None and int(cur["rev"]) >= seq and (int(cur["dirty"]) or not force):
            continue
        work.append((it, seq, by, at))
        if (it.kind == "doc" and it.op == "put" and cur is not None and int(cur["dirty"]) and not int(cur["deleted"])
                and int(cur["rev"]) > 0):
            b = space_vcs.base_get(ctx.account, ctx.space, ctx.plugin, it.key)
            if not b or int(b["seq"]) != int(cur["rev"]) or b["value"] is None:
                wanted.append((it.key, int(cur["rev"])))
    fetched = _download(ctx, [it for it, *_ in work if it.op == "put"])
    if any(isinstance(got, Offline) for got in fetched.values()):
        for got in fetched.values():
            _drop_temp(got)
        return {"state": "offline", "error": reason_of(next(g for g in fetched.values() if isinstance(g, Offline)))}
    preps: dict[ItemId, _Prep] = {}
    try:
        for it, *_ in work:
            if it.op == "put":
                preps[it.id] = _prepare(ctx, it, fetched.get(it.id))
        bases = _fetch_bases(ctx, wanted) if wanted else {}
        last = max((cs.seq for cs in changesets), default=0)
        conn = db.connect()
        run = _Apply(ctx, conn, force=force, bases=bases)
        try:
            with db.write_txn(conn):
                for it, seq, by, at in work:
                    run.one(it, seq, by, at, preps.get(it.id))
                for unit, seq in units.items():
                    if unit not in run.blocked:
                        space_vcs.unit_seen(conn, ctx.account, ctx.space, ctx.plugin, unit, seq)
                if last:
                    space_vcs.head_advance(conn, ctx.account, ctx.space, ctx.plugin, last)
                if run.changed:
                    space_vcs.change_log_bump(conn, ctx.plugin, run.changed)
        except BaseException:
            run.undo()  # the transaction rolled back: so do the files
            raise
        run.committed()
    finally:
        for prep in preps.values():
            if prep.temp is not None:
                prep.temp.unlink(missing_ok=True)  # gone already once it landed
    return {"state": "ok", "changed": run.changed, "conflicts": run.conflicts, "merges": run.merges,
            "blocked": len(run.blocked), "blocked_units": set(run.blocked)}


def _settle_in_flight(ctx: Ctx, *, now: float) -> _Out | None:
    """Changesets already sent once are answered before anything is pulled: one the server
    committed (its answer lost) would otherwise come back in the pull looking like someone
    else's change to the same rows. Returns why the round must stop, or None."""
    for cs in space_vcs.cs_open(ctx.account, ctx.space, ctx.plugin):
        if cs["state"] != "pushing":
            continue
        out = _push_cs(ctx, cs, now=now)
        if out.kind == "missing":
            again = space_vcs.cs_get(ctx.account, ctx.space, cs["cs_id"])
            out = _push_cs(ctx, again, now=now) if again else _Out("dropped")
            if out.kind == "missing":
                return _stop(ctx, Error(out.error), now=now)
        if out.kind == "stop":
            return out
    return None


def _deliver(ctx: Ctx, keys: list[str]) -> None:
    """The plugin's ``api.data.on_change`` callbacks in this process hear what pulls changed:
    this one's keys, and those of any pull in another process (the MCP bridge) since they
    last heard (the plugin's change log has both)."""
    if keys:
        scopes.deliver_data_changes(ctx.plugin)


def _pull_round(ctx: Ctx, *, now: float) -> dict[str, Any]:
    """Pull to the head. Whatever it changed, even when it stops part way, is told to the
    plugin once at the end."""
    changed: list[str] = []
    try:
        return _pull_pages(ctx, changed, now=now)
    finally:
        _deliver(ctx, changed)


def _pull_pages(ctx: Ctx, changed: list[str], *, now: float) -> dict[str, Any]:
    settled = _settle_in_flight(ctx, now=now)
    if settled is not None:
        return {"state": settled.state, "error": settled.error, "changed": [], "pulled": 0, "conflicts": 0}
    head = space_vcs.head_get(ctx.account, ctx.space, ctx.plugin)
    cursor = int(head["seq"])
    buffer: list[IncomingChangeset] = []
    conflicts = 0
    pulled = 0
    for _ in range(MAX_PAGES):
        page = _call(ctx.backend.pull, ctx.space, ctx.plugin, cursor, PULL_LIMIT)
        if not isinstance(page, PullPage):
            out = _stop(ctx, page, now=now)
            return {"state": out.state, "error": out.error, "changed": changed, "pulled": pulled,
                    "conflicts": conflicts}
        if page.resync:
            return _resync(ctx, page.head, changed, now=now)
        space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, remote_seq=page.head)
        for cs in page.changesets:
            buffer.append(cs)
            cursor = max(cursor, cs.seq)
            if _groups_open(buffer, now):
                continue
            out = _apply(ctx, buffer)
            if out["state"] != "ok":
                stop = _stop(ctx, Offline(out.get("error", "")), now=now)
                return {"state": stop.state, "error": stop.error, "changed": changed, "pulled": pulled,
                        "conflicts": conflicts}
            changed += out["changed"]
            conflicts += out["conflicts"]
            pulled += len(buffer)
            buffer = []
        if not page.more:
            break
    blocked = _retry_blocked(ctx, now=now)
    changed += blocked["changed"]
    return {"state": blocked["state"], "error": blocked.get("error", ""), "changed": changed, "pulled": pulled,
            "conflicts": conflicts + blocked["conflicts"]}


def _retry_blocked(ctx: Ctx, *, now: float) -> dict[str, Any]:
    """Items set aside whose wait is over, each alone at its current version."""
    changed: list[str] = []
    conflicts = 0
    for b in space_vcs.blocked(ctx.account, ctx.space, ctx.plugin, due=now):
        got = _call(ctx.backend.fetch, ctx.space, ctx.plugin, b["kind"], b["key"], None)
        if isinstance(got, Offline):
            return {"state": "ok", "changed": changed, "conflicts": conflicts}  # the next round tries again
        if not isinstance(got, IncomingItem):
            conn = db.connect()
            with db.write_txn(conn):
                space_vcs.blocked_put(conn, ctx.account, ctx.space, ctx.plugin, b["kind"], b["key"], unit=b["unit"],
                                      seq=int(b["seq"]), error=reason_of(got), now=now)
            continue
        out = _apply(ctx, [IncomingChangeset(seq=0, items=(got,))], force=True)
        changed += out.get("changed", [])
        conflicts += int(out.get("conflicts", 0))
    return {"state": "ok", "changed": changed, "conflicts": conflicts}


def _listing(ctx: Ctx, *, now: float) -> tuple[dict[ItemId, IncomingItem], int] | dict[str, Any]:
    """Every item's current version on the server (``pull(full=True)``, paged) and the head;
    or why the round stops."""
    listing: dict[ItemId, IncomingItem] = {}
    after = ""
    head = 0
    while True:
        page = _call(ctx.backend.pull, ctx.space, ctx.plugin, 0, PULL_LIMIT, full=True, after=after)
        if not isinstance(page, PullPage):
            out = _stop(ctx, page, now=now)
            return {"state": out.state, "error": out.error, "changed": [], "pulled": 0, "conflicts": 0}
        head = max(head, int(page.head))
        for it in page.items:
            if it.kind in KINDS:
                listing[it.id] = it
        if not page.more or not page.after or page.after == after:
            return listing, head
        after = page.after


def _resync(ctx: Ctx, head_seq: int, changed: list[str], *, now: float) -> dict[str, Any]:
    """The cursor is older than what the server keeps: list every item and reconcile each
    by seq (missing here: applied; extra here and clean: removed; edited here: the usual
    merge and conflict rules)."""
    got = _listing(ctx, now=now)
    if isinstance(got, dict):
        return got
    listing, _ = got
    local = {(r["kind"], r["key"]): r for r in space_vcs.plugin_rows(ctx.account, ctx.space, ctx.plugin)
             if r["kind"] in KINDS}
    todo: list[IncomingItem] = []
    for vid, it in listing.items():
        cur = local.get(vid)
        if it.deleted:
            if cur is not None:
                todo.append(it)
            continue
        if (cur is not None and not int(cur["dirty"]) and not int(cur["deleted"]) and int(cur["rev"]) == it.seq
                and (not it.sha256 or it.sha256 == cur["sha256"])):
            continue
        todo.append(it)
    conflicts = 0
    blocked: set[str] = set()
    for i in range(0, len(todo), PULL_LIMIT):
        out = _apply(ctx, [IncomingChangeset(seq=0, items=tuple(todo[i:i + PULL_LIMIT]))], force=True)
        if out["state"] != "ok":
            stop = _stop(ctx, Offline(out.get("error", "")), now=now)
            return {"state": stop.state, "error": stop.error, "changed": changed, "pulled": 0, "conflicts": conflicts}
        changed += out["changed"]
        conflicts += out["conflicts"]
        blocked |= out["blocked_units"]
    extras = [r for vid, r in local.items() if vid not in listing and not int(r["dirty"]) and not int(r["sensitive"])]
    conn = db.connect()
    run = _Apply(ctx, conn, force=True)
    try:
        with db.write_txn(conn):
            for r in extras:
                cur = space_vcs.row(conn, ctx.account, ctx.space, ctx.plugin, r["kind"], r["key"])
                if (cur is None or int(cur["dirty"]) or cur["sha256"] != r["sha256"]
                        or float(cur["updated"]) != float(r["updated"])):
                    continue  # written since the listing: it stays, and its push settles it
                gone = IncomingItem(kind=r["kind"], key=r["key"], op="del")
                run.one(gone, 0, "", now, None, action=lambda gone=gone, cur=cur: run._delete(gone, 0, "", now, cur))
            blocked |= {b["unit"] for b in space_vcs.blocked(ctx.account, ctx.space, ctx.plugin)}
            for it in listing.values():  # every unit applied here is as the server has it (what lock requests say)
                unit = it.unit or unit_of(it.kind, it.key)
                if unit not in blocked:
                    space_vcs.unit_seen(conn, ctx.account, ctx.space, ctx.plugin, unit, it.seq)
            space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, conn=conn, remote_seq=head_seq)
            space_vcs.head_reset(ctx.account, ctx.space, ctx.plugin, head_seq, conn=conn)
            if run.changed:
                space_vcs.change_log_bump(conn, ctx.plugin, run.changed)
    except BaseException:
        run.undo()
        raise
    run.committed()
    changed += run.changed
    return {"state": "ok", "error": "", "changed": changed, "pulled": len(todo), "conflicts": conflicts,
            "resync": True}


def _v1rev(it: IncomingItem) -> int | None:
    try:
        v = it.meta.get("v1rev")
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _keeps(cur: Mapping[str, Any] | None, it: IncomingItem) -> bool:
    """On the move from the older sync, this PC's row stays as it is (at the item's seq):
    clean with the item's content, or an edit made on top of the revision it was imported at."""
    if cur is None or it.deleted:
        return False
    if not int(cur["dirty"]):
        return not int(cur["deleted"]) and bool(it.sha256) and it.sha256 == cur["sha256"]
    v1rev = _v1rev(it)
    return v1rev is not None and int(cur["rev"]) == v1rev


def _reconcile_v1(ctx: Ctx, *, now: float) -> dict[str, Any]:
    """The plugin's first round on the new sync. Its rows still carry the older sync's
    revisions, which mean nothing to the new one, so they are matched once against a full
    listing (an imported item says the older revision it came from, ``meta["v1rev"]``):

    - clean here with the item's content, or edited here on top of the revision it was
      imported at: kept as it is, now at the item's seq (an edit goes out as usual);
    - clean here and different, or not here: the team's version comes down;
    - edited here on top of anything else: a conflict (theirs current, mine kept);
    - here and not on the server: removed when clean, an edit against a delete when it
      was edited on top of a revision, sent as new when it was made here.

    All in one transaction; only then is the plugin on the new sync (engine ``v2``) with
    the server's head. A copy with nothing from the older sync (no rows, or only changes
    made here and never sent) needs none of it: it pulls from the start like any."""
    if not any(int(r["rev"]) > 0 or not int(r["dirty"])
               for r in space_vcs.plugin_rows(ctx.account, ctx.space, ctx.plugin)
               if r["kind"] in KINDS and not int(r["sensitive"])):
        space_vcs.head_put(ctx.account, ctx.space, ctx.plugin, engine="v2")
        return {"state": "ok", "error": "", "changed": [], "pulled": 0, "conflicts": 0}
    got = _listing(ctx, now=now)
    if isinstance(got, dict):
        return got
    listing, head_seq = got
    local = {(r["kind"], r["key"]): r for r in space_vcs.plugin_rows(ctx.account, ctx.space, ctx.plugin)
             if r["kind"] in KINDS}
    need = [it for vid, it in listing.items() if not it.deleted and not _keeps(local.get(vid), it)]
    fetched = _download(ctx, need)
    if any(isinstance(g, Offline) for g in fetched.values()):
        for g in fetched.values():
            _drop_temp(g)
        out = _stop(ctx, next(g for g in fetched.values() if isinstance(g, Offline)), now=now)
        return {"state": out.state, "error": out.error, "changed": [], "pulled": 0, "conflicts": 0}
    preps: dict[ItemId, _Prep] = {}
    a = (ctx.account, ctx.space, ctx.plugin)
    try:
        for it in need:
            preps[it.id] = _prepare(ctx, it, fetched.get(it.id))
        conn = db.connect()
        run = _Apply(ctx, conn, force=True, merge=False)
        try:
            with db.write_txn(conn):
                rows = {(r["kind"], r["key"]): r for r in space_vcs.plugin_rows(*a) if r["kind"] in KINDS}
                for vid, it in listing.items():
                    cur = rows.get(vid)
                    if cur is not None and int(cur["sensitive"]):
                        continue
                    if _keeps(cur, it):
                        conn.execute("UPDATE plugin_data SET rev=? WHERE account_id=? AND scope_id=? AND plugin_id=? "
                                     "AND kind=? AND key=?", (int(it.seq), *a, *vid))
                        if it.kind == "doc" and not int(cur["dirty"]):
                            space_vcs.base_put(conn, *a, it.key, int(it.seq), cur["sha256"], cur["value"])
                        continue
                    if cur is not None:  # a revision of the older sync is no base here
                        conn.execute("UPDATE plugin_data SET rev=0 WHERE account_id=? AND scope_id=? AND plugin_id=? "
                                     "AND kind=? AND key=?", (*a, *vid))
                    prep = preps.get(it.id)
                    if not it.deleted and prep is None:  # changed here during the listing: fetched alone
                        space_vcs.blocked_put(conn, *a, it.kind, it.key, unit=it.unit or unit_of(*vid), seq=it.seq,
                                              error="Changed here while moving to the new sync.", now=0.0)
                        run.blocked.add(it.unit or unit_of(*vid))
                        continue
                    run.one(it, int(it.seq), it.by, it.at, prep)
                for vid, cur in rows.items():
                    if vid in listing or int(cur["sensitive"]) or (int(cur["dirty"]) and not int(cur["deleted"])
                                                                   and not int(cur["rev"])):
                        continue  # on the server, never shared, or made here: it goes out as new
                    gone = IncomingItem(kind=vid[0], key=vid[1], op="del")
                    run.one(gone, 0, "", now, None, action=lambda gone=gone, cur=cur: run._delete(gone, 0, "", now, cur))
                for it in listing.values():
                    unit = it.unit or unit_of(it.kind, it.key)
                    if unit not in run.blocked:
                        space_vcs.unit_seen(conn, *a, unit, int(it.seq))
                space_vcs.head_reset(*a, head_seq, conn=conn)
                space_vcs.head_put(*a, conn=conn, engine="v2", remote_seq=head_seq)
                if run.changed:
                    space_vcs.change_log_bump(conn, ctx.plugin, run.changed)
        except BaseException:
            run.undo()
            raise
        run.committed()
    finally:
        for prep in preps.values():
            if prep.temp is not None:
                prep.temp.unlink(missing_ok=True)
    return {"state": "ok", "error": "", "changed": run.changed, "pulled": len(need), "conflicts": run.conflicts}


# --------------------------------------------------------------------------- rounds


def held_reason(account: str, space: str) -> str:
    """Why nothing may move in the space now (reset, lost, unavailable, paused), or ''."""
    st = repo.sync_get(account, space)
    why = HELD_STATES.get(str(st["state"] or ""))
    if why is None:
        return ""
    return str(st["error"] or why) if st["state"] == "unavailable" else why


def run(account: str, space: str, plugin: str, backend: Any, *, push: bool | None = None, pull: bool | None = None,
        force: bool = False, message: str = "", now: float | None = None) -> dict[str, Any]:
    """One round for (space, plugin): pull, then push. In Manual mode nothing moves unless
    asked (``push=True`` / ``pull=True``, with an optional ``message`` for the push). A
    round backing off is skipped unless ``force``; nothing moves while the space is held
    (:func:`held_reason`). The plugin's first round on the new sync reconciles this PC's
    copy first (:func:`_reconcile_v1`). Returns ``{state, changed, error, pushed, pulled,
    conflicts}`` (``changed``: ``[plugin]`` when a pull changed its data); ``busy`` when
    another round holds the space. A round that raises is this plugin's error (it backs
    off), never the space's other plugins'."""
    now = time.time() if now is None else now
    ctx = Ctx(account, space, plugin, backend)
    head = space_vcs.head_get(account, space, plugin)
    manual = head["mode"] == "manual"
    do_pull = (not manual) if pull is None else bool(pull)
    do_push = (not manual) if push is None else bool(push)
    out: dict[str, Any] = {"state": "ok", "changed": [], "error": "", "pushed": 0, "pulled": 0, "conflicts": 0}
    held_by = held_reason(account, space)
    if held_by:
        return {**out, "state": repo.sync_get(account, space)["state"], "error": held_by}
    if not force and float(head["next_try"]) > now:
        return {**out, "state": head["state"], "error": head["error"], "skipped": True}
    with _lock(account, space, 600.0 if force else 0.0) as held:
        if not held:
            return {**out, "state": "busy"}
        repo.sync_put(account, space, called_at=now)
        try:
            if space_vcs.head_get(account, space, plugin)["engine"] != "v2":
                if pull is False:  # a push-only round (the exit flush): the move waits for a full one
                    return {**out, "skipped": True}
                got = _reconcile_v1(ctx, now=now)
                _deliver(ctx, got.get("changed") or [])
                out.update(state=got["state"], error=got.get("error", ""), pulled=got.get("pulled", 0),
                           conflicts=got.get("conflicts", 0), changed=[plugin] if got.get("changed") else [])
            if do_pull and out["state"] == "ok":
                got = _pull_round(ctx, now=now)
                out.update(state=got["state"], error=got.get("error", ""), pulled=out["pulled"] + got.get("pulled", 0),
                           conflicts=out["conflicts"] + got.get("conflicts", 0),
                           changed=[plugin] if got.get("changed") or out["changed"] else [])
            if do_push and out["state"] == "ok":
                sent = _push_round(ctx, message=message, now=now, pull=pull is not False)
                out.update(state=sent["state"], error=sent.get("error", ""), pushed=sent.get("pushed", 0))
        except data_crypto.Locked as exc:
            return {**out, "state": "locked", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — this plugin's round failed; the others go on
            return {**out, **_round_raised(ctx, exc, now=now)}
    if out["state"] == "ok":
        space_vcs.head_ok(account, space, plugin, now=now)
        repo.sync_put(account, space, synced_at=now)
    return out


def _round_raised(ctx: Ctx, exc: Exception, *, now: float) -> dict[str, Any]:
    """A round of one plugin raised: it backs off with the error shown, and the provider
    plugin's errors get it with the traceback."""
    import traceback

    msg = f"Sync failed: {type(exc).__name__}: {exc}"
    _log.warning("sync of %s in %s failed", ctx.plugin, ctx.space, exc_info=True)
    stop = _stop(ctx, Error(msg[:500]), now=now)
    try:
        from backend.tools.panel.panel_plugin_check import record
        from backend.uefn_plugins.spaces import provider_plugin

        record("plugin_sync_error", provider_plugin(), msg, stack=traceback.format_exc()[-4000:])
    except Exception:  # noqa: BLE001 — reporting never raises from a round
        _log.debug("recording the sync failure failed", exc_info=True)
    return {"state": stop.state, "error": stop.error}


def set_mode(account: str, space: str, plugin: str, mode: str) -> dict[str, Any]:
    """Auto (rounds push and pull by themselves) or Manual (only Push and Pull do)."""
    if mode not in MODES:
        raise ValueError("Choose Auto or Manual.")
    space_vcs.head_put(account, space, plugin, mode=mode)
    return {"ok": True, "mode": mode}


def refresh(account: str, space: str, plugins: list[str], backend: Any, *, now: float | None = None) -> dict[str, Any]:
    """``heads``: each plugin's head (what is incoming), imports, live locks, the roster. A new
    epoch puts the space in ``reset`` (read-only until the person chooses). The new sync
    switched off on the server (``v2`` false) pauses these plugins (read-only, "Team sync
    paused") and only them: plugins still on the older sync go on."""
    now = time.time() if now is None else now
    asked_at = time.time()
    got = _call(backend.heads, space, list(plugins))
    if not isinstance(got, Heads):
        if isinstance(got, Paused):
            repo.sync_put(account, space, state="paused")
        return {"state": "paused" if isinstance(got, Paused) else "offline" if isinstance(got, Offline) else "error",
                "error": reason_of(got)}
    if not got.v2:
        for plugin in plugins:
            space_vcs.head_put(account, space, plugin, state="paused", error=SYNC_PAUSED)
        return {"state": "paused", "error": SYNC_PAUSED}
    known = {h["epoch"] for h in space_vcs.heads(account, space).values() if h["epoch"]}
    reset = bool(known) and got.epoch not in known
    if reset:
        space_vcs.reset_epoch(account, space, got.epoch)
        repo.sync_put(account, space, state="reset", error="This space's data was reset on the server.")
    elif repo.sync_get(account, space)["state"] == "paused":
        repo.sync_put(account, space, state="ok")
    incoming: dict[str, int] = {}
    for plugin in plugins:
        remote = int(got.heads.get(plugin, 0))
        head = space_vcs.head_get(account, space, plugin)
        fields: dict[str, Any] = {"remote_seq": remote, "epoch": got.epoch}
        if plugin in got.importing:
            fields.update(state="importing", error=f"Moving to the new sync ({int(got.importing[plugin])}%)")
        elif head["state"] in ("paused", "importing"):
            fields.update(state="ok", error="")  # back on (its next round says otherwise if not)
        space_vcs.head_put(account, space, plugin, **fields)
        incoming[plugin] = max(0, remote - int(head["seq"]))
    _locks_from(account, space, got.locks, now=now, asked_at=asked_at)
    space_vcs.presence_put(account, space, {"people": [dict(p) for p in got.people], "usage": dict(got.usage)},
                           now=now)
    return {"state": "reset" if reset else "ok", "error": "", "incoming": incoming, "epoch": got.epoch,
            "importing": dict(got.importing)}


# --------------------------------------------------------------------------- locks


def _cache_lock(ctx: Ctx, lk: LockInfo, now: float, reason: str = "") -> None:
    space_vcs.lock_put(ctx.account, ctx.space, lk.plugin or ctx.plugin, lk.unit, name=lk.name, holder_user=lk.user,
                       holder_name=lk.user_name, holder_device=lk.device, since=lk.since, lease_left=lk.lease_left,
                       fence=lk.fence, mine=lk.mine, reason=reason or lk.reason, now=now)


def _locks_from(account: str, space: str, live: Iterable[LockInfo], *, now: float,
                asked_at: float | None = None) -> dict[str, Any]:
    """The server's live locks replace the cache. Rows locked out by a lock that went are
    queued again; unsent edits under a lock of mine someone broke or took over become a
    conflict (kept, never pushed over theirs without the person), and the person is told
    about every lock of theirs that went."""
    rows = [asdict(lk) for lk in live]
    change = space_vcs.locks_replace(account, space, rows, now=now, asked_at=asked_at)
    for lk in change["freed"]:
        row = _row_of_unit(lk["unit"])
        if row:
            r = space_vcs.row(None, account, space, lk["plugin_id"], *row)
            if r and r["sync_state"] == "locked_out":
                repo.set_state(account, space, lk["plugin_id"], *row, "")
    for lk in change["lost"]:
        row = _row_of_unit(lk["unit"])
        r = space_vcs.row(None, account, space, lk["plugin_id"], *row) if row else None
        kept = bool(r and int(r["dirty"]))
        _tell_lock_lost(lk, kept=kept)
        if not kept:
            continue
        holder = lk.get("now_holder") or "someone"
        conn = db.connect()
        with db.write_txn(conn):
            space_vcs.conflict_put(conn, account, space, lk["plugin_id"], r["kind"], r["key"], unit=lk["unit"],
                                   reason="lock_broken", mine_value=r["value"], mine_sha=r["sha256"],
                                   mine_size=int(r["size"]), mine_deleted=bool(int(r["deleted"])),
                                   base_seq=int(r["rev"]), theirs_seq=int(r["rev"]), theirs_by=holder, theirs_at=now)
            space_vcs.set_row_state(conn, account, space, lk["plugin_id"], r["kind"], r["key"], "conflict",
                                    f"Your lock was taken by {holder}; your unsent change is kept.")
    return change


def _tell_lock_lost(lk: Mapping[str, Any], *, kept: bool) -> None:
    """A lock of mine went: someone broke it or took it over, or its lease ran out. An alert
    (a Windows notification when no Ducky window is in front) and the app hears it (its
    activity list, the plugin's bar)."""
    plugin, unit = str(lk["plugin_id"]), str(lk["unit"])
    name = str(lk.get("name") or _unit_name(unit))
    holder = str(lk.get("now_holder") or "")
    detail = f"{holder} took {name}" if holder else f"Your lock on {name} ended"
    detail += "; your unsent change is kept as a conflict." if kept else "."
    try:
        from backend.uefn_plugins.spaces import plugin_label
        from frontend.notifications import alert

        alert(plugin_label(plugin) or plugin, "Your lock was broken." if holder else "Your lock ended.",
              level="error", detail=detail)
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "plugin_lock_lost", "plugin_id": plugin, "unit": unit, "unit_name": name,
                       "holder": holder, "kept": kept, "detail": detail})
        push_ui_event({"type": "plugin_scope_changed", "plugins": [plugin]})
    except Exception:  # noqa: BLE001 — the bar's lock list says it on its next read
        _log.debug("telling about a lost lock failed", exc_info=True)


def _lock_answer(unit: str, res: Any) -> dict[str, Any]:
    if isinstance(res, (Granted, Held)):
        return {"unit": unit, "ok": True, "state": "granted" if isinstance(res, Granted) else "held",
                "fence": res.fence, "leaseLeft": res.lease_left}
    if isinstance(res, Behind):
        return {"unit": unit, "ok": False, "state": "behind", "seq": res.seq, "by": res.by,
                "error": f"{res.by or 'Someone'} changed this after your copy. Sync first."}
    if isinstance(res, LockInfo):
        who = res.user_name or res.user or "someone"
        return {"unit": unit, "ok": False, "state": "locked", "holder": who, "since": res.since,
                "leaseLeft": res.lease_left, "error": f"Locked by {who}"}
    return {"unit": unit, "ok": False, "state": "error", "error": "No answer for this unit."}


def acquire(account: str, space: str, plugin: str, backend: Any, units: list[tuple[str, str]], *,
            reason: str = "manual", mode: str = "best", now: float | None = None) -> dict[str, dict[str, Any]]:
    """Lock ``units`` (``(unit, name)``) for this PC. Each says the seq of its last change
    applied here; a unit this PC is behind on is pulled and asked for once more (not while
    the space is held: :func:`held_reason`). ``reason``: ``auto`` (released 5 minutes after
    its last change went out), ``manual`` (kept until released), or '' to keep the reason
    each lock of mine already has (a renewal). Returns ``{unit: {ok, state, ...}}``."""
    now = time.time() if now is None else now
    ctx = Ctx(account, space, plugin, backend)
    asked = [LockUnit(u, n) for u, n in units]
    res = _call(backend.lock, space, plugin, asked, mode, space_vcs.unit_seqs(account, space, plugin,
                                                                               [u for u, _ in units]))
    if not isinstance(res, dict):
        return {u: {"unit": u, "ok": False, "state": "error", "error": reason_of(res)} for u, _ in units}
    behind = [lu for lu in asked if isinstance(res.get(lu.unit), Behind)]
    if behind and not held_reason(account, space):
        with _lock(account, space, 30.0) as held:
            if held:
                _pull_round(ctx, now=now)
        again = _call(backend.lock, space, plugin, behind, mode,
                      space_vcs.unit_seqs(account, space, plugin, [lu.unit for lu in behind]))
        if isinstance(again, dict):
            res.update(again)
    out: dict[str, dict[str, Any]] = {}
    held_since = {lk["unit"]: float(lk["since"]) for lk in space_vcs.locks(account, space, plugin, now=now, live=False)
                  if lk["mine"]}
    for lu in asked:
        r = res.get(lu.unit)
        if isinstance(r, (Granted, Held)):
            since = held_since.get(lu.unit) or now if isinstance(r, Held) else now  # a renew keeps "since"
            space_vcs.lock_put(account, space, plugin, lu.unit, name=lu.name, holder_device=device_id(),
                               since=since, lease_left=r.lease_left, fence=r.fence, mine=True, reason=reason, now=now)
        elif isinstance(r, LockInfo):
            _cache_lock(ctx, r, now)
        out[lu.unit] = _lock_answer(lu.unit, r)
    return out


def renew_due(account: str, space: str, plugin: str, *, active: bool, now: float | None = None) -> list[str]:
    """Locks of mine to renew now: every 60 s while the plugin is active or the unit has
    changes not sent yet."""
    now = time.time() if now is None else now
    out = []
    for lk in space_vcs.locks(account, space, plugin, now=now):
        if not lk["mine"] or now - float(lk["renewed"]) < LOCK_RENEW_S:
            continue
        if active or _unit_unsent(account, space, plugin, lk["unit"]):
            out.append(lk["unit"])
    return out


def renew(account: str, space: str, plugin: str, backend: Any, units: list[str], *,
          now: float | None = None) -> dict[str, dict[str, Any]]:
    """Renew locks of mine: one lock call for all of them (the server takes 30 a minute),
    each keeping its reason."""
    if not units:
        return {}
    names = {lk["unit"]: lk["name"] for lk in space_vcs.locks(account, space, plugin, now=now, live=False)}
    return acquire(account, space, plugin, backend, [(unit, names.get(unit, "")) for unit in units], reason="",
                   now=now)


def _unit_unsent(account: str, space: str, plugin: str, unit: str) -> bool:
    row = _row_of_unit(unit)
    if row is None:
        return False
    r = space_vcs.row(None, account, space, plugin, *row)
    return bool(r and int(r["dirty"]))


def idle_auto_locks(account: str, space: str, plugin: str, *, now: float | None = None) -> list[str]:
    """Auto locks of mine whose unit's last change went out 5 minutes ago (nothing unsent)."""
    now = time.time() if now is None else now
    return [lk["unit"] for lk in space_vcs.locks(account, space, plugin, now=now, live=False)
            if lk["mine"] and lk["reason"] == "auto" and now - float(lk["touched"]) >= AUTO_RELEASE_S
            and not _unit_unsent(account, space, plugin, lk["unit"])]


def release(account: str, space: str, plugin: str, backend: Any, units: list[str]) -> dict[str, Any]:
    """Release locks of mine (the cache forgets them even when the server can't be reached:
    the lease runs out there within 5 minutes)."""
    got = _call(backend.unlock, space, plugin, list(units))
    space_vcs.lock_delete(account, space, plugin, units)
    return {"ok": isinstance(got, Done), "error": "" if isinstance(got, Done) else reason_of(got)}


def release_idle(account: str, space: str, plugin: str, backend: Any, *, now: float | None = None) -> list[str]:
    units = idle_auto_locks(account, space, plugin, now=now)
    if units:
        release(account, space, plugin, backend, units)
    return units


def release_all(account: str, space: str, backend_for: Callable[[str], Any]) -> int:
    """Every lock of mine in the space (exit, a scope switch): best effort."""
    mine: dict[str, list[str]] = {}
    for lk in space_vcs.locks(account, space, live=False):
        if lk["mine"]:
            mine.setdefault(lk["plugin_id"], []).append(lk["unit"])
    for plugin, units in mine.items():
        backend = backend_for(plugin)
        if backend is not None:
            release(account, space, plugin, backend, units)
        else:
            space_vcs.lock_delete(account, space, plugin, units)
    return sum(len(u) for u in mine.values())


def break_lock(account: str, space: str, plugin: str, backend: Any, unit: str) -> dict[str, Any]:
    got = _call(backend.break_lock, space, plugin, unit)
    if isinstance(got, Done):
        space_vcs.lock_delete(account, space, plugin, [unit])
        return {"ok": True}
    return {"ok": False, "error": got.reason if isinstance(got, Denied) else reason_of(got)}


def ask(account: str, space: str, plugin: str, backend: Any, unit: str) -> dict[str, Any]:
    got = _call(backend.ask, space, plugin, unit)
    return {"ok": isinstance(got, Done), "error": "" if isinstance(got, Done) else reason_of(got)}


def serve_lock_requests(account: str, backend_for: Callable[[str, str], Any], *,
                        now: float | None = None) -> int:
    """Answer writers waiting for a lock (``required`` prefixes). Returns how many."""
    served = 0
    for req in space_vcs.lock_requests_pending(account):
        backend = backend_for(req["space_id"], req["plugin_id"])
        if backend is None:
            space_vcs.lock_request_answer(account, req["space_id"], req["plugin_id"], req["unit"], "refused",
                                          "Not connected: this space can't take locks right now.")
            continue
        got = acquire(account, req["space_id"], req["plugin_id"], backend, [(req["unit"], req["name"])],
                      reason="auto", now=now)[req["unit"]]
        space_vcs.lock_request_answer(account, req["space_id"], req["plugin_id"], req["unit"],
                                      "granted" if got["ok"] else "refused", got.get("error", ""))
        served += 1
    return served


# --------------------------------------------------------------------------- presence


def device_label() -> str:
    return (platform.node() or "This PC")[:64]


def presence_blob(account: str, space: str, plugins: Iterable[str], *, now: float | None = None) -> dict[str, Any]:
    """What this PC says in the space: per plugin whether its panel is on screen, the units
    changed in the last 2 minutes (by the person or a ducky) and the locks held here."""
    from backend.uefn_plugins.panel_presence import panel_state

    acts = space_vcs.activity(account, space, now=now)
    mine = [lk for lk in space_vcs.locks(account, space, now=now) if lk["mine"]]
    names = {(lk["plugin_id"], lk["unit"]): lk["name"] for lk in mine}
    out: dict[str, Any] = {}
    for plugin in sorted(set(plugins) | {a["plugin_id"] for a in acts} | {lk["plugin_id"] for lk in mine}):
        try:
            viewing = bool(panel_state(plugin)["visible"])
        except Exception:  # noqa: BLE001 — presence never fails a beat
            viewing = False
        out[plugin] = {
            "viewing": viewing,
            "editing": [{"unitName": names.get((plugin, a["unit"])) or _unit_name(a["unit"]), "actor": a["actor"],
                         "ducky": a["ducky"], "since": float(a["since"])}
                        for a in acts if a["plugin_id"] == plugin],
            "locks": sorted(lk["name"] or _unit_name(lk["unit"]) for lk in mine if lk["plugin_id"] == plugin),
        }
    # "label", never "device": a roster row's "device" is the device id the server adds.
    return {"label": device_label(), "app": "open", "plugins": out}


def beat(account: str, space: str, backend: Any, plugins: Iterable[str], *, force: bool = False,
         now: float | None = None) -> dict[str, Any]:
    """Send presence when it changed, or every 60 s to keep it alive, and never more than one
    beat every 10 s (a failed one counts): the server takes 6 a minute. The roster and the
    live locks it answers with are kept. ``skipped`` when nothing was due."""
    import hashlib

    now = time.time() if now is None else now
    blob = presence_blob(account, space, plugins, now=now)
    sha = hashlib.sha256(json.dumps(blob, sort_keys=True).encode("utf-8")).hexdigest()
    last = space_vcs.presence_get(account, space)
    if not force and (now - last["sent_at"] < BEAT_MIN_S
                      or (sha == last["sent_sha"] and now - last["sent_at"] < BEAT_EVERY_S)):
        return {"ok": True, "skipped": True}
    asked_at = time.time()
    got = _call(backend.beat, space, blob)
    if not isinstance(got, Roster):
        # A failed beat counts as one: the next waits its 10 s, and goes again once due.
        space_vcs.presence_put(account, space, sent_sha=last["sent_sha"], now=now)
        return {"ok": False, "error": reason_of(got)}
    roster = dict(last["roster"]) if isinstance(last["roster"], dict) else {}
    roster["people"] = [dict(p) for p in got.people]
    space_vcs.presence_put(account, space, roster, sent_sha=sha, now=now)
    _locks_from(account, space, got.locks, now=now, asked_at=asked_at)
    return {"ok": True, "people": len(got.people)}


# --------------------------------------------------------------------------- conflicts, restore, history


def resolve(account: str, space: str, plugin: str, kind: str, key: str, choice: str,
            backend: Any = None) -> dict[str, Any]:
    """Settle one conflict. ``mine``: keep this PC's version (Keep mine, Restore mine, or
    delete again); ``theirs``: keep the team's (Keep theirs, Accept delete). Either way
    the other version stops being kept here."""
    if choice not in RESOLVE_CHOICES:
        raise ValueError("Choose mine or theirs.")
    c = space_vcs.conflict_get(account, space, plugin, kind, key)
    if c is None:
        return {"ok": False, "error": "There is no conflict here any more."}
    ctx = Ctx(account, space, plugin, backend)
    reason = c["reason"]
    if reason == "lock_broken" and choice == "theirs":
        return _discard_mine(ctx, kind, key)
    target = _asset_path(ctx, key) if kind == "asset" else None
    conn = db.connect()
    a = (account, space, plugin, kind, key)
    with db.write_txn(conn):
        cur = space_vcs.row(conn, *a)
        if cur is None and choice == "mine" and _holds_mine(c):
            # The row went meanwhile: mine is made again from the conflict's copy (sent as new).
            if kind == "doc":
                space_vcs.apply_row(conn, *a, value=c["mine_value"], size=int(c["mine_size"]), sha256=c["mine_sha"],
                                    rev=0, dirty=True)
            elif c["mine_path"] and Path(c["mine_path"]).is_file():
                space_vcs.apply_row(conn, *a, value=None, size=int(c["mine_size"]), sha256=c["mine_sha"], rev=0,
                                    dirty=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(c["mine_path"], target)
        elif reason == "deleted":
            if choice == "mine" and cur is not None:
                space_vcs.set_row_state(conn, *a, "", dirty=True)  # made again on top of the delete
            elif cur is not None:
                space_vcs.delete_row(conn, *a)
                if target is not None:
                    target.unlink(missing_ok=True)
        elif reason == "mine_deleted" or (reason == "lock_broken" and int(c["mine_deleted"])):
            if choice == "mine" and cur is not None:
                space_vcs.make_tombstone(conn, *a)
                if target is not None:
                    target.unlink(missing_ok=True)
            elif cur is not None:
                space_vcs.set_row_state(conn, *a, "")
        elif choice == "mine" and cur is not None:
            if kind == "doc":
                space_vcs.apply_row(conn, *a, value=c["mine_value"], size=int(c["mine_size"]), sha256=c["mine_sha"],
                                    rev=int(cur["rev"]), dirty=True)
            elif c["mine_path"] and Path(c["mine_path"]).is_file():
                space_vcs.apply_row(conn, *a, value=None, size=int(c["mine_size"]), sha256=c["mine_sha"],
                                    rev=int(cur["rev"]), dirty=True)
                os.replace(c["mine_path"], target)
            else:
                space_vcs.set_row_state(conn, *a, "", dirty=True)
        elif cur is not None:
            space_vcs.set_row_state(conn, *a, "")
        space_vcs.conflict_delete(conn, *a)
    if c["mine_path"] and choice == "theirs":
        Path(c["mine_path"]).unlink(missing_ok=True)
    return {"ok": True}


def _discard_mine(ctx: Ctx, kind: str, key: str) -> dict[str, Any]:
    """Keep theirs after a broken lock: the unsent edit goes and the team's current version
    comes down."""
    if ctx.backend is None:
        return {"ok": False, "error": "Not connected: this space can't be reached right now."}
    got = _call(ctx.backend.fetch, ctx.space, ctx.plugin, kind, key, None)
    if not isinstance(got, IncomingItem):
        return {"ok": False, "error": reason_of(got)}
    if ctx.plugin == WORKFLOWS and kind == "doc":
        from backend.automations import owned

        owned.archive_before_adopt(ctx.scope, key)
    conn = db.connect()
    a = (ctx.account, ctx.space, ctx.plugin, kind, key)
    with db.write_txn(conn):
        space_vcs.conflict_delete(conn, *a)
        cur = space_vcs.row(conn, *a)
        if cur is not None:
            space_vcs.set_row_state(conn, *a, "", dirty=False)
    out = _apply(ctx, [IncomingChangeset(seq=0, items=(got,))], force=True)
    _deliver(ctx, out.get("changed", []))
    return {"ok": out["state"] == "ok", "error": out.get("error", "")}


def restore(account: str, space: str, plugin: str, backend: Any, *, items: Mapping[ItemId, int] | None = None,
            to_seq: int | None = None, keys: Iterable[ItemId] | None = None, message: str = "") -> dict[str, Any]:
    """Restore items to their version at a seq, or the plugin as of ``to_seq`` (``keys``:
    only those items): a new changeset on the server (never a rewrite), then pulled here.
    ``skipped``: items whose version then is no longer kept (left as they are)."""
    held_by = held_reason(account, space)
    if held_by:
        return {"ok": False, "error": held_by}
    extra = {"keys": [tuple(k) for k in keys]} if keys is not None else {}
    got = _call(backend.revert, space, plugin, items=dict(items) if items is not None else None, to_seq=to_seq,
                message=message, **extra)
    if isinstance(got, Locked):
        who = ", ".join(sorted({lk.user_name or lk.user for lk in got.units})) or "someone"
        return {"ok": False, "error": f"Locked by {who}"}
    if not isinstance(got, Committed):
        return {"ok": False, "error": reason_of(got) or "The server didn't restore it."}
    ctx = Ctx(account, space, plugin, backend)
    with _lock(account, space, 30.0) as held:
        pulled = _pull_round(ctx, now=time.time()) if held else {"state": "busy"}
    return {"ok": True, "seq": got.seq, "skipped": [list(i) for i in got.skipped], "pulled": pulled["state"] == "ok"}


def undo(account: str, space: str, plugin: str, backend: Any, seq: int, *, message: str = "") -> dict[str, Any]:
    """Undo changeset ``seq``: each of its items goes back to what it was as of ``seq - 1``
    (the server decides: an item it made is deleted; one whose earlier version is no longer
    kept is left as it is and listed in ``skipped``, never deleted)."""
    page = _call(backend.history, space, plugin, None, seq + 1, 1)
    if not isinstance(page, History) or not page.entries or page.entries[0].seq != seq:
        return {"ok": False, "error": reason_of(page) or "That change is no longer kept."}
    keys = [tuple(vid) for vid in page.entries[0].items]
    return restore(account, space, plugin, backend, to_seq=seq - 1, keys=keys, message=message or f"Undo #{seq}")


def history(account: str, space: str, plugin: str, backend: Any, *, key: ItemId | None = None,
            before: int | None = None, limit: int = 50) -> dict[str, Any]:
    got = _call(backend.history, space, plugin, key, before, limit)
    if not isinstance(got, History):
        return {"ok": False, "error": reason_of(got)}
    return {"ok": True, "entries": [asdict(e) for e in got.entries], "more": got.more}


# --------------------------------------------------------------------------- status


def status(account: str, space: str, plugin: str, *, now: float | None = None) -> dict[str, Any]:
    """What the bar and the drawer show for one plugin's copy in a space."""
    now = time.time() if now is None else now
    head = space_vcs.head_get(account, space, plugin)
    outgoing = [{"kind": r["kind"], "key": r["key"], "size": int(r["size"]), "deleted": bool(int(r["deleted"])),
                 "state": r["sync_state"] or "queued", "reason": r["sync_error"]}
                for r in space_vcs.plugin_rows(account, space, plugin)
                if int(r["dirty"]) and not int(r["sensitive"])]
    locks = space_vcs.locks(account, space, plugin, now=now)
    roster = space_vcs.presence_get(account, space)["roster"]
    return {
        "head": int(head["seq"]),
        "remote": int(head["remote_seq"]),
        "incoming": max(0, int(head["remote_seq"]) - int(head["seq"])),
        "mode": head["mode"],
        "state": head["state"],
        "error": head["error"],
        "nextTry": float(head["next_try"]) or None,
        "syncedAt": float(head["synced_at"]) or None,
        "outgoing": outgoing,
        "sending": len(space_vcs.cs_open(account, space, plugin)),
        "conflicts": [{"kind": c["kind"], "key": c["key"], "reason": c["reason"], "by": c["theirs_by"],
                       "at": c["theirs_at"], "theirsSeq": int(c["theirs_seq"])}
                      for c in space_vcs.conflicts(account, space, plugin)],
        "blocked": [{"kind": b["kind"], "key": b["key"], "error": b["error"], "attempts": int(b["attempts"]),
                     "nextTry": float(b["next_try"])} for b in space_vcs.blocked(account, space, plugin)],
        "locks": [{"unit": lk["unit"], "name": lk["name"] or _unit_name(lk["unit"]), "holder": lk["holder_name"],
                   "mine": lk["mine"], "since": lk["since"], "leaseLeft": lk["lease_left"]} for lk in locks],
        "people": list((roster or {}).get("people") or []) if isinstance(roster, dict) else [],
    }


# --------------------------------------------------------------------------- lost access


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:32] or "team"


def _local_key(account: str, plugin: str, kind: str, key: str, slug: str) -> str:
    """``key`` when Local has nothing there, else ``key-from-<slug>`` (a file keeps its
    extension: ``scene-from-alpha.glb``), numbered if that is taken too."""
    def taken(k: str) -> bool:
        r = repo.get(account, scopes.PERSONAL, plugin, kind, k)
        return bool(r and not int(r["deleted"]))

    if not taken(key):
        return key
    head, sep, leaf = key.rpartition("/")
    stem, dot, ext = leaf.rpartition(".") if kind == "asset" and "." in leaf.lstrip(".") else (leaf, "", "")
    for n in range(1, 100):
        tail = f"-from-{slug}" + (f"-{n}" if n > 1 else "")
        name = f"{stem}{tail}{dot}{ext}"
        candidate = f"{head}{sep}{name}"
        limit = 128 if kind == "doc" else 256
        if len(candidate) > limit:
            candidate = f"{head}{sep}{stem[:max(1, len(stem) - (len(candidate) - limit))]}{tail}{dot}{ext}"
        if not taken(candidate):
            return candidate
    return f"{key}-from-{slug}-{uuid.uuid4().hex[:6]}"


def save_unsent_to_local(account: str, space: str, *, label: str = "") -> dict[str, Any]:
    """Access to the space is gone (or going): this PC's unsent changes are copied into
    Local, each under its own key when Local has none, else ``<key>-from-<space>``: rows
    never sent, and the losing versions of mine unresolved conflicts keep. The copies are
    sealed for this account already, so they are copied as they are."""
    label = label or repo.sync_get(account, space)["label"] or space
    slug = _slug(label)
    saved: list[dict[str, str]] = []
    rows = [(r["plugin_id"], r["kind"], r["key"], r["value"],
             scopes.asset_file({"account": account, "id": space}, r["plugin_id"], r["key"]), r["size"], r["sha256"])
            for r in space_vcs.unsent_rows(account, space)]
    rows += [(c["plugin_id"], c["kind"], c["key"], c["mine_value"], Path(c["mine_path"]) if c["mine_path"] else None,
              c["mine_size"], c["mine_sha"]) for c in space_vcs.unsent_conflicts(account, space)]
    for plugin, kind, key, value, src, size, sha in rows:
        if kind not in KINDS:
            continue
        new_key = _local_key(account, plugin, kind, key, slug)
        if kind == "doc":
            if value is None:
                continue
            repo.put(account, scopes.PERSONAL, plugin, "doc", new_key, value=value, size=int(size), sha256=sha,
                     dirty=False)
        else:
            if src is None or not src.is_file():
                continue
            dst = scopes.asset_file({"account": account, "id": scopes.PERSONAL}, plugin, new_key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            temp = dst.with_name(f"{dst.name}.{uuid.uuid4().hex}.tmp")
            shutil.copyfile(src, temp)
            repo.put_file_row(account, scopes.PERSONAL, plugin, new_key, temp_path=temp, target_path=dst,
                              size=int(size), sha256=sha, dirty=False)
        saved.append({"plugin": plugin, "kind": kind, "key": key, "localKey": new_key})
    space_vcs.lost_choice_put(account, space, "saved")
    return {"ok": True, "saved": saved}


def conflicts_into_rows(account: str, space: str) -> int:
    """Upload my copy, after the space's data was reset on the server: each unresolved
    conflict's losing version of mine becomes its row again (a doc's value; a file's side
    copy back in place), so mine is what goes up. Returns how many."""
    done = 0
    files = _Files()
    conn = db.connect()
    try:
        with db.write_txn(conn):
            for c in space_vcs.unsent_conflicts(account, space):
                a = (account, space, c["plugin_id"], c["kind"], c["key"])
                if c["kind"] == "doc" and c["mine_value"] is not None:
                    space_vcs.apply_row(conn, *a, value=c["mine_value"], size=int(c["mine_size"]),
                                        sha256=c["mine_sha"], rev=0, dirty=True)
                elif c["kind"] == "asset" and c["mine_path"] and Path(c["mine_path"]).is_file():
                    target = scopes.asset_file({"account": account, "id": space}, c["plugin_id"], c["key"])
                    space_vcs.apply_row(conn, *a, value=None, size=int(c["mine_size"]), sha256=c["mine_sha"], rev=0,
                                        dirty=True)
                    files.aside(target)
                    files.move(Path(c["mine_path"]), target, keep=True)
                else:
                    continue
                space_vcs.conflict_delete(conn, *a)
                done += 1
    except BaseException:
        files.undo()
        raise
    files.committed()
    return done


def discard_unsent(account: str, space: str) -> dict[str, Any]:
    """The person chose not to keep the unsent changes of a space they lost."""
    space_vcs.lost_choice_put(account, space, "discarded")
    return {"ok": True}
