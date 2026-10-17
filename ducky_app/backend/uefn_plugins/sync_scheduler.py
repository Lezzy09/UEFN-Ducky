"""Background rounds for shared spaces, in the app process only.

Before, a shared space synced only while a plugin's scope bar was on screen (a round a
minute) or the Workflows view was open: an agent's edits made with the panel closed
never went out, and this PC never pulled. This daemon keeps every space in step:

- a write to a shared copy starts a round 5 s after the last write, at most one round
  per space every 30 s. Writes in any process count: the MCP bridge writes the same
  database, and ``PRAGMA data_version``, read once a second, says when anyone did;
- a round every 60 s while a linked plugin's panel is visible or the Workflows view is
  open, every 15 minutes otherwise;
- one round per linked space at start, and again when the account or the provider
  changes;
- changes queued again without a new write (Upload my copy, Retry) keep a round coming
  every 30 s while each one still sends some of them;
- after a round that failed (``error``, ``offline``, ``unavailable``) the space is tried
  again after 1 and 5 minutes, then every 15;
- at exit, :func:`flush` sends what is still queued, for at most 5 s.

Every round is wrapped in ``spaces._round_failed``: one that raises is recorded on the
space and the next tick runs. Rounds of one space never overlap, in any process: each
holds the space's round lock (:func:`run_round`). The provider decides what a round does.
Never runs in the MCP bridge (``UEFN_DUCKY_MCP_BRIDGE=1``): the app's scheduler sees the
bridge's writes.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

_log = logging.getLogger(__name__)

TICK_S = 1.0
DEBOUNCE_S = 5.0  # a round this long after the last write to a space
MIN_GAP_S = 30.0  # at most one round per space this often
ACTIVE_EVERY_S = 60.0  # while a linked plugin's panel or the Workflows view is on screen
IDLE_EVERY_S = 15 * 60.0
RETRY_AFTER_S = (60.0, 5 * 60.0, 15 * 60.0)  # after 1, 2, 3 or more failed rounds in a row
REFRESH_EVERY_S = 30.0  # links, panels and sync rows are read again at least this often,
REFRESH_MIN_S = 5.0  # and after someone else's write at most this often
FLUSH_TIMEOUT_S = 5.0
ROUND_WAIT_S = 10 * 60.0  # how long a forced round waits for a round of the same space to end
RETRY_STATES = frozenset({"error", "offline", "unavailable"})
# Access gone, or the server's copy was reset: writes there are refused, and a round
# every 15 minutes is enough to see it come back.
SLOW_STATES = frozenset({"lost", "reset"})
# Workflow docs' plugin id (owned.DOC_PLUGIN). The Workflows view reports itself as this
# plugin's panel, so panel_presence says when it is on screen.
WORKFLOWS = "ducky.automations"


def _in_bridge() -> bool:
    return os.environ.get("UEFN_DUCKY_MCP_BRIDGE") == "1"


def _try_lock(handle: Any) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def _round_lock(account: str, space: str, wait: float) -> Iterator[bool]:
    """The space's round lock: an OS file lock, so a round in the MCP bridge (a plugin
    tool asking for one) and one here never overlap, and a process that dies frees it.
    Yields False when another round still holds it after ``wait`` seconds. Before, the
    provider's lock was per process: two rounds pushed at once, and the one whose push
    went stale replaced an edit the other hadn't confirmed yet."""
    from frontend.app_paths import resolve_app_data_dir

    try:
        folder = resolve_app_data_dir() / "locks"
        folder.mkdir(parents=True, exist_ok=True)
        handle = open(folder / f"space-round-{account}-{space}.lock", "a+b")  # noqa: SIM115 — closed below
    except OSError:
        _log.debug("no round lock for %s; the round runs without it", space, exc_info=True)
        handle = None
    if handle is None:
        yield True
        return
    with handle:
        deadline = time.monotonic() + max(0.0, wait)
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.2)
        try:
            yield True
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_round(account: str, space: str, *, force: bool) -> dict[str, Any]:
    """One provider round for ``(account, space)``, holding the space's round lock: a
    forced round waits for one already running (up to :data:`ROUND_WAIT_S`), any other
    answers ``busy``. A round that raises is recorded on the space (state ``error`` and
    the provider plugin's errors) instead of escaping."""
    from backend.uefn_plugins import spaces

    try:
        with _round_lock(account, space, ROUND_WAIT_S if force else 0.0) as held:
            if not held:
                return {"state": "busy", "changed": [], "error": ""}
            return spaces.provider().sync(account, space, force=force) or {}
    except Exception as exc:  # noqa: BLE001 — any failure is the space's, never the caller's
        return spaces._round_failed({"account": account, "id": space}, exc)


