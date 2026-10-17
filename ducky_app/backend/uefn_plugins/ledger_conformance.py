"""What every :class:`~backend.uefn_plugins.ledger.LedgerBackend` must do, as checks any
backend factory can run, and :class:`FakeLedger`, an in-memory model of the server
rules the checks describe (core's own tests run the engine against it).

A backend's tests provide a *world* (:class:`World`): clients of one server, as given
users and devices, plus a few knobs to put the server in a state (time passing, a
garbage-collection sweep, a lost upload, trimmed history, a size limit, a purge). Then::

    @pytest.mark.parametrize("check", ledger_conformance.CHECKS, ids=lambda c: c.__name__)
    def test_conformance(check):
        check(MyWorld())

The server rules modelled (and checked):

- a commit gets the next seq of (space, plugin); pushing a cs_id again answers
  :class:`Replay` with its seq;
- an item whose seq on the server is above the change's base answers :class:`Conflict`;
  re-creating a deleted item is allowed from base 0 or the tombstone's seq; a change to
  an item that is gone for good (purged) answers a conflict with ``deleted``;
- a unit under someone else's live lock answers :class:`Locked`; nothing is committed;
- items over the size limit, or workflows from a member who may not change them,
  answer :class:`Refused`; nothing is committed;
- a sweep running answers :class:`Retry`; a lost upload answers :class:`Missing` (or is
  re-uploaded by the backend itself) and the next push commits;
- a pull from below what the server keeps answers ``resync``; a full listing pages
  every item's current version;
- history lists changesets and item versions; revert is a new changeset, as of a seq for
  the whole plugin or only the items named, and never deletes an item whose version then
  is no longer kept (it is skipped);
- a lock is granted only to a PC not behind the unit's last commit; atomic acquires
  are all or nothing; a live lock is broken only by an admin, an expired one by anyone;
  leases run 300 s on the server clock;
- a beat answers the roster (live presence) and live locks;
- a commit and a beat name the caller's device: the lock that device holds is the one
  its commits carry the fence of, and its roster row carries that device id.
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from backend.uefn_plugins.ledger import (
    CAPABILITIES,
    Behind,
    Committed,
    Conflict,
    ConflictItem,
    Denied,
    Done,
    Error,
    Granted,
    Heads,
    Held,
    History,
    HistoryEntry,
    Importing,
    IncomingChangeset,
    IncomingItem,
    ItemId,
    LockInfo,
    LockResult,
    LockUnit,
    Locked,
    Missing,
    Offline,
    OutgoingChangeset,
    OutgoingItem,
    Paused,
    PullPage,
    PushResult,
    Refused,
    RefusedItem,
    Replay,
    Retry,
    Roster,
    unit_of,
)

LEASE_S = 300.0
PRESENCE_LEASE_S = 150.0
WORKFLOWS = "ducky.automations"
NO_WORKFLOW_RIGHTS = "This account can't change these workflows."
TOO_BIG = "Too big for this team's plan."
BREAK_DENIED = "Only the team's owners and admins can break a lock that is still held."


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_item(kind: str, key: str, content: bytes, *, base: int = 0, unit: str = "") -> OutgoingItem:
    """An item to put (checks and tests)."""
    return OutgoingItem(kind=kind, key=key, unit=unit or unit_of(kind, key), op="put", base_seq=base,
                        sha256=sha(content), size=len(content), data=content)


def del_item(kind: str, key: str, *, base: int, unit: str = "") -> OutgoingItem:
    return OutgoingItem(kind=kind, key=key, unit=unit or unit_of(kind, key), op="del", base_seq=base)


def changeset(*items: OutgoingItem, base: int = 0, device: str = "", cs_id: str = "", message: str = "",
              fences: Mapping[str, int] | None = None, group: str = "", part: int = 1,
              last: bool = True) -> OutgoingChangeset:
    return OutgoingChangeset(cs_id=cs_id or uuid.uuid4().hex, base_seq=base, items=tuple(items), device=device,
                             message=message, fences=dict(fences or {}), group=group, part=part, last=last)


# --------------------------------------------------------------------------- the fake server


@dataclass
class _Version:
    seq: int
    kind: str
    key: str
    unit: str
    op: str
    content: bytes | None
    sha256: str
    size: int
    by: str
    at: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Changeset:
    seq: int
    cs_id: str
    by: str
    device: str
    at: float
    actor: str
    ducky: str
    message: str
    group: str
    part: int
    last: bool
    items: list[_Version]


@dataclass
class _Lock:
    unit: str
    name: str
    user: str
    device: str
    since: float
    lease_until: float
    fence: int
    reason: str = "auto"


@dataclass
class _Repo:
    head: int = 0
    changesets: dict[int, _Changeset] = field(default_factory=dict)
    items: dict[ItemId, _Version] = field(default_factory=dict)
    versions: dict[ItemId, list[_Version]] = field(default_factory=dict)
    units: dict[str, tuple[int, str, float]] = field(default_factory=dict)
    created: dict[ItemId, int] = field(default_factory=dict)  # each item's first seq
    kept_from: int = 1  # changesets below this seq are no longer kept (retention)


@dataclass
class _Space:
    epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    repos: dict[str, _Repo] = field(default_factory=dict)
    csids: dict[str, tuple[str, int]] = field(default_factory=dict)
    locks: dict[tuple[str, str], _Lock] = field(default_factory=dict)
    presence: dict[tuple[str, str], tuple[dict[str, Any], float]] = field(default_factory=dict)
    fence: int = 0

    def repo(self, plugin: str) -> _Repo:
        return self.repos.setdefault(plugin, _Repo())


class FakeLedgerServer:
    """One team server shared by every :class:`FakeLedger` client. Knobs are plain
    attributes; ``hooks`` run inside calls (``fetch``, ``push``: ``fn(space, plugin, ...)``)
    so tests can race them."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.skew = 0.0
        self.spaces: dict[str, _Space] = {}
        self.offline = False
        self.paused: set[str] = set()
        self.sweeping: set[str] = set()
        self.importing: dict[tuple[str, str], float] = {}
        self.lose_uploads: dict[str, int] = {}
        self.max_file_bytes: int | None = None
        self.no_workflow_rights: set[str] = set()
        self.admins: set[str] = set()
        self.names: dict[str, str] = {}
        self.bad: set[tuple[str, str, str, str, int]] = set()  # (space, plugin, kind, key, seq) fails to verify
        self.hooks: dict[str, Callable[..., None]] = {}
        self.asks: list[tuple[str, str, str, str]] = []  # (space, plugin, unit, asker)
        self.calls: list[tuple[str, str, str]] = []  # (method, space, plugin)
        self.tmp = Path(tempfile.mkdtemp(prefix="fake-ledger-"))

    def now(self) -> float:
        return time.time() + self.skew

    def space(self, space: str) -> _Space:
        return self.spaces.setdefault(space, _Space())

    def client(self, user: str, device: str = "d1", *, name: str = "", admin: bool = False) -> "FakeLedger":
        if name:
            self.names[user] = name
        if admin:
            self.admins.add(user)
        return FakeLedger(self, user, device)

    def reset_epoch(self, space: str) -> None:
        """The space's data was reset on the server: everything goes, new epoch."""
        with self.lock:
            self.spaces[space] = _Space()

    def purge(self, space: str, plugin: str, kind: str, key: str) -> None:
        with self.lock:
            repo = self.space(space).repo(plugin)
            repo.items.pop((kind, key), None)
            repo.versions.pop((kind, key), None)

    def trim(self, space: str, plugin: str, below_seq: int) -> None:
        """Retention: changesets below ``below_seq`` are no longer kept (current versions are)."""
        with self.lock:
            repo = self.space(space).repo(plugin)
            repo.kept_from = max(repo.kept_from, int(below_seq))
            for seq in [s for s in repo.changesets if s < below_seq]:
                del repo.changesets[seq]
            for vid, versions in repo.versions.items():
                current = repo.items.get(vid)
                repo.versions[vid] = [v for v in versions if v.seq >= below_seq or v is current]

    def rmtree(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class FakeLedger:
    """A client of :class:`FakeLedgerServer` as ``user`` on ``device``."""

    def __init__(self, server: FakeLedgerServer, user: str, device: str) -> None:
        self.server = server
        self.user = user
        self.device = device

    # -- helpers

    def _gate(self, space: str, plugin: str = "", method: str = "") -> Any:
        s = self.server
        s.calls.append((method, space, plugin))
        if s.offline:
            return Offline("no network")
        if space in s.paused:
            return Paused()
        if plugin and (space, plugin) in s.importing:
            return Importing(s.importing[(space, plugin)])
        return None

    def _info(self, plugin: str, lk: _Lock, now: float) -> LockInfo:
        return LockInfo(unit=lk.unit, plugin=plugin, name=lk.name, user=lk.user,
                        user_name=self.server.names.get(lk.user, lk.user), device=lk.device, since=lk.since,
                        lease_left=max(0.0, lk.lease_until - now), fence=lk.fence, reason=lk.reason,
                        mine=(lk.user, lk.device) == (self.user, self.device))

    def _live_locks(self, sp: _Space, now: float, plugins: list[str] | None = None) -> tuple[LockInfo, ...]:
        return tuple(self._info(p, lk, now) for (p, _), lk in sorted(sp.locks.items())
                     if lk.lease_until > now and (plugins is None or p in plugins))

    def _incoming(self, v: _Version, *, content: bool = False) -> IncomingItem:
        data: bytes | None = None
        path = ""
        if content and v.op == "put":
            if v.kind == "doc":
                data = v.content
            else:
                tmp = self.server.tmp / f"{uuid.uuid4().hex}.part"
                tmp.write_bytes(v.content or b"")
                path = str(tmp)
        return IncomingItem(kind=v.kind, key=v.key, unit=v.unit, op=v.op, seq=v.seq, sha256=v.sha256, size=v.size,
                            by=self.server.names.get(v.by, v.by), at=v.at, data=data, path=path, meta=dict(v.meta))

    def _commit(self, sp: _Space, plugin: str, versions: list[_Version], *, cs_id: str, device: str, actor: str = "user",
                ducky: str = "", message: str = "", group: str = "", part: int = 1, last: bool = True) -> int:
        repo = sp.repo(plugin)
        seq = repo.head + 1
        repo.head = seq
        now = self.server.now()
        for v in versions:
            v.seq, v.at = seq, now
            repo.items[(v.kind, v.key)] = v
            repo.versions.setdefault((v.kind, v.key), []).append(v)
            repo.created.setdefault((v.kind, v.key), seq)
            repo.units[v.unit] = (seq, v.by, now)
        repo.changesets[seq] = _Changeset(seq, cs_id, self.user, device, now, actor, ducky, message, group, part, last,
                                          versions)
        sp.csids[cs_id] = (plugin, seq)
        return seq

    def _foreign_locks(self, sp: _Space, plugin: str, units: list[str], fences: Mapping[str, int],
                       now: float, device: str = "") -> list[LockInfo]:
        """Live locks on ``units`` the caller can't commit through: someone else's, or this
        user's on another device (``device``: the one the change names), or a stale fence."""
        out: list[LockInfo] = []
        for unit in dict.fromkeys(units):
            lk = sp.locks.get((plugin, unit))
            if lk is None or lk.lease_until <= now:
                continue
            mine = (lk.user, lk.device) == (self.user, device or self.device)
            if not mine or int(fences.get(unit, lk.fence)) != lk.fence:
                out.append(self._info(plugin, lk, now))
        return out

    # -- LedgerBackend

    def capabilities(self) -> set[str]:
        return set(CAPABILITIES)

    def heads(self, space: str, plugins: list[str]) -> Any:
        with self.server.lock:
            gate = self._gate(space, method="heads")
            if gate is not None and not isinstance(gate, Importing):
                return gate
            sp = self.server.space(space)
            now = self.server.now()
            people = tuple({**blob, "user": u, "user_name": self.server.names.get(u, u), "device": d}
                           for (u, d), (blob, until) in sorted(sp.presence.items()) if until > now)
            used = sum(v.size for r in sp.repos.values() for vs in r.versions.values() for v in vs)
            return Heads(epoch=sp.epoch, heads={p: sp.repo(p).head for p in plugins},
                         importing={p: pct for (s, p), pct in self.server.importing.items() if s == space},
                         locks=self._live_locks(sp, now), people=people, usage={"bytes": used})

    def push(self, space: str, plugin: str, changeset: OutgoingChangeset) -> PushResult:
        s = self.server
        hook = s.hooks.get("push")
        if hook:
            hook(space, plugin, changeset)
        with s.lock:
            gate = self._gate(space, plugin, "push")
            if gate is not None:
                return gate
            sp = s.space(space)
            if changeset.cs_id in sp.csids:
                return Replay(sp.csids[changeset.cs_id][1])
            # Upload: every put's content is read (the backend seals and sends it).
            contents: dict[ItemId, bytes] = {}
            for item in changeset.items:
                if item.op == "put":
                    try:
                        contents[item.id] = item.read()
                    except Exception as exc:  # noqa: BLE001 — a backend never raises
                        return Error(f"{item.key}: {exc}")
            if space in s.sweeping:
                return Retry(5.0)
            repo = sp.repo(plugin)
            now = s.now()
            conflicts: list[ConflictItem] = []
            for item in changeset.items:
                cur = repo.items.get(item.id)
                if cur is None:
                    if item.base_seq > 0:  # gone for good: never re-created silently
                        conflicts.append(ConflictItem(item.kind, item.key, 0, "", 0.0, True))
                    continue
                if cur.seq > item.base_seq and not (cur.op == "del" and item.op == "put" and item.base_seq == 0):
                    conflicts.append(ConflictItem(item.kind, item.key, cur.seq, s.names.get(cur.by, cur.by), cur.at,
                                                  cur.op == "del"))
            if conflicts:
                return Conflict(tuple(conflicts))
            locked = self._foreign_locks(sp, plugin, [i.unit for i in changeset.items], changeset.fences, now,
                                         changeset.device)
            if locked:
                return Locked(tuple(locked))
            if plugin == WORKFLOWS and self.user in s.no_workflow_rights:
                return Refused(tuple(RefusedItem(i.kind, i.key, NO_WORKFLOW_RIGHTS) for i in changeset.items))
            if s.max_file_bytes is not None:
                big = [RefusedItem(i.kind, i.key, TOO_BIG) for i in changeset.items
                       if i.op == "put" and len(contents[i.id]) > s.max_file_bytes]
                if big:
                    return Refused(tuple(big))
            if s.lose_uploads.get(space, 0) > 0 and contents:
                s.lose_uploads[space] -= 1
                return Missing(tuple(sha(c) for c in contents.values()))
            versions = [
                _Version(0, i.kind, i.key, i.unit, i.op, contents.get(i.id), sha(contents[i.id]) if i.op == "put" else "",
                         len(contents.get(i.id) or b""), self.user, now, dict(i.meta))
                for i in changeset.items
            ]
            seq = self._commit(sp, plugin, versions, cs_id=changeset.cs_id, device=changeset.device or self.device,
                               actor=changeset.actor, ducky=changeset.ducky, message=changeset.message,
                               group=changeset.group, part=changeset.part, last=changeset.last)
            for unit in changeset.release_locks:
                lk = sp.locks.get((plugin, unit))
                if lk and (lk.user, lk.device) == (self.user, self.device):
                    del sp.locks[(plugin, unit)]
            return Committed(seq, {(v.kind, v.key): seq for v in versions})

    def pull(self, space: str, plugin: str, since: int, limit: int, *, full: bool = False, after: str = "") -> Any:
        with self.server.lock:
            gate = self._gate(space, plugin, "pull")
            if gate is not None:
                return gate
            repo = self.server.space(space).repo(plugin)
            limit = max(1, min(int(limit), 50))
            if full:
                ordered = sorted(repo.items.items(), key=lambda kv: f"{kv[0][0]}\n{kv[0][1]}")
                rest = [(k, v) for k, v in ordered if f"{k[0]}\n{k[1]}" > after]
                page = rest[:limit]
                cursor = f"{page[-1][0][0]}\n{page[-1][0][1]}" if page else after
                return PullPage(head=repo.head, more=len(rest) > limit, items=tuple(self._incoming(v) for _, v in page),
                                after=cursor)
            if int(since) + 1 < repo.kept_from and repo.head > int(since):
                return PullPage(head=repo.head, resync=True)
            seqs = sorted(s for s in repo.changesets if s > int(since))
            out = []
            for seq in seqs[:limit]:
                cs = repo.changesets[seq]
                out.append(IncomingChangeset(
                    seq=seq, items=tuple(self._incoming(v) for v in cs.items), cs_id=cs.cs_id,
                    by=self.server.names.get(cs.by, cs.by), device=cs.device, at=cs.at, actor=cs.actor,
                    ducky=cs.ducky, message=cs.message, group=cs.group, part=cs.part, last=cs.last,
                ))
            return PullPage(changesets=tuple(out), head=repo.head, more=len(seqs) > limit)

    def fetch(self, space: str, plugin: str, kind: str, key: str, seq: int | None = None) -> Any:
        s = self.server
        hook = s.hooks.get("fetch")
        if hook:
            hook(space, plugin, kind, key, seq)
        with s.lock:
            gate = self._gate(space, plugin, "fetch")
            if gate is not None:
                return gate if isinstance(gate, Offline) else Error(type(gate).__name__)
            repo = s.space(space).repo(plugin)
            versions = repo.versions.get((kind, key)) or []
            if seq is None:
                found = repo.items.get((kind, key))
            else:
                found = next((v for v in versions if v.seq == int(seq)), None)
            if found is None:
                return Error("This version is no longer kept.")
            if (space, plugin, kind, key, found.seq) in s.bad:
                return Error("The download didn't verify.")
            return self._incoming(found, content=True)

    def history(self, space: str, plugin: str, key: ItemId | None = None, before: int | None = None,
                limit: int = 50) -> Any:
        with self.server.lock:
            gate = self._gate(space, plugin, "history")
            if isinstance(gate, Offline):
                return gate
            repo = self.server.space(space).repo(plugin)
            names = self.server.names
            if key is None:
                seqs = sorted((s for s in repo.changesets if before is None or s < before), reverse=True)
                entries = []
                for s_ in seqs[:limit]:
                    cs = repo.changesets[s_]
                    entries.append(HistoryEntry(seq=s_, by=names.get(cs.by, cs.by), at=cs.at, device=cs.device,
                                                actor=cs.actor, ducky=cs.ducky, message=cs.message,
                                                count=len(cs.items), items=tuple((v.kind, v.key) for v in cs.items)))
                return History(tuple(entries), more=len(seqs) > limit)
            versions = sorted((v for v in repo.versions.get(tuple(key), []) if before is None or v.seq < before),
                              key=lambda v: v.seq, reverse=True)
            entries = [HistoryEntry(seq=v.seq, by=names.get(v.by, v.by), at=v.at, kind=v.kind, key=v.key,
                                    deleted=v.op == "del", size=v.size, sha256=v.sha256) for v in versions[:limit]]
            return History(tuple(entries), more=len(versions) > limit)

    def revert(self, space: str, plugin: str, items: Mapping[ItemId, int] | None = None, to_seq: int | None = None,
               message: str = "", *, keys: Any = None) -> Any:
        s = self.server
        with s.lock:
            gate = self._gate(space, plugin, "revert")
            if gate is not None:
                return gate
            if space in s.sweeping:
                return Retry(5.0)
            sp = s.space(space)
            repo = sp.repo(plugin)
            now = s.now()
            targets: dict[ItemId, _Version | None] = {}
            skipped: list[ItemId] = []
            if items is not None:
                for vid, seq in items.items():
                    if int(seq) == 0:
                        cur = repo.items.get(tuple(vid))
                        if cur is not None and cur.op == "put":
                            targets[tuple(vid)] = None  # back to before it existed: deleted
                        continue
                    old = next((v for v in repo.versions.get(tuple(vid), []) if v.seq == int(seq)), None)
                    if old is None:
                        skipped.append(tuple(vid))
                    else:
                        targets[tuple(vid)] = old
            elif to_seq is not None:
                only = None if keys is None else {tuple(k) for k in keys}
                for vid, cur in repo.items.items():
                    if only is not None and vid not in only:
                        continue
                    kept = [v for v in repo.versions.get(vid, []) if v.seq <= int(to_seq)]
                    if kept:
                        targets[vid] = kept[-1]
                    elif repo.created.get(vid, 0) > int(to_seq):
                        if cur.op == "put":
                            targets[vid] = None  # made after to_seq: deleted
                    else:
                        skipped.append(vid)  # its version then is no longer kept
            versions: list[_Version] = []
            for vid, old in targets.items():
                cur = repo.items.get(vid)
                if old is None:
                    versions.append(_Version(0, vid[0], vid[1], cur.unit if cur else unit_of(*vid), "del", None, "", 0,
                                             self.user, now))
                elif cur is None or cur.sha256 != old.sha256 or cur.op != old.op:
                    versions.append(replace(old, seq=0, by=self.user, at=now))
            locked = self._foreign_locks(sp, plugin, [v.unit for v in versions], {}, now)
            if locked:
                return Locked(tuple(locked))
            if not versions:
                return Committed(repo.head, {}, tuple(skipped))
            seq = self._commit(sp, plugin, versions, cs_id=uuid.uuid4().hex, device=self.device, message=message)
            return Committed(seq, {(v.kind, v.key): seq for v in versions}, tuple(skipped))

    def lock(self, space: str, plugin: str, units: list[LockUnit], mode: str, have_seq: Mapping[str, int]) -> Any:
        s = self.server
        with s.lock:
            gate = self._gate(space, method="lock")
            if gate is not None and not isinstance(gate, Importing):
                return gate
            sp = s.space(space)
            repo = sp.repo(plugin)
            now = s.now()
            out: dict[str, LockResult] = {}
            granted: list[str] = []
            for lu in units:
                lk = sp.locks.get((plugin, lu.unit))
                if lk is not None and lk.lease_until > now:
                    if (lk.user, lk.device) == (self.user, self.device):
                        lk.lease_until = now + LEASE_S
                        out[lu.unit] = Held(lk.fence, LEASE_S)
                    else:
                        out[lu.unit] = self._info(plugin, lk, now)
                    continue
                last = repo.units.get(lu.unit)
                if last is not None and last[0] > int(have_seq.get(lu.unit, 0)):
                    out[lu.unit] = Behind(last[0], s.names.get(last[1], last[1]), last[2])
                    continue
                sp.fence += 1
                sp.locks[(plugin, lu.unit)] = _Lock(lu.unit, lu.name, self.user, self.device, now, now + LEASE_S,
                                                    sp.fence)
                out[lu.unit] = Granted(sp.fence, LEASE_S)
                granted.append(lu.unit)
            if mode == "atomic" and any(not isinstance(r, (Granted, Held)) for r in out.values()):
                for unit in granted:
                    del sp.locks[(plugin, unit)]
                    del out[unit]
            return out

    def unlock(self, space: str, plugin: str, units: list[str]) -> Any:
        with self.server.lock:
            gate = self._gate(space, method="unlock")
            if isinstance(gate, Offline):
                return gate
            sp = self.server.space(space)
            for unit in units:
                lk = sp.locks.get((plugin, unit))
                if lk and (lk.user, lk.device) == (self.user, self.device):
                    del sp.locks[(plugin, unit)]
            return Done()

    def break_lock(self, space: str, plugin: str, unit: str) -> Any:
        s = self.server
        with s.lock:
            gate = self._gate(space, method="break")
            if isinstance(gate, Offline):
                return gate
            sp = s.space(space)
            lk = sp.locks.get((plugin, unit))
            if lk is None:
                return Done()
            live = lk.lease_until > s.now()
            if live and (lk.user, lk.device) != (self.user, self.device) and self.user not in s.admins:
                return Denied(BREAK_DENIED)
            del sp.locks[(plugin, unit)]
            return Done()

    def ask(self, space: str, plugin: str, unit: str) -> Any:
        with self.server.lock:
            gate = self._gate(space, method="ask")
            if isinstance(gate, Offline):
                return gate
            self.server.asks.append((space, plugin, unit, self.user))
            return Done()

    def beat(self, space: str, blob: dict[str, Any]) -> Any:
        s = self.server
        with s.lock:
            gate = self._gate(space, method="beat")
            if gate is not None and not isinstance(gate, Importing):
                return gate
            sp = s.space(space)
            now = s.now()
            sp.presence[(self.user, self.device)] = (dict(blob), now + PRESENCE_LEASE_S)
            people = tuple({**b, "user": u, "user_name": s.names.get(u, u), "device": d}
                           for (u, d), (b, until) in sorted(sp.presence.items()) if until > now)
            return Roster(people=people, locks=self._live_locks(sp, now))


# --------------------------------------------------------------------------- the checks


class World(Protocol):
    """One server and the knobs the checks need. A backend's tests implement it."""

    def client(self, user: str, device: str = "d1", *, name: str = "", admin: bool = False) -> Any:
        """A backend signed in as ``user`` on ``device`` (``admin``: may break live locks)."""
        ...

    def advance(self, seconds: float) -> None:
        """Server time passes."""
        ...

    def set_sweeping(self, space: str, on: bool) -> None:
        """A garbage-collection sweep holds the space's commits."""
        ...

    def lose_next_upload(self, space: str) -> None:
        """What the next push uploads goes missing once before its commit."""
        ...

    def trim(self, space: str, plugin: str, below_seq: int) -> None:
        """Retention drops changesets below ``below_seq``."""
        ...

    def set_max_file_bytes(self, limit: int | None) -> None:
        ...

    def purge(self, space: str, plugin: str, kind: str, key: str) -> None:
        """An owner purges one item and its history for good."""
        ...


class FakeWorld:
    """:class:`World` over :class:`FakeLedgerServer`."""

    def __init__(self) -> None:
        self.server = FakeLedgerServer()

    def client(self, user: str, device: str = "d1", *, name: str = "", admin: bool = False) -> FakeLedger:
        return self.server.client(user, device, name=name, admin=admin)

    def advance(self, seconds: float) -> None:
        self.server.skew += float(seconds)

    def set_sweeping(self, space: str, on: bool) -> None:
        (self.server.sweeping.add if on else self.server.sweeping.discard)(space)

    def lose_next_upload(self, space: str) -> None:
        self.server.lose_uploads[space] = self.server.lose_uploads.get(space, 0) + 1

    def trim(self, space: str, plugin: str, below_seq: int) -> None:
        self.server.trim(space, plugin, below_seq)

    def set_max_file_bytes(self, limit: int | None) -> None:
        self.server.max_file_bytes = limit

    def purge(self, space: str, plugin: str, kind: str, key: str) -> None:
        self.server.purge(space, plugin, kind, key)


SPACE = "spaceConf"
PLUGIN = "cards"


def _expect(cond: bool, what: str) -> None:
    if not cond:
        raise AssertionError(what)


def _commit(backend: Any, *items: OutgoingItem, **kw: Any) -> Committed:
    out = backend.push(SPACE, PLUGIN, changeset(*items, **kw))
    if isinstance(out, Missing):  # a backend may leave the re-upload to the next push
        out = backend.push(SPACE, PLUGIN, changeset(*items, **kw))
    _expect(isinstance(out, Committed), f"expected a commit, got {out!r}")
    return out


def _content(backend: Any, kind: str, key: str, seq: int | None = None) -> bytes | None:
    got = backend.fetch(SPACE, PLUGIN, kind, key, seq)
    _expect(isinstance(got, IncomingItem), f"fetch {key} failed: {got!r}")
    if got.op == "del":
        return None
    data = got.read()
    if got.path:
        Path(got.path).unlink(missing_ok=True)
    return data


def check_commit_and_pull(world: World) -> None:
    """Commits get dense seqs; a pull lists them in order with what changed; fetch gives the content."""
    a, b = world.client("ana", "d1", name="Ana"), world.client("ben", "d2", name="Ben")
    first = _commit(a, put_item("doc", "card.pip", b'{"hp":1}'), put_item("asset", "img/pip.png", b"\x89PNG"))
    second = _commit(b, put_item("doc", "card.zed", b'{"hp":2}'))
    _expect((first.seq, second.seq) == (1, 2), f"seqs {first.seq}, {second.seq}")
    _expect(first.items.get(("doc", "card.pip")) == 1, f"item seqs {first.items}")
    page = b.pull(SPACE, PLUGIN, 0, 50)
    _expect(isinstance(page, PullPage) and page.head == 2 and not page.more, f"pull {page!r}")
    _expect([cs.seq for cs in page.changesets] == [1, 2], "changesets in seq order")
    _expect({i.id for i in page.changesets[0].items} == {("doc", "card.pip"), ("asset", "img/pip.png")}, "items")
    _expect(page.changesets[0].items[0].seq == 1, "item seq in a pulled changeset")
    _expect(_content(b, "doc", "card.pip") == b'{"hp":1}', "doc content")
    _expect(_content(b, "asset", "img/pip.png") == b"\x89PNG", "file content")
    later = b.pull(SPACE, PLUGIN, 1, 50)
    _expect([cs.seq for cs in later.changesets] == [2], "pull after a seq")
    heads = b.heads(SPACE, [PLUGIN])
    _expect(isinstance(heads, Heads) and heads.heads.get(PLUGIN) == 2 and heads.epoch, f"heads {heads!r}")


def check_replay(world: World) -> None:
    """The same cs_id pushed twice is one commit: the second answer is a replay of its seq."""
    a = world.client("ana")
    cs = changeset(put_item("doc", "card.pip", b"1"))
    first = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(first, Committed), f"first {first!r}")
    again = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(again, Replay) and again.seq == first.seq, f"replay {again!r}")
    _expect(a.pull(SPACE, PLUGIN, 0, 50).head == first.seq, "no second commit")


