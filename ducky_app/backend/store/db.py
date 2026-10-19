"""``ducky.db`` — open, configure, migrate, snapshot (ADR 0003).

One connection per thread, WAL, ``busy_timeout``; writers use ``BEGIN
IMMEDIATE`` through :func:`write_txn`. Schema version is ``PRAGMA
user_version``; migrations are numbered SQL files under ``migrations/`` applied
forward-only, one transaction each. A database written by a newer app is
refused, never downgraded.

This module is the only place in the tree allowed to import :mod:`sqlite3`
(``test_fitness.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Iterator

DB_NAME = "ducky.db"
SIDECAR_NAMES = (DB_NAME + "-wal", DB_NAME + "-shm")
SNAPSHOT_DIR_NAME = "snapshots"
# Held by a process while it opens ducky.db for the first time (staged restore, WAL
# switch, migrations), so the app and its IDE/agent bridges never do those at once.
OPEN_LOCK_NAME = DB_NAME + ".open-lock"
OPEN_LOCK_WAIT_S = 120.0  # a migration may first copy a large database (pre-migrate snapshot)
KEEP_SNAPSHOTS = 3
BUSY_TIMEOUT_MS = 5000
# ducky.db-wal is reused, never shrunk, while any process keeps the file open; one big
# transaction (a re-index, an import) left it at its high-water mark for good.
WAL_SIZE_LIMIT = 64 * 1024 * 1024
# Connections of finished threads kept open for the next new thread to adopt.
_IDLE_KEEP = 4
# Page cache per connection, KiB. Worker threads get a small one: each kept its
# own copy of every page it read, so the same chats sat in memory once per thread.
_MAIN_CACHE_KIB = 32768
_WORKER_CACHE_KIB = 2048

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

REQUIRED_COMPILE_OPTIONS = ("ENABLE_FTS5", "ENABLE_JSON1")
# JSON1 is built in unconditionally from SQLite 3.38 and no longer listed as a
# compile option; we probe json_extract() directly instead of the flag.


class StoreError(RuntimeError):
    """Raised for refusals: UNC path, newer schema, failed integrity."""


class NewerSchemaError(StoreError):
    pass


class UnsupportedFilesystemError(StoreError):
    pass


_thread_local = threading.local()
_guard = threading.Lock()
_log = logging.getLogger("uefn_ducky.store")
_migrated: set[str] = set()
_conn_keys: dict[str, str] = {}  # str(path) -> resolved connection-cache key
_owned_lock = threading.Lock()
_owned: list[tuple[threading.Thread, str, sqlite3.Connection]] = []  # (owner, key, conn)


# --------------------------------------------------------------------------- paths


def app_root() -> Path:
    from frontend.app_paths import resolve_app_data_dir

    return resolve_app_data_dir()


def db_path(root: Path | None = None) -> Path:
    return (root or app_root()) / DB_NAME


def snapshot_dir(root: Path | None = None) -> Path:
    return (root or app_root()) / SNAPSHOT_DIR_NAME


def _refuse_network_path(path: Path) -> None:
    s = str(path)
    if s.startswith("\\\\") or s.startswith("//"):
        raise UnsupportedFilesystemError(
            f"ducky.db cannot live on a network path ({s}); WAL mode needs a local disk."
        )


# --------------------------------------------------------------------------- connect


RESTORE_PENDING_NAME = DB_NAME + ".restore-pending"


def _apply_pending_restore(path: Path) -> None:
    """Settings → Database → Restore stages a snapshot as ``ducky.db.restore-pending``;
    the first process to open the store after that swaps it in. If another
    process still holds the live file the swap fails and stays pending."""
    pending = path.parent / RESTORE_PENDING_NAME
    if not pending.is_file():
        return
    try:
        backup = path.parent / f"{DB_NAME}.replaced-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        n = 1
        while backup.exists() or backup.with_name(backup.name + "-wal").exists():
            n += 1
            backup = backup.with_name(f"{backup.name.rsplit('~', 1)[0]}~{n}")
    except OSError as exc:
        _log.warning("staged ducky.db restore could not be applied yet: %s", exc)
        return
    # All or nothing. ducky.db goes first (that rename fails while any connection holds
    # it); the old WAL travels with it (the app is often killed without a checkpoint, so
    # the WAL holds the latest commits and SQLite replays it when the backup is opened).
    # If any step fails, everything moved is put back: SQLite deletes a WAL left beside a
    # missing or empty ducky.db, so a half-done swap would lose those commits.
    moved: list[tuple[Path, Path]] = []
    try:
        for name in (DB_NAME, *SIDECAR_NAMES):
            src = path.parent / name
            if src.exists():
                dst = backup.with_name(backup.name + name[len(DB_NAME):])
                src.rename(dst)
                moved.append((src, dst))
        pending.replace(path)
        _log.warning("ducky.db restored from a staged snapshot (previous file kept as %s)", backup.name)
    except OSError as exc:
        for src, dst in reversed(moved):
            try:
                dst.rename(src)
            except OSError:
                _log.error("could not put %s back after a failed restore swap", src.name, exc_info=True)
        _log.warning("staged ducky.db restore could not be applied yet: %s", exc)


VACUUM_PENDING_NAME = DB_NAME + ".vacuum-pending"
# Starts that find ducky.db open in another process before the rebuild runs anyway.
VACUUM_MAX_WAITS = 5
VACUUM_MAX_FAILURES = 3


def request_vacuum(root: Path | None = None) -> None:
    """Rebuild ducky.db at the next start (:func:`_vacuum_if_requested`): every value of an
    account is sealed now, and only a rebuild drops the plaintext the file still holds in
    free pages and page slack from before."""
    marker = db_path(root).parent / VACUUM_PENDING_NAME
    if not marker.is_file():
        marker.write_text(json.dumps({"waits": 0, "failures": 0}), encoding="utf-8")


def _held_elsewhere(path: Path) -> bool:
    """True while another process has ``path`` open (Windows: it can't be opened unshared).
    Other systems have no such test: False."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, open_existing, normal = 0x80000000, 3, 0x80
    handle = k32.CreateFileW(str(path), generic_read, 0, None, open_existing, normal, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return ctypes.get_last_error() == 32  # ERROR_SHARING_VIOLATION
    k32.CloseHandle(handle)
    return False


def _vacuum_if_requested(path: Path) -> None:
    """First open of a start, under the open lock: rebuild ducky.db once if
    :func:`request_vacuum` asked for it. Waits (a few starts) for no other process to hold
    the file, since the rebuild holds the write lock throughout. A failure keeps the
    original whole (VACUUM is one transaction) and is tried again; never raises."""
    marker = path.parent / VACUUM_PENDING_NAME
    if not marker.is_file():
        return
    try:
        state = json.loads(marker.read_text(encoding="utf-8") or "{}")
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    waits, failures = int(state.get("waits") or 0), int(state.get("failures") or 0)

    def _note(**changes: int) -> None:
        try:
            marker.write_text(json.dumps({"waits": waits, "failures": failures, **changes}), encoding="utf-8")
        except OSError:
            pass

    try:
        if not path.is_file():
            marker.unlink(missing_ok=True)
            return
        if _held_elsewhere(path) and waits < VACUUM_MAX_WAITS:
            _note(waits=waits + 1)
            _log.info("ducky.db rebuild waits for the next start: another process has it open")
            return
        import tempfile

        size = path.stat().st_size
        wal = path.with_name(path.name + "-wal")
        size += wal.stat().st_size if wal.is_file() else 0
        need = int(size * 1.2) + 64 * 1024 * 1024
        if min(shutil.disk_usage(path.parent).free, shutil.disk_usage(tempfile.gettempdir()).free) < need:
            _log.warning("ducky.db rebuild waits: not enough free disk space (%d MB needed)", need >> 20)
            return
        started = time.monotonic()
        conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        try:
            conn.execute("PRAGMA secure_delete=ON")
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        marker.unlink(missing_ok=True)
        _log.info("ducky.db rebuilt in %.1f s: no plaintext from before is left in it", time.monotonic() - started)
    except Exception:  # noqa: BLE001 — never in the way of opening the store
        _log.warning("ducky.db rebuild failed; tried again next start", exc_info=True)
        if failures + 1 >= VACUUM_MAX_FAILURES:
            marker.unlink(missing_ok=True)
        else:
            _note(failures=failures + 1)


@contextmanager
def _first_open_lock(folder: Path, wait_s: float = OPEN_LOCK_WAIT_S) -> Iterator[None]:
    """Hold ``ducky.db.open-lock`` (an OS file lock, released if the process dies).

    The app and every IDE/agent bridge open ducky.db at boot. Without this, two first
    opens at once raced on the WAL switch ("database is locked" at once: SQLite never
    waits on a read-to-write lock upgrade), a staged restore could be applied by two
    processes and lose the previous file, and each upgrading process took its own
    pre-migrate snapshot, pushing older restore points out.
    """
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(folder / OPEN_LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + wait_s
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise sqlite3.OperationalError(
                        "database is locked: another UEFN Ducky process is still opening ducky.db"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _is_busy(exc: BaseException) -> bool:
    """SQLITE_BUSY / SQLITE_LOCKED: another connection holds the lock (not damage)."""
    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or "database is locked" in str(exc)


DatabaseError = sqlite3.DatabaseError


def sqlite_library_version() -> str:
    return sqlite3.sqlite_version


def check_db_file(path: Path) -> str:
    """``PRAGMA integrity_check`` on a database file that is not the live store (read-only).
    A backup sealed for an account is opened to a copy first (``sealed_files``)."""
    from backend.store import sealed_files

    if sealed_files.is_sealed_file(path):
        with _opened_copy(path) as plain:
            return check_db_file(plain)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "no result"
    finally:
        conn.close()


@contextmanager
def _opened_copy(path: Path) -> Iterator[Path]:
    """A plain copy of sealed backup ``path`` beside it, removed afterwards."""
    from backend.store import sealed_files

    plain = path.with_name(f".{path.stem}.{os.getpid()}.check.db")
    try:
        sealed_files.open_to(path, plain)
        yield plain
    finally:
        for name in (plain.name, plain.name + "-wal", plain.name + "-shm", plain.name + "-journal"):
            try:
                (plain.parent / name).unlink(missing_ok=True)
            except OSError:
                pass


def copy_backup(src: Path, dest: Path) -> None:
    """Put backup ``src`` at ``dest`` as a plain database (opened if it is sealed: raises
    ``sealed_files.WrongAccount`` or ``data_crypto.Locked`` when it can't be opened here)."""
    from backend.store import sealed_files

    if sealed_files.is_sealed_file(src):
        sealed_files.open_to(src, dest)
    else:
        shutil.copy2(src, dest)


def record_integrity(conn: sqlite3.Connection, result: str) -> None:
    with write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value, updated) VALUES ('last_integrity', ?, ?)",
            (json.dumps({"result": result, "ts": time.time()}), time.time()),
        )


def _refuse_real_appdata_under_pytest(path: Path) -> None:
    """A test that escapes the conftest redirect must fail loudly instead of
    migrating, importing into, or pruning the developer's live database.
    ``DUCKY_TESTS_REAL_APPDATA=1`` opts out deliberately.

    Any process running pytest counts, not only a test's run phase: PYTEST_CURRENT_TEST is
    unset while test modules are imported and collected, and a plugin repo's tests (no app
    conftest redirect) migrated the owner's live ducky.db past the installed app's schema
    that way on Oct 16 2026, so the installed app could no longer open it."""
    under_pytest = (
        "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ or "pytest" in sys.modules
    )
    if not under_pytest or os.environ.get("DUCKY_TESTS_REAL_APPDATA") == "1":
        return
    try:
        real = (Path.home() / "AppData" / "Local" / "UEFN-Ducky").resolve()
        here = path.parent.resolve() if path.parent.exists() else path.parent
    except OSError:
        return
    if here == real:
        raise RuntimeError(
            f"refusing to open the real ducky.db ({path}) from a test; run pytest from the repo root "
            "so conftest.py redirects LOCALAPPDATA, or set DUCKY_TESTS_REAL_APPDATA=1 on purpose"
        )


def connect(root: Path | None = None) -> sqlite3.Connection:
    """Return this thread's connection to ``ducky.db``, migrating on first open.

    Connections are cached per thread and per resolved path, so a test that
    repoints ``LOCALAPPDATA`` gets a fresh database.

    The key has to be the *real* path so two spellings of one database share a
    connection — but resolving it is three filesystem syscalls (~0.5 ms on
    Windows), and they used to run ahead of the cache lookup on every call, so
    every store read in the app paid for them. The resolved key is remembered
    per spelling instead: a directory's real path does not change under a
    running process, and a test that repoints ``LOCALAPPDATA`` produces a
    different spelling and so resolves afresh.
    """
    path = db_path(root)
    raw = str(path)
    cache: dict[str, sqlite3.Connection] = getattr(_thread_local, "conns", None) or {}
    key = _conn_keys.get(raw)
    if key is not None:
        conn = cache.get(key)
        if conn is not None:
            return conn

    _refuse_network_path(path)
    _refuse_real_appdata_under_pytest(path)
    # Resolve only after the guards have passed and the directory exists, so the
    # key is the settled one from the very first call. Keying the first call on
    # the pre-mkdir spelling and later calls on the resolved one opened a second
    # connection to the same file.
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    _conn_keys[raw] = key
    conn = cache.get(key)
    if conn is not None:
        return conn
    conn = _reclaim_finished(key if key in _migrated else None)
    if conn is not None:
        cache[key] = conn
        _thread_local.conns = cache
        return conn
    with _guard:
        # This process's first open of the file (staged restore, WAL switch, migrations)
        # runs under the cross-process open lock; later connections only configure.
        first = key not in _migrated
        with _first_open_lock(path.parent) if first else nullcontext():
            if first:
                _apply_pending_restore(path)
                _vacuum_if_requested(path)
            # check_same_thread=False only so a finished thread's connection can be
            # closed or handed to the next new thread; each connection still has one
            # owning thread at a time.
            conn = sqlite3.connect(
                str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            if os.environ.get("DUCKY_DB_TRACE"):
                _install_trace(conn, path)
            try:
                _configure(conn)
                if first:
                    migrate(conn)
                    _migrated.add(key)
            except BaseException:
                conn.close()  # never leave a corrupt file held open (restore must rename it)
                raise
    cache[key] = conn
    _thread_local.conns = cache
    with _owned_lock:
        _owned.append((threading.current_thread(), key, conn))
    return conn


def _thread_alive(thread: threading.Thread) -> bool:
    try:
        return thread.is_alive()
    except RuntimeError:  # a finished thread Python did not start (dummy thread)
        return False


def _reusable(conn: sqlite3.Connection) -> bool:
    try:
        return not conn.in_transaction
    except sqlite3.ProgrammingError:  # already closed
        return False


def _close_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _reclaim_finished(key: str | None, *, keep: int = _IDLE_KEEP) -> sqlite3.Connection | None:
    """Close or reuse the connections of threads that have finished.

    A thread's connection is never closed when the thread ends, and it sits in
    a reference cycle, so it stayed open (three file handles plus its page
    cache) until a full garbage collection. Panel requests, pywebview calls and
    model warms each run on a new thread, so an idle panel piled up hundreds an
    hour, and each new thread paid for a fresh open and PRAGMA setup.

    Returns a finished thread's connection to *key*, now owned by the calling
    thread, when one is free. Up to *keep* others stay open for the next new
    thread; the rest, and any left mid-transaction, are closed.
    """
    me = threading.current_thread()
    picked: sqlite3.Connection | None = None
    stale: list[sqlite3.Connection] = []
    with _owned_lock:
        live: list[tuple[threading.Thread, str, sqlite3.Connection]] = []
        idle: list[tuple[threading.Thread, str, sqlite3.Connection]] = []
        for entry in _owned:
            if _thread_alive(entry[0]):
                live.append(entry)
            elif _reusable(entry[2]):
                idle.append(entry)
            else:
                stale.append(entry[2])
        for i in range(len(idle) - 1, -1, -1):
            if key is not None and idle[i][1] == key:
                picked = idle.pop(i)[2]
                live.append((me, key, picked))
                break
        cut = max(len(idle) - keep, 0)
        stale.extend(entry[2] for entry in idle[:cut])
        _owned[:] = live + idle[cut:]
    for conn in stale:
        _close_quietly(conn)
    return picked


def _install_trace(conn: sqlite3.Connection, path: Path) -> None:
    """DUCKY_DB_TRACE=1: print every mutating statement with its thread (diagnostics)."""
    import sys

    def _trace(sql: str) -> None:
        head = sql.lstrip()[:6].upper()
        if head.startswith(("INSERT", "UPDATE", "DELETE")):
            line = f"[ducky.db {threading.current_thread().name} {path.parent.parent.name}] {sql[:160]}"
            sys.stderr.write(line + chr(10))

    conn.set_trace_callback(_trace)


def _configure(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    # Switching to WAL upgrades a read lock to a write lock, and SQLite never runs the
    # busy handler for that upgrade: it fails at once ("database is locked") while
    # another connection holds the file. The file stays WAL once set, so only a file
    # that is not (new, or put back by a restore) is switched, and the switch is retried.
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000

    def _mode() -> str:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    while _mode() != "wal":
        try:
            if str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal":
                break
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc):
                raise
        if time.monotonic() > deadline:
            raise sqlite3.OperationalError("database is locked: ducky.db could not be switched to WAL")
        time.sleep(0.02)
    conn.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT}")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    main = threading.current_thread() is threading.main_thread()
    conn.execute(f"PRAGMA cache_size=-{_MAIN_CACHE_KIB if main else _WORKER_CACHE_KIB}")
    assert_capabilities(conn)


def assert_capabilities(conn: sqlite3.Connection) -> None:
    opts = {r[0] for r in conn.execute("PRAGMA compile_options")}
    if "ENABLE_FTS5" not in opts:
        raise StoreError("this SQLite build lacks FTS5; chat and memory search need it")
    try:
        conn.execute("SELECT json_extract('{\"a\":1}', '$.a')").fetchone()
    except sqlite3.OperationalError as exc:  # pragma: no cover - defensive
        raise StoreError("this SQLite build lacks JSON functions") from exc


def close_thread_connections() -> None:
    cache: dict[str, sqlite3.Connection] = getattr(_thread_local, "conns", None) or {}
    closing = {id(conn) for conn in cache.values()}
    with _owned_lock:
        _owned[:] = [entry for entry in _owned if id(entry[2]) not in closing]
    for conn in cache.values():
        try:
            # Drop the WAL while we still own it. Closing alone leaves ducky.db-wal
            # locked on Windows long enough for the next unlink/replace to fail.
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    _thread_local.conns = {}


def reset_for_tests() -> None:
    """Drop cached connections and the migrated-path memo (tests only)."""
    close_thread_connections()
    _reclaim_finished(None, keep=0)
    with _guard:
        _migrated.clear()
        _conn_keys.clear()


# --------------------------------------------------------------------------- transactions


@contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; rolls back on any exception.

    Never hold one of these across an HTTP, LLM or listener call.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def data_version(conn: sqlite3.Connection) -> int:
    """Changes whenever another connection commits; cheap cache revalidation."""
    return int(conn.execute("PRAGMA data_version").fetchone()[0])


# --------------------------------------------------------------------------- migrations


def migration_files() -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = _MIGRATION_RE.match(p.name)
        if not m:
            raise StoreError(f"bad migration filename: {p.name}")
        out.append((int(m.group(1)), p))
    nums = [n for n, _ in out]
    if nums != list(range(1, len(nums) + 1)):
        raise StoreError(f"migrations must be numbered 1..N without gaps, got {nums}")
    return out


def head_version() -> int:
    files = migration_files()
    return files[-1][0] if files else 0


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations forward. Returns the resulting ``user_version``."""
    current = user_version(conn)
    head = head_version()
    if current > head:
        raise NewerSchemaError(
            f"ducky.db is at schema {current} but this app knows up to {head}; "
            "it was written by a newer UEFN-Ducky. Update the app instead of downgrading."
        )
    if current == head:
        return current
    if current > 0:
        _refuse_source_upgrade_of_real_db(conn, current, head)
    if current > 0:
        # On the connection we already hold: snapshot() would re-enter connect()
        # and deadlock on _guard (1.2.90 hung every upgraded panel at boot).
        try:
            _pre_migrate_copy(conn, current)
        except Exception:
            pass
    for number, path in migration_files():
        if number <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Another process opening the same file may have applied this step while we
            # waited for the write lock; re-running it would fail (ALTER TABLE ADD COLUMN).
            if user_version(conn) < number:
                # Not executescript(): it would COMMIT behind our back.
                for statement in _split_statements(sql):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version={number}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        current = number
    return current


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into statements; ``sqlite3.complete_statement`` aware."""
    out: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if sqlite3.complete_statement(candidate):
            out.append(candidate.strip())
            buf = []
    if "".join(buf).strip():
        raise StoreError("migration ends with an incomplete statement")
    return out


# --------------------------------------------------------------------------- health


def integrity_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no result"


SNAPSHOT_FINGERPRINT_KEY = "snapshot_fingerprint"
# Caches, logs and bookkeeping change on their own all day; a change there alone
# is no reason for another copy of the database.
_FINGERPRINT_SKIP = frozenset({
    "meta", "cache_docs", "events", "usage_calls", "verse_diagnostics", "digest_files", "digest_lines",
    "watch_index", "workspace_state", "captures", "scope_sync",
})


def data_fingerprint(conn: sqlite3.Connection) -> str:
    """Row count, highest rowid and newest ``updated`` of every table holding the
    user's data, hashed. Equal fingerprints mean no row was added, removed or
    stamped as updated in between; search indexes and caches are left out."""
    tables = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    virtual = [str(name) for name, sql in tables if str(sql or "").upper().startswith("CREATE VIRTUAL TABLE")]
    summary: list[list[object]] = []
    for name, sql in tables:
        name = str(name)
        if name in _FINGERPRINT_SKIP or any(name == v or name.startswith(v + "_") for v in virtual):
            continue
        columns = {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{name}")')}
        exprs = ["count(*)"]
        if "WITHOUT ROWID" not in str(sql or "").upper():
            exprs.append("max(rowid)")
        if "updated" in columns:
            exprs.append("max(updated)")
        summary.append([name, *conn.execute(f'SELECT {", ".join(exprs)} FROM "{name}"').fetchone()])
    return hashlib.sha256(json.dumps(summary, default=str).encode("utf-8")).hexdigest()


def snapshot(root: Path | None = None, *, label: str = "") -> Path:
    """``VACUUM INTO`` a consistent copy under ``snapshots/``; keeps the newest N.

    Records the data fingerprint the copy was taken at (taken just before, so a
    write landing in between only makes the next check see a change)."""
    root = root or app_root()
    conn = connect(root)
    fingerprint = data_fingerprint(conn)
    target = _vacuum_into(conn, root, label=label)
    with write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value, updated) VALUES (?, ?, ?)",
            (SNAPSHOT_FINGERPRINT_KEY, json.dumps({"name": target.name, "fingerprint": fingerprint}), time.time()),
        )
    return target


def unchanged_since_snapshot(conn: sqlite3.Connection, newest: Path) -> bool:
    """True when *newest* is the copy the last fingerprint was recorded for and the data still matches it."""
    row = conn.execute("SELECT value FROM meta WHERE key=?", (SNAPSHOT_FINGERPRINT_KEY,)).fetchone()
    if row is None:
        return False
    try:
        saved = json.loads(row[0])
    except ValueError:
        return False
    if not isinstance(saved, dict) or saved.get("name") != newest.name:
        return False
    return saved.get("fingerprint") == data_fingerprint(conn)


def _refuse_source_upgrade_of_real_db(conn: sqlite3.Connection, current: int, head: int) -> None:
    """A source checkout (a script, a dev run, a plugin's tests) must not upgrade the
    person's real ducky.db past the installed app's schema: the installed app then
    refuses the file ("written by a newer UEFN-Ducky") on its next start, and so does
    every IDE bridge it launches. That happened on Oct 16 2026 (schema 15 -> 18). Built
    apps upgrade as always; ``DUCKY_DEV_MIGRATE_REAL_DB=1`` allows it on purpose."""
    if getattr(sys, "frozen", False) or os.environ.get("DUCKY_DEV_MIGRATE_REAL_DB") == "1":
        return
    try:
        here = Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent.resolve()
        real = (Path.home() / "AppData" / "Local" / "UEFN-Ducky").resolve()
    except OSError:
        return
    if here == real:
        raise StoreError(
            f"refusing to upgrade the real ducky.db from schema {current} to {head} from a source "
            "checkout: the installed UEFN Ducky could no longer open it. Point LOCALAPPDATA at a "
            "copy, or set DUCKY_DEV_MIGRATE_REAL_DB=1 to do it on purpose."
        )


_premigrate_done: set[tuple[str, int]] = set()


def _pre_migrate_copy(conn: sqlite3.Connection, current: int) -> None:
    """One copy of the database before an upgrade from schema ``current``.

    A first open that fails (busy) is retried, and the next process to take the open
    lock migrates too: each used to add another copy of the same data, and keeping
    three snapshots pushed every older restore point out. A recent copy for this
    schema, made by this process or another, is reused.
    """
    folder = Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent
    label = f"pre-migrate-v{current}"
    mark = (str(folder), current)
    if mark in _premigrate_done:
        return
    recent = [
        p for p in snapshot_dir(folder).glob(f"ducky-*-{label}*.db")
        if time.time() - p.stat().st_mtime < 2 * OPEN_LOCK_WAIT_S
    ]
    if not recent:
        _vacuum_into(conn, folder, label=label)
    _premigrate_done.add(mark)


def _vacuum_into(conn: sqlite3.Connection, root: Path, *, label: str = "") -> Path:
    target_dir = snapshot_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    target = target_dir / f"ducky-{stamp}{suffix}.db"
    n = 1
    while target.exists():
        n += 1
        target = target_dir / f"ducky-{stamp}{suffix}-{n}.db"
    conn.execute("VACUUM INTO ?", (str(target),))
    _prune_snapshots(target_dir)
    return target


def _prune_snapshots(target_dir: Path) -> None:
    files = sorted(target_dir.glob("ducky-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_SNAPSHOTS:]:
        try:
            old.unlink()
        except OSError:
            pass


def newest_snapshot(root: Path | None = None) -> Path | None:
    d = snapshot_dir(root)
    if not d.is_dir():
        return None
    files = sorted(d.glob("ducky-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def restore_snapshot(root: Path | None = None) -> Path:
    """Replace a corrupt ``ducky.db`` with the newest snapshot it can open. Loud on failure.

    A snapshot sealed for an account (made before its chats were sealed) needs that
    account's keys, which a corrupt database may not give: plain snapshots go first,
    newest first, and sealed ones only after them."""
    from backend.store import sealed_files

    root = root or app_root()
    d = snapshot_dir(root)
    files = sorted(d.glob("ducky-*.db"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    if not files:
        raise StoreError("ducky.db failed its integrity check and no snapshot exists to restore")
    files.sort(key=sealed_files.is_sealed_file)  # stable: plain ones first, each group newest first
    reset_for_tests()
    dest = db_path(root)
    with _first_open_lock(root):  # no other process may be mid-first-open while the file is swapped
        moved: list[tuple[Path, Path]] = []
        for name in (DB_NAME, *SIDECAR_NAMES):
            p = root / name
            if p.exists():
                p.replace(root / (name + ".corrupt"))
                moved.append((root / (name + ".corrupt"), p))
        for src in files:
            try:
                copy_backup(src, dest)
                return src
            except Exception:  # noqa: BLE001 — a sealed one locked here: try the next one
                _log.warning("snapshot %s could not be restored", src.name, exc_info=True)
        for corrupt, original in moved:  # nothing could be restored: leave things as found
            corrupt.replace(original)
    raise StoreError("ducky.db failed its integrity check and no snapshot here can be opened")


def open_checked(root: Path | None = None) -> sqlite3.Connection:
    """Boot-time open: integrity check, restore from snapshot if it fails.

    A lock held by another process ("database is locked") is not damage: it is retried
    and then raised, never answered by restoring an older snapshot over live data.
    """
    root = root or app_root()
    result = ""
    for attempt in range(4):
        try:
            conn = connect(root)
            result = integrity_check(conn)
            break
        except sqlite3.DatabaseError as exc:
            if not _is_busy(exc):
                result = f"error: {exc}"
                break
            if attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))
    if result == "ok":
        return conn
    restored = restore_snapshot(root)
    conn = connect(root)
    if integrity_check(conn) != "ok":
        raise StoreError(f"ducky.db is corrupt and the snapshot {restored.name} is too")
    _record_restore(conn, restored, result)
    return conn


def _record_restore(conn: sqlite3.Connection, restored: Path, why: str) -> None:
    with write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value, updated) VALUES ('last_restore', ?, ?)",
            (f"{restored.name}: {why}", time.time()),
        )


def is_store_file(name: str) -> bool:
    """True for the DB, its sidecars and the snapshots dir (AppData maintenance)."""
    return name in (DB_NAME, *SIDECAR_NAMES, SNAPSHOT_DIR_NAME, OPEN_LOCK_NAME, VACUUM_PENDING_NAME)


__all__ = [
    "DB_NAME",
    "SIDECAR_NAMES",
    "SNAPSHOT_DIR_NAME",
    "StoreError",
    "NewerSchemaError",
    "UnsupportedFilesystemError",
    "app_root",
    "db_path",
    "connect",
    "close_thread_connections",
    "reset_for_tests",
    "write_txn",
    "data_version",
    "migrate",
    "head_version",
    "user_version",
    "integrity_check",
    "data_fingerprint",
    "snapshot",
    "unchanged_since_snapshot",
    "newest_snapshot",
    "restore_snapshot",
    "open_checked",
    "is_store_file",
]