def _announce(out: dict[str, Any]) -> None:
    """Open panels and scope bars refresh after a round, like a round the bar started."""
    changed = [str(p) for p in out.get("changed") or []]
    if not changed and (out.get("skipped") or out.get("state") == "busy"):
        return
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "plugin_scope_changed", "plugins": changed, "synced": True})
        if WORKFLOWS in changed:
            push_ui_event({"type": "graphs_changed"})
    except Exception:  # noqa: BLE001 — the next status read shows it anyway
        _log.debug("announcing a sync round failed", exc_info=True)


def _visible(plugin: str) -> bool:
    from backend.uefn_plugins.panel_presence import panel_state

    return bool(panel_state(plugin)["visible"])


def _plan(account: str) -> dict[str, tuple[set[str], bool, float]]:
    """``{space: (what lives there, on screen, newest unsent write)}``: spaces linked
    plugins keep their data in, spaces this account keeps workflows in (every one while
    the Workflows view is open), and any space with changes still to send."""
    from backend.store.repos import plugin_data as repo
    from backend.store.switch import use_db
    from backend.uefn_plugins import scopes

    held: dict[str, set[str]] = {}
    for plugin, space in repo.links(account).items():
        if scopes.valid_space_id(space) and scopes.sharing_allowed(plugin):
            held.setdefault(space, set()).add(plugin)
    view = False
    if use_db("automations"):
        from backend.store.repos import workflows as runtime

        view = _visible(WORKFLOWS)
        for space in runtime.synced_spaces(account):
            if scopes.valid_space_id(space) and (view or repo.has_rows(account, WORKFLOWS, space)):
                held.setdefault(space, set()).add(WORKFLOWS)
    unsent = {
        space: at for space, at in repo.unsent_spaces(account).items()
        if scopes.valid_space_id(space) and not space.startswith(scopes.SANDBOX_PREFIX)
    }
    out: dict[str, tuple[set[str], bool, float]] = {}
    for space in set(held) | set(unsent):
        plugins = held.get(space, set())
        active = any(view if plugin == WORKFLOWS else _visible(plugin) for plugin in plugins)
        out[space] = (plugins, active, unsent.get(space, 0.0))
    return out


@dataclass
class _Space:
    plugins: set[str] = field(default_factory=set)  # linked plugin ids, WORKFLOWS for workflows
    active: bool = False  # one of them is on screen
    state: str = "ok"  # the sync row's state (the provider's last word)
    called_at: float = 0.0  # when the provider last started a round for it, in any process
    written: float = 0.0  # newest change still to send (0: none)
    started: float = 0.0  # when this scheduler last started a round for it
    sent: float = 0.0  # start of its last round the provider ran (changes before it went with it)
    fails: int = 0  # failed rounds in a row
    owed: bool = False  # the round at start is still to run
    left: int = 0  # changes still to send at the last look
    looked: float = 0.0  # called_at at the last look
    more: bool = False  # rounds since the last look sent some of them, and some are left
    running: bool = False