def check_conflict(world: World) -> None:
    """A change based on an older version of an item answers a conflict naming the newer one."""
    a, b = world.client("ana", name="Ana"), world.client("ben", "d2", name="Ben")
    _commit(a, put_item("doc", "card.pip", b"a1"))
    out = b.push(SPACE, PLUGIN, changeset(put_item("doc", "card.pip", b"b1", base=0)))
    _expect(isinstance(out, Conflict), f"expected a conflict, got {out!r}")
    item = out.items[0]
    _expect(item.id == ("doc", "card.pip") and item.seq == 1 and not item.deleted, f"conflict item {item!r}")
    # Other items commit when the change is based on what the server has.
    ok = _commit(b, put_item("doc", "card.pip", b"b1", base=1), put_item("doc", "card.new", b"n"))
    _expect(ok.seq == 2, "commit on the current base")


def check_recreate_after_delete(world: World) -> None:
    """A deleted item can be made again from base 0 or the tombstone's seq; an edit based
    on an older version conflicts with the delete; a purged item never comes back silently."""
    a, b = world.client("ana"), world.client("ben", "d2")
    _commit(a, put_item("doc", "card.pip", b"1"))
    gone = _commit(a, del_item("doc", "card.pip", base=1))
    edit = b.push(SPACE, PLUGIN, changeset(put_item("doc", "card.pip", b"mine", base=1)))
    _expect(isinstance(edit, Conflict) and edit.items[0].deleted, f"edit vs delete {edit!r}")
    _commit(b, put_item("doc", "card.pip", b"new", base=gone.seq))
    _commit(a, put_item("doc", "card.zed", b"z"))
    _commit(a, del_item("doc", "card.zed", base=4))
    _commit(b, put_item("doc", "card.zed", b"fresh", base=0))
    world.purge(SPACE, PLUGIN, "doc", "card.zed")
    out = b.push(SPACE, PLUGIN, changeset(put_item("doc", "card.zed", b"again", base=6)))
    _expect(isinstance(out, Conflict) and out.items[0].deleted, f"purged item {out!r}")


