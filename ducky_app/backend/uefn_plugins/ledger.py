"""The remote side of a shared space's repo: what a provider's ledger backend does for
the version engine (:mod:`backend.uefn_plugins.vcs_engine`).

Core is engine-agnostic: a provider returns a :class:`LedgerBackend` from
``Provider.ledger(account, space, plugin)`` (None keeps that plugin on the provider's
older sync). Any backend must pass :mod:`backend.uefn_plugins.ledger_conformance`.

Rules every backend keeps:

- Every method is synchronous, is called from scheduler threads, and never raises:
  a failure comes back as :class:`Offline` (no network, a timeout: any exception type)
  or :class:`Error` (anything else), with the reason.
- Core passes plaintext (bytes, or a plaintext file path) and plaintext metadata, and
  gets plaintext back. The backend does all sealing, chunking and verifying.
- An item is ``(kind, key)``: ``kind`` is ``doc`` (an ``api.data`` doc key), ``asset``
  (an ``api.data`` file path) or ``tree`` (a folder file, key ``tree:<folder>/<h32>``).
  Maps of items in results are keyed by that ``(kind, key)`` tuple.
- A unit is what locks and presence are about: ``doc:<key>``, ``asset:<path>`` or a
  ``tree:...`` unit id. ``seq`` is dense per (space, plugin); an item's seq is the seq
  of the changeset that last changed it.
- This PC is one device: ``backend.store.repos.space_vcs.device_id()``, the same value
  core puts in :attr:`OutgoingChangeset.device`. Every call names it to the server (a
  commit, a lock, a beat), so a lock this PC holds is the one its commits carry the
  fence of, :attr:`LockInfo.device` / :attr:`LockInfo.mine` say whose lock it is, and a
  roster row's ``device`` is that id (core finds its own row by it). Never a hardware id.
- A plugin moving from the provider's older sync: :meth:`LedgerBackend.pull` with
  ``full=True`` lists every item, and an item imported from the older sync carries
  ``meta["v1rev"]``, the older sync's revision it was imported at. Core reconciles this
  PC's copy against that listing once, before its first changeset round.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, Union, runtime_checkable

# Capabilities a backend may answer with (:meth:`LedgerBackend.capabilities`).
CAP_LOCKS = "locks"  # lock, unlock, break_lock
CAP_ASK = "ask"
CAP_PRESENCE = "presence"  # beat
CAP_HISTORY = "history"
CAP_REVERT = "revert"
CAP_RESYNC = "resync"  # pull(full=True) lists every item
CAPABILITIES = frozenset({CAP_LOCKS, CAP_ASK, CAP_PRESENCE, CAP_HISTORY, CAP_REVERT, CAP_RESYNC})

KINDS = ("doc", "asset", "tree")
OPS = ("put", "del")
LOCK_MODES = ("atomic", "best")
ItemId = tuple[str, str]  # (kind, key)


def unit_of(kind: str, key: str) -> str:
    """The unit of an ``api.data`` item: ``doc:<key>`` / ``asset:<path>``. A tree item's
    unit comes from its folder unit, never from its key."""
    return f"{kind}:{key}"


# --------------------------------------------------------------------------- what goes out


@dataclass(frozen=True)
class OutgoingItem:
    """One change in a changeset. ``base_seq`` is the item's seq this change is based on
    (0: new here). The content of a put is ``read()``: plaintext from ``data``, from
    ``reader`` (opened on demand, e.g. a file sealed at rest) or from the plaintext file
    at ``path``. ``meta`` is plaintext metadata for the backend to seal (``relpath``,
    ``mtime_ns``, ``mode``, ``unit_name``...)."""

    kind: str
    key: str
    unit: str
    op: str
    base_seq: int = 0
    sha256: str = ""
    size: int = 0
    data: bytes | None = None
    path: str = ""
    reader: Callable[[], bytes] | None = field(default=None, compare=False, repr=False)
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> ItemId:
        return (self.kind, self.key)

    def read(self) -> bytes:
        if self.data is not None:
            return self.data
        if self.reader is not None:
            return self.reader()
        if self.path:
            return Path(self.path).read_bytes()
        raise ValueError(f"{self.kind} {self.key} has no content")


@dataclass(frozen=True)
class OutgoingChangeset:
    """One atomic changeset. ``cs_id`` is chosen before upload; pushing the same id again
    is idempotent (:class:`Replay`). A group too big for one call goes as parts
    (``part`` of the group, ``last`` on the final one). ``fences``: ``{unit: fence}`` of
    units this PC holds locks on; ``release_locks``: units to release on commit."""

    cs_id: str
    base_seq: int
    items: tuple[OutgoingItem, ...]
    device: str = ""
    group: str = ""
    part: int = 1
    last: bool = True
    message: str = ""
    actor: str = "user"
    ducky: str = ""
    fences: Mapping[str, int] = field(default_factory=dict)
    release_locks: tuple[str, ...] = ()


# --------------------------------------------------------------------------- what comes in


@dataclass(frozen=True)
class IncomingItem:
    """One item version. In a pulled changeset it carries no content; :meth:`LedgerBackend.fetch`
    returns it with the plaintext in ``data`` or streamed to the temp file ``path``
    (verified; the engine removes the file when done). ``sha256`` and ``size`` are of
    the plaintext ('' / 0 when the backend doesn't know them before a fetch)."""

    kind: str
    key: str
    unit: str = ""
    op: str = "put"
    seq: int = 0
    sha256: str = ""
    size: int = 0
    by: str = ""
    at: float = 0.0
    data: bytes | None = None
    path: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> ItemId:
        return (self.kind, self.key)

    @property
    def deleted(self) -> bool:
        return self.op == "del"

    def read(self) -> bytes:
        if self.data is not None:
            return self.data
        if self.path:
            return Path(self.path).read_bytes()
        raise ValueError(f"{self.kind} {self.key} was not fetched")


@dataclass(frozen=True)
class IncomingChangeset:
    seq: int
    items: tuple[IncomingItem, ...]
    cs_id: str = ""
    by: str = ""
    device: str = ""
    at: float = 0.0
    actor: str = "user"
    ducky: str = ""
    message: str = ""
    group: str = ""
    part: int = 1
    last: bool = True


@dataclass(frozen=True)
class PullPage:
    """Changesets after ``since`` in seq order, the plugin's head and whether more follow.
    ``resync``: ``since`` is older than what the server keeps; list every item instead
    (``pull(..., full=True)``). A full listing comes back in ``items`` (each item's
    current version, deletes included) with ``after``, the cursor of the next page."""

    changesets: tuple[IncomingChangeset, ...] = ()
    head: int = 0
    more: bool = False
    resync: bool = False
    items: tuple[IncomingItem, ...] = ()
    after: str = ""


# --------------------------------------------------------------------------- locks, heads, presence


@dataclass(frozen=True)
class LockInfo:
    """A live lock. ``lease_left`` is seconds on the server clock; ``mine``: held by this
    account on this device (``device`` is the holder's device id, see the module
    docstring). ``name`` is the unit's plaintext name; ``user_name`` the holder's display
    name."""

    unit: str
    plugin: str = ""
    name: str = ""
    user: str = ""
    user_name: str = ""
    device: str = ""
    since: float = 0.0
    lease_left: float = 0.0
    fence: int = 0
    reason: str = ""
    mine: bool = False


@dataclass(frozen=True)
class LockUnit:
    unit: str
    name: str = ""


@dataclass(frozen=True)
class Granted:
    fence: int
    lease_left: float


@dataclass(frozen=True)
class Held:
    """Already held by this PC: renewed."""

    fence: int
    lease_left: float


@dataclass(frozen=True)
class Behind:
    """Someone committed to the unit after the seq this PC said it has: pull, then ask again."""

    seq: int
    by: str = ""
    at: float = 0.0


@dataclass(frozen=True)
class Heads:
    """``v2`` False: the new sync is switched off on the server. Plugins already moved to
    it are paused (read-only, "Team sync paused") until it is back; the provider keeps
    returning their ledger meanwhile."""

    epoch: str
    heads: Mapping[str, int] = field(default_factory=dict)
    importing: Mapping[str, float] = field(default_factory=dict)
    locks: tuple[LockInfo, ...] = ()
    people: tuple[Mapping[str, Any], ...] = ()
    usage: Mapping[str, Any] = field(default_factory=dict)
    v2: bool = True


@dataclass(frozen=True)
class Roster:
    """The space's live presence (each person's opened blob plus ``user``, ``user_name``,
    ``device``: the device id that beat) and its live locks."""

    people: tuple[Mapping[str, Any], ...] = ()
    locks: tuple[LockInfo, ...] = ()


@dataclass(frozen=True)
class HistoryEntry:
    """A changeset (``count`` items), or one item's version (``kind``/``key`` set)."""

    seq: int
    by: str = ""
    at: float = 0.0
    device: str = ""
    actor: str = "user"
    ducky: str = ""
    message: str = ""
    count: int = 0
    kind: str = ""
    key: str = ""
    deleted: bool = False
    size: int = 0
    sha256: str = ""
    items: tuple[ItemId, ...] = ()
    # The name of the PC ``device`` is, when the change says it ("" otherwise: core names
    # the PCs its rosters have seen).
    device_name: str = ""


@dataclass(frozen=True)
class History:
    entries: tuple[HistoryEntry, ...] = ()
    more: bool = False


@dataclass(frozen=True)
class Done:
    """Acknowledged (unlock, break, ask)."""


@dataclass(frozen=True)
class Denied:
    """Not allowed (breaking someone's live lock without the right)."""

    reason: str = ""


# --------------------------------------------------------------------------- push answers


@dataclass(frozen=True)
class Committed:
    """The changeset is ``seq``. ``items``: each item's new seq. A revert lists the items
    it had to leave out (their version is no longer kept) in ``skipped``."""

    seq: int
    items: Mapping[ItemId, int] = field(default_factory=dict)
    skipped: tuple[ItemId, ...] = ()


@dataclass(frozen=True)
class Replay:
    """This cs_id was committed before (an answer got lost) at ``seq``."""

    seq: int


@dataclass(frozen=True)
class ConflictItem:
    kind: str
    key: str
    seq: int = 0
    by: str = ""
    at: float = 0.0
    deleted: bool = False

    @property
    def id(self) -> ItemId:
        return (self.kind, self.key)


@dataclass(frozen=True)
class Conflict:
    """Items whose version on the server is newer than the change's base. ``deleted`` with
    a purged item: it is gone for good (never re-created silently)."""

    items: tuple[ConflictItem, ...]


@dataclass(frozen=True)
class Locked:
    """Units of the change under someone else's live lock. Nothing was committed."""

    units: tuple[LockInfo, ...]


@dataclass(frozen=True)
class RefusedItem:
    kind: str
    key: str
    reason: str

    @property
    def id(self) -> ItemId:
        return (self.kind, self.key)


@dataclass(frozen=True)
class Refused:
    """Items the server won't take (size, storage, permission), each with the reason.
    Nothing was committed."""

    items: tuple[RefusedItem, ...]


@dataclass(frozen=True)
class Retry:
    """Try again after ``after`` seconds (the server is busy, e.g. collecting garbage)."""

    after: float = 30.0


@dataclass(frozen=True)
class Missing:
    """Uploaded objects the server can't find (``ids``); push again to re-upload them."""

    ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Importing:
    """The plugin's data is still being moved to this sync (``pct`` done)."""

    pct: float = 0.0


@dataclass(frozen=True)
class Paused:
    """The space is paused: read-only."""


@dataclass(frozen=True)
class Offline:
    reason: str = ""


@dataclass(frozen=True)
class Error:
    reason: str = ""


PushResult = Union[Committed, Replay, Conflict, Locked, Refused, Retry, Missing, Importing, Paused, Offline, Error]
Failure = Union[Offline, Error, Paused, Importing, Retry]
LockResult = Union[Granted, Held, Behind, LockInfo]
FAILURES = (Offline, Error, Paused, Importing, Retry)


def failed(result: Any) -> bool:
    """True for an answer that says the call didn't happen (offline, error, paused...)."""
    return isinstance(result, FAILURES)


def reason_of(result: Any) -> str:
    """Words for the bar: why a call didn't go through."""
    if isinstance(result, Offline):
        return f"offline{': ' + result.reason if result.reason else ''}"
    if isinstance(result, Error):
        return result.reason or "the server said no"
    if isinstance(result, Paused):
        return "paused"
    if isinstance(result, Importing):
        return f"moving to the new sync ({int(result.pct)}%)"
    if isinstance(result, Retry):
        return f"busy, retry in {int(result.after)} s"
    if isinstance(result, Missing):
        return "an upload didn't arrive"
    return ""


TEAMMATE = "a teammate"
_USER_ID = re.compile(r"[0-9a-f]{8}(-?)[0-9a-f]{4}\1[0-9a-f]{4}\1[0-9a-f]{4}\1[0-9a-f]{12}", re.IGNORECASE)


def person(*names: Any, fallback: str = TEAMMATE) -> str:
    """Who someone is, for the bar and the drawer: the first of ``names`` (a display name,
    then the user id the server keeps) that reads as a name; ``fallback`` when none does.
    A bare user id (uuid-shaped) never shows."""
    for name in names:
        text = str(name or "").strip()
        if text and not _USER_ID.fullmatch(text):
            return text
    return fallback


@runtime_checkable
class LedgerBackend(Protocol):
    """The remote side of a space. See the module docstring for the rules."""

    def capabilities(self) -> set[str]:
        """Which optional calls work (:data:`CAPABILITIES`)."""
        ...

    def heads(self, space: str, plugins: list[str]) -> Heads | Offline | Error | Paused:
        """The space's epoch, each plugin's head seq, imports running, live locks, roster."""
        ...

    def push(self, space: str, plugin: str, changeset: OutgoingChangeset) -> PushResult:
        """Upload and commit one changeset (resuming what an earlier try uploaded)."""
        ...

    def pull(self, space: str, plugin: str, since: int, limit: int, *, full: bool = False,
             after: str = "") -> PullPage | Offline | Error | Paused | Importing:
        """Changesets after ``since`` (at most ``limit``), without content. ``full``: a page
        of every item's current version from cursor ``after`` instead (an imported item
        with ``meta["v1rev"]``)."""
        ...

    def fetch(self, space: str, plugin: str, kind: str, key: str, seq: int | None = None) -> IncomingItem | Offline | Error:
        """One item's content at ``seq`` (None: its current version), verified."""
        ...

    def history(self, space: str, plugin: str, key: ItemId | None = None, before: int | None = None,
                limit: int = 50) -> History | Offline | Error:
        """Changesets newest first, or one item's versions (``key``), before seq ``before``."""
        ...

    def revert(self, space: str, plugin: str, items: Mapping[ItemId, int] | None = None, to_seq: int | None = None,
               message: str = "", *, keys: Sequence[ItemId] | None = None) -> PushResult:
        """A new changeset pointing ``items`` back at their version at the given seq (0: back
        to before the item existed, so it is deleted), or the whole plugin as of ``to_seq``:
        each item's version then, deleted when it was made after ``to_seq``. ``keys`` with
        ``to_seq``: only those items, on the same rule (Undo). An item whose version then is
        no longer kept is left as it is and listed in :attr:`Committed.skipped`. Locks apply
        as for a push."""
        ...

    def lock(self, space: str, plugin: str, units: list[LockUnit], mode: str,
             have_seq: Mapping[str, int]) -> dict[str, LockResult] | Offline | Error | Paused:
        """Acquire or renew locks. ``have_seq``: ``{unit: seq of the last changeset touching it
        applied on this PC}``. ``atomic``: all or none."""
        ...

    def unlock(self, space: str, plugin: str, units: list[str]) -> Done | Offline | Error:
        ...

    def break_lock(self, space: str, plugin: str, unit: str) -> Done | Denied | Offline | Error:
        ...

    def ask(self, space: str, plugin: str, unit: str) -> Done | Offline | Error:
        """Ask the holder of ``unit`` to release it."""
        ...

    def beat(self, space: str, blob: dict[str, Any]) -> Roster | Offline | Error | Paused:
        """Send this PC's presence (plaintext; the backend seals it) and get the roster."""
        ...