class Scheduler:
    """The cadence above. :meth:`tick` is one look (the daemon calls it every second);
    tests drive it with their own clock, and ``spawn`` runs a round (a thread here)."""

    def __init__(self, *, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.clock = clock
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, name="space-sync-round", daemon=True).start())
        self.spaces: dict[str, _Space] = {}
        self._lock = threading.Lock()
        self._who = ("", "")  # (account, provider plugin) the spaces belong to
        self._version: int | None = None
        self._refreshed = float("-inf")
        self._stale = True

    def tick(self, now: float | None = None) -> list[str]:
        """Start every round that is due. Returns their spaces."""
        from backend.store import db
        from backend.uefn_plugins import spaces

        now = self.clock() if now is None else now
        version = db.data_version(db.connect())
        if version != self._version:
            self._version, self._stale = version, True
        provider = spaces.provider_plugin() if spaces.has_provider() else ""
        since = now - self._refreshed
        if provider != self._who[1] or since >= REFRESH_EVERY_S or (self._stale and since >= REFRESH_MIN_S):
            self._refresh(now, provider)
        due: list[tuple[str, bool]] = []
        with self._lock:
            account = self._who[0]
            for space, rec in self.spaces.items():
                force = self._due(rec, now)
                if force is not None:
                    rec.running, rec.owed, rec.started = True, False, now
                    due.append((space, force))
        for space, force in due:
            self.spawn(lambda space=space, force=force: self._round(account, space, force, now))
        return [space for space, _ in due]

    def _refresh(self, now: float, provider: str) -> None:
        from backend.store.repos import plugin_data as repo
        from backend.uefn_plugins import scopes

        self._refreshed, self._stale = now, False
        account = scopes.account_id() if provider else scopes.LOCAL
        found = {} if account == scopes.LOCAL else _plan(account)
        rows = {space: repo.sync_get(account, space) for space in found}
        left = {space: repo.count_dirty(account, space) for space, (_, _, written) in found.items() if written}
        with self._lock:
            fresh = (account, provider) != self._who
            if fresh:
                self._who, self.spaces = (account, provider), {}
            for space, (plugins, active, written) in found.items():
                rec = self.spaces.get(space)
                if rec is None:
                    rec = self.spaces[space] = _Space(owed=fresh and bool(plugins))
                rec.plugins, rec.active, rec.written = plugins, active, written
                rec.state, rec.called_at = str(rows[space]["state"] or "ok"), float(rows[space]["called_at"] or 0.0)
                if rec.state not in RETRY_STATES and rec.called_at > rec.started:
                    rec.fails = 0  # a round started elsewhere (the scope bar, a Save) worked since
                # Changes queued again carry no new write (Upload my copy, Retry), and the
                # provider sends a batch per round: while the rounds since the last look,
                # started anywhere, still sent some, the next one comes as soon as allowed.
                # One that sent nothing (rows it keeps skipping) ends it, so it can't loop.
                # A backlog seen for the first time gets one more round to find out.
                count = left.get(space, 0)
                if not count:
                    rec.more = False
                elif rec.called_at > rec.looked:
                    rec.more = not rec.left or count < rec.left
                rec.left, rec.looked = count, rec.called_at
            for space in [s for s, rec in self.spaces.items() if s not in found and not rec.running]:
                del self.spaces[space]

    @staticmethod
    def _due(rec: _Space, now: float) -> bool | None:
        """None: not yet. Otherwise the round's ``force``: True for changes to send (it
        must beat the provider's own minute limit), False for a pull it may skip."""
        if rec.running:
            return None
        unsent = rec.written > max(rec.sent, rec.called_at) or rec.more
        if rec.owed:
            return unsent
        last = max(rec.started, rec.called_at)
        failing = rec.fails > 0 or rec.state in RETRY_STATES
        wait = RETRY_AFTER_S[min(max(rec.fails, 1), len(RETRY_AFTER_S)) - 1] if failing else 0.0
        slow = rec.state in SLOW_STATES
        if unsent and not slow and now >= max(rec.written + DEBOUNCE_S, last + MIN_GAP_S, last + wait):
            return True
        every = IDLE_EVERY_S if slow else wait or (ACTIVE_EVERY_S if rec.active else IDLE_EVERY_S)
        return False if now >= last + every else None

    def _round(self, account: str, space: str, force: bool, started: float) -> None:
        from backend.store.repos import plugin_data as repo

        out = run_round(account, space, force=force)
        state = str(out.get("state") or "")
        ran = state != "busy" and not out.get("skipped")  # busy: another round holds the space
        try:
            called_at = float(repo.sync_get(account, space)["called_at"] or 0.0)
        except Exception:  # noqa: BLE001 — the next refresh reads it
            called_at = 0.0
        with self._lock:
            rec = self.spaces.get(space) if self._who[0] == account else None
            if rec is not None:
                rec.running = False
                rec.called_at = max(rec.called_at, called_at)
                if ran:
                    rec.sent = started
                    rec.fails = rec.fails + 1 if state in RETRY_STATES else 0
                    rec.state = state or rec.state
            self._stale = True
        _announce(out)


def flush(timeout: float = FLUSH_TIMEOUT_S) -> int:
    """At exit (``shutdown.hard_exit``): one round for every space with changes still to
    send, all at once, for at most ``timeout`` seconds in all; rounds still running then
    are left behind. Returns how many started. Never raises."""
    deadline = time.monotonic() + max(0.0, timeout)
    try:
        from backend.store.repos import plugin_data as repo
        from backend.uefn_plugins import scopes, spaces

        if _in_bridge() or not spaces.has_provider():
            return 0
        account = scopes.account_id()
        if account == scopes.LOCAL:
            return 0
        targets = [
            space for space in sorted(repo.unsent_spaces(account))
            if scopes.valid_space_id(space) and not space.startswith(scopes.SANDBOX_PREFIX)
            and repo.sync_get(account, space)["state"] not in SLOW_STATES
        ]
    except Exception:  # noqa: BLE001 — exit goes on
        _log.debug("sync flush skipped", exc_info=True)
        return 0
    workers = [
        threading.Thread(target=run_round, args=(account, space), kwargs={"force": True}, name="space-sync-flush",
                         daemon=True)
        for space in targets
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(max(0.0, deadline - time.monotonic()))
    return len(workers)


_START_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def start() -> bool:
    """Start the daemon (app process only). False in the MCP bridge, or when it runs."""
    global _THREAD
    if _in_bridge():
        return False
    with _START_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, args=(Scheduler(),), name="space-sync-scheduler", daemon=True)
        _THREAD.start()
    return True


def stop() -> None:
    _STOP.set()


def _loop(scheduler: Scheduler) -> None:
    while not _STOP.wait(TICK_S):
        try:
            scheduler.tick()
        except Exception:  # noqa: BLE001 — a bad look never stops the next one
            _log.debug("space sync tick failed", exc_info=True)