def check_locked(world: World) -> None:
    """A unit someone else holds refuses commits touching it; nothing is committed."""
    a, b = world.client("ana", name="Ana"), world.client("ben", "d2", name="Ben")
    got = a.lock(SPACE, PLUGIN, [LockUnit("doc:card.pip", "card.pip")], "best", {"doc:card.pip": 0})
    _expect(isinstance(got.get("doc:card.pip"), Granted), f"grant {got!r}")
    fence = got["doc:card.pip"].fence
    out = b.push(SPACE, PLUGIN, changeset(put_item("doc", "card.pip", b"b")))
    _expect(isinstance(out, Locked) and out.units[0].unit == "doc:card.pip" and out.units[0].user_name == "Ana",
            f"locked {out!r}")
    _expect(b.pull(SPACE, PLUGIN, 0, 50).head == 0, "nothing committed")
    _commit(a, put_item("doc", "card.pip", b"a"), fences={"doc:card.pip": fence})


def check_refused(world: World) -> None:
    """Items over the plan's size limit are refused with the reason; nothing is committed."""
    a = world.client("ana")
    world.set_max_file_bytes(10)
    out = a.push(SPACE, PLUGIN, changeset(put_item("asset", "big.bin", b"x" * 64), put_item("doc", "small", b"1")))
    _expect(isinstance(out, Refused) and [i.id for i in out.items] == [("asset", "big.bin")] and out.items[0].reason,
            f"refused {out!r}")
    _expect(a.pull(SPACE, PLUGIN, 0, 50).head == 0, "nothing committed")
    world.set_max_file_bytes(None)
    _commit(a, put_item("doc", "small", b"1"))


def check_retry(world: World) -> None:
    """While a sweep runs commits answer retry; afterwards the same changeset commits."""
    a = world.client("ana")
    world.set_sweeping(SPACE, True)
    cs = changeset(put_item("doc", "card.pip", b"1"))
    out = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(out, Retry) and out.after > 0, f"retry {out!r}")
    world.set_sweeping(SPACE, False)
    done = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(done, Committed), f"after the sweep {done!r}")


def check_missing(world: World) -> None:
    """An upload that went missing is sent again: the push answers missing (and the next
    one commits) or re-uploads by itself."""
    a = world.client("ana")
    world.lose_next_upload(SPACE)
    cs = changeset(put_item("asset", "img/a.png", b"pixels"))
    out = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(out, (Missing, Committed)), f"missing {out!r}")
    if isinstance(out, Missing):
        out = a.push(SPACE, PLUGIN, cs)
    _expect(isinstance(out, Committed), f"after re-upload {out!r}")
    _expect(_content(a, "asset", "img/a.png") == b"pixels", "content after re-upload")


def check_resync(world: World) -> None:
    """A pull from below what the server keeps says resync; the full listing pages every
    item's current version (deletes too) exactly once."""
    a = world.client("ana")
    for n in range(5):
        _commit(a, put_item("doc", f"card.{n}", str(n).encode()))
    _commit(a, del_item("doc", "card.0", base=1))
    world.trim(SPACE, PLUGIN, 4)
    page = a.pull(SPACE, PLUGIN, 1, 50)
    _expect(isinstance(page, PullPage) and page.resync and page.head == 6, f"resync {page!r}")
    seen: dict[ItemId, IncomingItem] = {}
    after = ""
    for _ in range(10):
        listing = a.pull(SPACE, PLUGIN, 0, 2, full=True, after=after)
        _expect(isinstance(listing, PullPage), f"listing {listing!r}")
        for item in listing.items:
            _expect(item.id not in seen, f"{item.id} listed twice")
            seen[item.id] = item
        after = listing.after
        if not listing.more:
            break
    _expect(set(seen) == {("doc", f"card.{n}") for n in range(5)}, f"listing {sorted(seen)}")
    _expect(seen[("doc", "card.0")].deleted and seen[("doc", "card.0")].seq == 6, "a delete is listed")
    _expect(seen[("doc", "card.3")].seq == 4, "each item's own seq")
    ok = a.pull(SPACE, PLUGIN, 4, 50)
    _expect(not ok.resync and [cs.seq for cs in ok.changesets] == [5, 6], "pull from what is kept")


def check_history(world: World) -> None:
    """History lists changesets newest first (who, message, items) and one item's versions."""
    a, b = world.client("ana", name="Ana"), world.client("ben", "d2", name="Ben")
    _commit(a, put_item("doc", "card.pip", b"1"), message="first")
    _commit(b, put_item("doc", "card.pip", b"2", base=1), put_item("doc", "card.zed", b"z"), message="second")
    h = a.history(SPACE, PLUGIN)
    _expect(isinstance(h, History) and [e.seq for e in h.entries] == [2, 1], f"history {h!r}")
    _expect(h.entries[0].count == 2 and h.entries[0].message == "second" and h.entries[0].by == "Ben", "entry")
    item = a.history(SPACE, PLUGIN, key=("doc", "card.pip"))
    _expect([e.seq for e in item.entries] == [2, 1] and item.entries[1].by == "Ana", f"versions {item!r}")
    older = a.history(SPACE, PLUGIN, before=2)
    _expect([e.seq for e in older.entries] == [1], "before")


def check_revert(world: World) -> None:
    """Restoring an item is a new changeset with the old content; restoring the plugin to
    a seq also deletes items made after it."""
    a = world.client("ana")
    _commit(a, put_item("doc", "card.pip", b"v1"))
    _commit(a, put_item("doc", "card.pip", b"v2", base=1))
    out = a.revert(SPACE, PLUGIN, items={("doc", "card.pip"): 1}, message="restore")
    _expect(isinstance(out, Committed) and out.seq == 3, f"revert {out!r}")
    _expect(_content(a, "doc", "card.pip") == b"v1", "restored content")
    _commit(a, put_item("doc", "card.new", b"n"))
    back = a.revert(SPACE, PLUGIN, to_seq=2)
    _expect(isinstance(back, Committed), f"revert to seq {back!r}")
    _expect(_content(a, "doc", "card.pip") == b"v2", "plugin as of seq 2")
    _expect(_content(a, "doc", "card.new") is None, "made after seq 2: deleted")
    made = _commit(a, put_item("doc", "card.tmp", b"t"))
    undone = a.revert(SPACE, PLUGIN, items={("doc", "card.tmp"): 0})
    _expect(isinstance(undone, Committed) and undone.seq == made.seq + 1, f"revert to 0 {undone!r}")
    _expect(_content(a, "doc", "card.tmp") is None, "back to before it existed: deleted")


def check_lock_successor(world: World) -> None:
    """A lock is granted only to a PC that has applied the unit's last commit; a renew is
    held; an atomic acquire is all or nothing; release frees the unit."""
    a, b = world.client("ana", name="Ana"), world.client("ben", "d2", name="Ben")
    unit = "doc:card.pip"
    _commit(a, put_item("doc", "card.pip", b"1"))
    behind = b.lock(SPACE, PLUGIN, [LockUnit(unit, "card.pip")], "best", {unit: 0})
    _expect(isinstance(behind.get(unit), Behind) and behind[unit].seq == 1, f"behind {behind!r}")
    got = b.lock(SPACE, PLUGIN, [LockUnit(unit, "card.pip")], "best", {unit: 1})
    _expect(isinstance(got.get(unit), Granted), f"granted {got!r}")
    again = b.lock(SPACE, PLUGIN, [LockUnit(unit, "card.pip")], "best", {unit: 1})
    _expect(isinstance(again.get(unit), Held) and again[unit].fence == got[unit].fence, f"renew {again!r}")
    theirs = a.lock(SPACE, PLUGIN, [LockUnit("doc:card.zed"), LockUnit(unit)], "atomic", {unit: 1})
    _expect(isinstance(theirs.get(unit), LockInfo) and theirs[unit].user_name == "Ben", f"locked {theirs!r}")
    _expect(not isinstance(theirs.get("doc:card.zed"), Granted), "atomic: nothing granted")
    free = a.lock(SPACE, PLUGIN, [LockUnit("doc:card.zed")], "best", {})
    _expect(isinstance(free.get("doc:card.zed"), Granted), "atomic released what it took")
    _expect(isinstance(b.unlock(SPACE, PLUGIN, [unit]), Done), "unlock")
    mine = a.lock(SPACE, PLUGIN, [LockUnit(unit)], "best", {unit: 1})
    _expect(isinstance(mine.get(unit), Granted), "free after release")


def check_break_and_expiry(world: World) -> None:
    """A live lock is broken only by an admin; after its 300 s lease anyone may take it,
    and the old holder's fence no longer commits."""
    a = world.client("ana", name="Ana")
    b = world.client("ben", "d2", name="Ben")
    boss = world.client("olga", "d3", name="Olga", admin=True)
    unit = "doc:card.pip"
    a.lock(SPACE, PLUGIN, [LockUnit(unit)], "best", {})
    _expect(isinstance(b.break_lock(SPACE, PLUGIN, unit), Denied), "a member can't break a live lock")
    _expect(isinstance(boss.break_lock(SPACE, PLUGIN, unit), Done), "an admin can")
    again = a.lock(SPACE, PLUGIN, [LockUnit(unit)], "best", {})
    _expect(isinstance(again.get(unit), Granted), f"free after the break {again!r}")
    old_fence = again[unit].fence
    world.advance(LEASE_S + 1)
    took = b.lock(SPACE, PLUGIN, [LockUnit(unit)], "best", {})
    _expect(isinstance(took.get(unit), Granted), f"expired lock taken over {took!r}")
    stale = a.push(SPACE, PLUGIN, changeset(put_item("doc", "card.pip", b"a"), fences={unit: old_fence}))
    _expect(isinstance(stale, Locked), f"stale fence {stale!r}")


def check_beat(world: World) -> None:
    """A beat answers the live roster and the live locks (each saying whether it is mine)."""
    a, b = world.client("ana", name="Ana"), world.client("ben", "d2", name="Ben")
    a.lock(SPACE, PLUGIN, [LockUnit("doc:card.pip", "card.pip")], "best", {})
    a.beat(SPACE, {"device": "Ana's PC", "plugins": {PLUGIN: {"viewing": True}}})
    roster = b.beat(SPACE, {"device": "Ben's PC"})
    _expect(isinstance(roster, Roster), f"beat {roster!r}")
    users = sorted(p.get("user") for p in roster.people)
    _expect(users == ["ana", "ben"], f"people {users}")
    ana = next(p for p in roster.people if p.get("user") == "ana")
    _expect(ana.get("device") and ana.get("plugins") == {PLUGIN: {"viewing": True}}, "the blob comes back opened")
    _expect([(lk.unit, lk.mine) for lk in roster.locks] == [("doc:card.pip", False)], f"locks {roster.locks}")
    world.advance(PRESENCE_LEASE_S + 1)
    later = b.beat(SPACE, {"device": "Ben's PC"})
    _expect([p.get("user") for p in later.people] == ["ben"], "presence runs out")


def check_revert_keys_as_of(world: World) -> None:
    """Undo: only the items named go back to what they were as of a seq. One made after it
    is deleted; one whose version then is no longer kept is skipped, never deleted."""
    a = world.client("ana")
    _commit(a, put_item("doc", "card.a", b"a1"))
    _commit(a, put_item("doc", "card.a", b"a2", base=1))
    world.trim(SPACE, PLUGIN, 2)
    _commit(a, put_item("doc", "card.a", b"a3", base=2), put_item("doc", "card.b", b"b1"),
            put_item("doc", "card.c", b"c1"))
    out = a.revert(SPACE, PLUGIN, to_seq=1, keys=[("doc", "card.a"), ("doc", "card.b")], message="Undo #3")
    _expect(isinstance(out, Committed) and out.skipped == (("doc", "card.a"),), f"undo {out!r}")
    _expect(_content(a, "doc", "card.a") == b"a3", "a version no longer kept: left as it is")
    _expect(_content(a, "doc", "card.b") is None, "made after the seq: deleted")
    _expect(_content(a, "doc", "card.c") == b"c1", "an item not named is untouched")


def check_device_identity(world: World) -> None:
    """A commit names this PC's device: carrying the fence of the lock that device holds,
    it goes through, and the roster row of that device's beat has the same device id."""
    device = "pc-ana-1"
    a = world.client("ana", device, name="Ana")
    unit = "doc:card.pip"
    got = a.lock(SPACE, PLUGIN, [LockUnit(unit, "card.pip")], "best", {})
    _expect(isinstance(got.get(unit), Granted), f"grant {got!r}")
    _commit(a, put_item("doc", "card.pip", b"a"), device=device, fences={unit: got[unit].fence})
    roster = a.beat(SPACE, {"label": "Ana's PC"})
    _expect(isinstance(roster, Roster), f"beat {roster!r}")
    _expect([p.get("device") for p in roster.people if p.get("user") == "ana"] == [device],
            f"roster device {roster.people!r}")
    _expect([(lk.unit, lk.device, lk.mine) for lk in roster.locks] == [(unit, device, True)], f"locks {roster.locks}")


CHECKS: list[Callable[[World], None]] = [
    check_commit_and_pull,
    check_replay,
    check_conflict,
    check_recreate_after_delete,
    check_locked,
    check_refused,
    check_retry,
    check_missing,
    check_resync,
    check_history,
    check_revert,
    check_lock_successor,
    check_break_and_expiry,
    check_beat,
    check_revert_keys_as_of,
    check_device_identity,
]
