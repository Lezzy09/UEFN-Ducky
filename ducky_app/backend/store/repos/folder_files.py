"""Folder copies of plugins that keep their own folders (migration 0022): each team copy's
files as this PC last saw them, the junctions on this PC, each team copy's state and the
merge bases of files a declaration merges. The rules live in
:mod:`backend.uefn_plugins.team_folders`; this module only reads and writes rows.

Also the per-plugin rows other processes read (``workspace_state``): a call marker per
running plugin call, a row while a caller moves the plugin's folders, the plugin's reload
epoch, and a sandbox flag while a test of the plugin has its folders.

Functions taking ``conn`` run inside a transaction the caller holds; the others open
their own.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

from backend.store import db

_FILE_COLS = ("account_id, space_id, plugin_id, folder_id, project_id, unit, relpath, size, mtime_ns, sha256, base_seq, "
              "base_sha, dirty, deleted, sync_state, sync_error, changed_at, readonly, item_key")
_FILE_WHERE = "account_id=? AND space_id=? AND plugin_id=? AND folder_id=?"
LOCAL_ACCOUNT = "_pc"  # the Local copy belongs to this PC, not to an account
CALL_PREFIX = "plugin_call:"  # + plugin + ":" + marker id
LAST_CALL_PREFIX = "plugin_call_last:"
SANDBOX_PREFIX = "plugin_folder_sandbox:"
MOVING_PREFIX = "plugin_folder_moving:"  # + plugin + ":" + row id
EPOCH_PREFIX = "plugin_epoch:"  # space_vcs.CHANGE_LOG_PREFIX: one row per plugin, shared


def _row(r: Any) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


def _conn(conn: Any) -> Any:
    return conn if conn is not None else db.connect()


# --------------------------------------------------------------------------- files


def files(account: str, space: str, plugin: str, folder_id: str, *, project_id: str | None = None,
          unit: str | None = None, conn: Any = None) -> list[dict[str, Any]]:
    sql, args = f"SELECT {_FILE_COLS} FROM folder_files WHERE {_FILE_WHERE}", [account, space, plugin, folder_id]
    if project_id is not None:
        sql, args = sql + " AND project_id=?", [*args, project_id]
    if unit is not None:
        sql, args = sql + " AND unit=?", [*args, unit]
    return [_row(r) for r in _conn(conn).execute(sql + " ORDER BY relpath", args).fetchall()]


def file_get(account: str, space: str, plugin: str, folder_id: str, relpath: str, *,
             conn: Any = None) -> dict[str, Any] | None:
    r = _conn(conn).execute(f"SELECT {_FILE_COLS} FROM folder_files WHERE {_FILE_WHERE} AND relpath=?",
                            (account, space, plugin, folder_id, relpath)).fetchone()
    return _row(r) if r else None


def by_key(account: str, space: str, plugin: str, item_key: str, *, conn: Any = None) -> dict[str, Any] | None:
    """The file an item key names (a pulled delete carries no name, only the key)."""
    r = _conn(conn).execute(
        f"SELECT {_FILE_COLS} FROM folder_files WHERE account_id=? AND space_id=? AND plugin_id=? AND item_key=?",
        (account, space, plugin, item_key)).fetchone()
    return _row(r) if r else None


_FILE_FIELDS: dict[str, Any] = {
    "unit": str, "project_id": str, "size": int, "mtime_ns": int, "sha256": str, "base_seq": int, "base_sha": str,
    "dirty": lambda v: 1 if v else 0, "deleted": lambda v: 1 if v else 0, "sync_state": str,
    "sync_error": lambda v: str(v or "")[:500], "changed_at": float, "readonly": lambda v: 1 if v else 0,
    "item_key": str,
}


def file_put(conn: Any, account: str, space: str, plugin: str, folder_id: str, relpath: str, **fields: Any) -> None:
    """Insert or update one file row with ``fields`` (other names are ignored). Without
    ``unit`` it only updates a row that exists."""
    cols = [c for c in fields if c in _FILE_FIELDS]
    values = [_FILE_FIELDS[c](fields[c]) for c in cols]
    if not cols:
        return
    if "unit" in cols:
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols)
        sql = (f"INSERT INTO folder_files(account_id, space_id, plugin_id, folder_id, relpath, {', '.join(cols)}) "
               f"VALUES (?, ?, ?, ?, ?{', ?' * len(cols)}) "
               f"ON CONFLICT(account_id, space_id, plugin_id, folder_id, relpath) DO UPDATE SET {sets}")
        args: tuple[Any, ...] = (account, space, plugin, folder_id, relpath, *values)
    else:
        sql = f"UPDATE folder_files SET {', '.join(f'{c}=?' for c in cols)} WHERE {_FILE_WHERE} AND relpath=?"
        args = (*values, account, space, plugin, folder_id, relpath)
    if conn is not None:
        conn.execute(sql, args)
        return
    c = db.connect()
    with db.write_txn(c):
        c.execute(sql, args)


def file_delete(conn: Any, account: str, space: str, plugin: str, folder_id: str, relpath: str) -> None:
    conn.execute(f"DELETE FROM folder_files WHERE {_FILE_WHERE} AND relpath=?",
                 (account, space, plugin, folder_id, relpath))


def file_rename(conn: Any, account: str, space: str, plugin: str, folder_id: str, old: str, new: str,
                unit: str) -> None:
    """A file renamed in place (only its case or Unicode form changed): its row, and its
    merge base, go by the new name."""
    conn.execute(f"UPDATE folder_files SET relpath=?, unit=? WHERE {_FILE_WHERE} AND relpath=?",
                 (new, unit, account, space, plugin, folder_id, old))
    conn.execute("UPDATE folder_merge_base SET relpath=? WHERE account_id=? AND space_id=? AND plugin_id=? AND "
                 "folder_id=? AND relpath=?", (new, account, space, plugin, folder_id, old))


def unit_set_state(account: str, space: str, plugin: str, folder_id: str, unit: str, state: str, error: str = "",
                   *, dirty_only: bool = True, conn: Any = None) -> int:
    """Every (dirty) file of one unit gets ``state`` with the reason. Returns how many."""
    sql = (f"UPDATE folder_files SET sync_state=?, sync_error=? WHERE {_FILE_WHERE} AND unit=?"
           + (" AND dirty=1" if dirty_only else ""))
    args = (state, str(error or "")[:500], account, space, plugin, folder_id, unit)
    if conn is not None:
        return conn.execute(sql, args).rowcount
    c = db.connect()
    with db.write_txn(c):
        return c.execute(sql, args).rowcount


def dirty_units(account: str, space: str, plugin: str, folder_id: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """``{(folder_id, unit): {changed_at, files, states}}`` of units with changes not sent:
    when the last one happened, how many files and their sync states."""
    sql, args = ("SELECT folder_id, unit, MAX(changed_at), COUNT(*), GROUP_CONCAT(DISTINCT sync_state) FROM folder_files "
                 "WHERE account_id=? AND space_id=? AND plugin_id=? AND dirty=1", [account, space, plugin])
    if folder_id is not None:
        sql, args = sql + " AND folder_id=?", [*args, folder_id]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in db.connect().execute(sql + " GROUP BY folder_id, unit", args).fetchall():
        states = {s for s in str(r[4] or "").split(",") if s}
        out[(str(r[0]), str(r[1]))] = {"changed_at": float(r[2] or 0.0), "files": int(r[3]), "states": states}
    return out


def forget_files(account: str, space: str, plugin: str | None = None, *, conn: Any = None) -> None:
    """Every folder row of a space (its copy is being purged), or of one plugin in it."""
    tables = ("folder_files", "folder_copies", "folder_merge_base")

    def run(c: Any) -> None:
        for table in tables:
            if plugin is None:
                c.execute(f"DELETE FROM {table} WHERE account_id=? AND space_id=?", (account, space))
            else:
                c.execute(f"DELETE FROM {table} WHERE account_id=? AND space_id=? AND plugin_id=?",
                          (account, space, plugin))

    if conn is not None:
        run(conn)
        return
    c = db.connect()
    with db.write_txn(c):
        run(c)


def reset_rows(conn: Any, account: str, space: str, *, keep: bool) -> int:
    """The space's data was reset on the server (inside the caller's transaction). ``keep``
    (Upload my copy): every folder file here goes up again as new (no base, no held state);
    deletes and files waiting to be fetched again go, as nothing is left there. Otherwise
    (Clear my copy) every file row goes. Merge bases go either way; each copy's state stays,
    so the next pull fills it again. Returns how many files were queued, or removed."""
    args = (account, space)
    conn.execute("DELETE FROM folder_merge_base WHERE account_id=? AND space_id=?", args)
    if not keep:
        return conn.execute("DELETE FROM folder_files WHERE account_id=? AND space_id=?", args).rowcount
    conn.execute("DELETE FROM folder_files WHERE account_id=? AND space_id=? AND (deleted=1 OR sync_state='refetch')",
                 args)
    return conn.execute("UPDATE folder_files SET dirty=1, base_seq=0, base_sha='', sync_state='', sync_error='' "
                        "WHERE account_id=? AND space_id=?", args).rowcount


def requeue_refused(conn: Any, account: str, space: str) -> int:
    """Folder files the server refused go out again (the plan or the space's usage changed;
    inside the caller's transaction). A unit refused here (names that clash, a file too big)
    is refused again by the scan before anything is sent. Returns how many."""
    return conn.execute("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? "
                        "AND sync_state='refused'", (account, space)).rowcount


def requeue_blocked(account: str, space: str, plugin: str, folder_id: str | None = None,
                    unit: str | None = None) -> int:
    """Folder files of ``plugin`` (of one unit when ``folder_id`` and ``unit`` are given)
    whose unit's sends kept failing go out again (Retry). Returns how many."""
    sql, args = ("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? "
                 "AND plugin_id=? AND sync_state='blocked'", [account, space, plugin])
    if folder_id is not None and unit is not None:
        sql, args = sql + " AND folder_id=? AND unit=?", [*args, folder_id, unit]
    conn = db.connect()
    with db.write_txn(conn):
        return conn.execute(sql, args).rowcount


def unsent_units(account: str, space: str, *, since: float | None = None) -> int:
    """How many folder units of the space have changes this PC never sent (held back ones
    too), changed after ``since`` when given."""
    sql = ("SELECT COUNT(*) FROM (SELECT DISTINCT plugin_id, folder_id, unit FROM folder_files WHERE account_id=? "
           "AND space_id=? AND dirty=1")
    args: list[Any] = [account, space]
    if since is not None:
        sql, args = sql + " AND changed_at>?", [*args, float(since)]
    return int(db.connect().execute(sql + ")", args).fetchone()[0])


def forget_plugin(account: str, plugin: str) -> list[str]:
    """Every folder row of ``plugin`` in every space of the account. Returns the spaces."""
    conn = db.connect()
    with db.write_txn(conn):
        spaces = sorted({str(r[0]) for t in ("folder_files", "folder_copies", "folder_merge_base") for r in conn.execute(
            f"SELECT DISTINCT space_id FROM {t} WHERE account_id=? AND plugin_id=?", (account, plugin)).fetchall()})
        for space in spaces:
            forget_files(account, space, plugin, conn=conn)
    return spaces


# --------------------------------------------------------------------------- junctions


def link_get(plugin: str, folder_id: str, project_id: str = "") -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM folder_links WHERE plugin_id=? AND folder_id=? AND project_id=?",
                             (plugin, folder_id, project_id)).fetchone()
    return _row(r) if r else None


def links(plugin: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM folder_links", []
    if plugin is not None:
        sql, args = sql + " WHERE plugin_id=?", [plugin]
    return [_row(r) for r in db.connect().execute(sql + " ORDER BY plugin_id, folder_id, project_id", args).fetchall()]


def link_put(plugin: str, folder_id: str, project_id: str, *, root: str, target: str, account: str, space: str,
             adopted_at: float | None = None) -> None:
    now = time.time()
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO folder_links(plugin_id, folder_id, project_id, root, adopted_at, target, account_id, space_id, "
            "updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(plugin_id, folder_id, project_id) DO UPDATE SET "
            "root=excluded.root, target=excluded.target, account_id=excluded.account_id, space_id=excluded.space_id, "
            "updated=excluded.updated, adopted_at=CASE WHEN folder_links.adopted_at>0 THEN folder_links.adopted_at "
            "ELSE excluded.adopted_at END",
            (plugin, folder_id, project_id, root, now if adopted_at is None else float(adopted_at), target, account,
             space, now),
        )


def link_delete(plugin: str, folder_id: str, project_id: str = "") -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("DELETE FROM folder_links WHERE plugin_id=? AND folder_id=? AND project_id=?",
                     (plugin, folder_id, project_id))


# --------------------------------------------------------------------------- team copies


_COPY_DEFAULT: dict[str, Any] = {"pulled_seq": 0, "pulled_at": 0.0, "pushed_at": 0.0, "ready": 0, "offer": 0,
                                 "updated": 0.0}
_COPY_FIELDS: dict[str, Any] = {"pulled_seq": int, "pulled_at": float, "pushed_at": float,
                                "ready": lambda v: 1 if v else 0, "offer": lambda v: 1 if v else 0}


def copy_get(account: str, space: str, plugin: str, folder_id: str, project_id: str = "") -> dict[str, Any]:
    r = db.connect().execute(
        "SELECT pulled_seq, pulled_at, pushed_at, ready, offer, updated FROM folder_copies WHERE account_id=? AND "
        "space_id=? AND plugin_id=? AND folder_id=? AND project_id=?",
        (account, space, plugin, folder_id, project_id)).fetchone()
    return _row(r) if r else dict(_COPY_DEFAULT)


def copies(account: str, space: str | None = None, plugin: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM folder_copies WHERE account_id=?", [account]
    if space is not None:
        sql, args = sql + " AND space_id=?", [*args, space]
    if plugin is not None:
        sql, args = sql + " AND plugin_id=?", [*args, plugin]
    return [_row(r) for r in db.connect().execute(sql + " ORDER BY space_id, plugin_id, folder_id, project_id",
                                                  args).fetchall()]


def copy_put(account: str, space: str, plugin: str, folder_id: str, project_id: str = "", **fields: Any) -> None:
    cols = [c for c in fields if c in _COPY_FIELDS]
    if not cols:
        return
    values = [_COPY_FIELDS[c](fields[c]) for c in cols]
    sets = ", ".join([*(f"{c}=excluded.{c}" for c in cols), "updated=excluded.updated"])
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            f"INSERT INTO folder_copies(account_id, space_id, plugin_id, folder_id, project_id, {', '.join(cols)}, "
            f"updated) VALUES (?, ?, ?, ?, ?{', ?' * len(cols)}, ?) ON CONFLICT(account_id, space_id, plugin_id, "
            f"folder_id, project_id) DO UPDATE SET {sets}",
            (account, space, plugin, folder_id, project_id, *values, time.time()),
        )


def ever_synced(account: str, space: str, plugin: str) -> bool:
    """Whether any folder copy of ``plugin`` in the space was pulled to completion or sent
    to from this PC."""
    return db.connect().execute(
        "SELECT 1 FROM folder_copies WHERE account_id=? AND space_id=? AND plugin_id=? AND (pulled_at>0 OR pushed_at>0) "
        "LIMIT 1", (account, space, plugin)).fetchone() is not None


# --------------------------------------------------------------------------- merge bases


def base_get(account: str, space: str, plugin: str, folder_id: str, relpath: str, *,
             conn: Any = None) -> dict[str, Any] | None:
    r = _conn(conn).execute(
        "SELECT seq, sha256, value FROM folder_merge_base WHERE account_id=? AND space_id=? AND plugin_id=? AND "
        "folder_id=? AND relpath=?", (account, space, plugin, folder_id, relpath)).fetchone()
    return _row(r) if r else None


def base_put(conn: Any, account: str, space: str, plugin: str, folder_id: str, relpath: str, seq: int, sha256: str,
             value: str | None) -> None:
    sql = ("INSERT INTO folder_merge_base(account_id, space_id, plugin_id, folder_id, relpath, seq, sha256, value) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, space_id, plugin_id, folder_id, relpath) DO UPDATE "
           "SET seq=excluded.seq, sha256=excluded.sha256, value=excluded.value")
    args = (account, space, plugin, folder_id, relpath, int(seq), sha256, value)
    if conn is not None:
        conn.execute(sql, args)
        return
    c = db.connect()
    with db.write_txn(c):
        c.execute(sql, args)


def base_delete(conn: Any, account: str, space: str, plugin: str, folder_id: str, relpath: str) -> None:
    conn.execute("DELETE FROM folder_merge_base WHERE account_id=? AND space_id=? AND plugin_id=? AND folder_id=? AND "
                 "relpath=?", (account, space, plugin, folder_id, relpath))


# --------------------------------------------------------------------------- rows every process reads


def _doc(conn: Any, key: str) -> dict[str, Any]:
    r = conn.execute("SELECT value FROM workspace_state WHERE key=?", (key,)).fetchone()
    try:
        doc = json.loads(r[0]) if r else {}
    except ValueError:
        doc = {}
    return doc if isinstance(doc, dict) else {}


def _doc_put(conn: Any, key: str, doc: dict[str, Any]) -> None:
    conn.execute("INSERT INTO workspace_state(key, value, updated) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                 "value=excluded.value, updated=excluded.updated",
                 (key, json.dumps(doc, separators=(",", ":")), time.time()))


def call_add(plugin: str, pid: int, *, actor: str = "user", ducky: str = "", at: float | None = None) -> str:
    """A call of ``plugin`` started in process ``pid``. Returns the marker's key."""
    key = f"{CALL_PREFIX}{plugin}:{uuid.uuid4().hex}"
    conn = db.connect()
    with db.write_txn(conn):
        _doc_put(conn, key, {"plugin": plugin, "pid": int(pid), "started": time.time() if at is None else float(at),
                             "actor": actor, "ducky": ducky})
    return key


def call_done(key: str, plugin: str, *, actor: str = "user", ducky: str = "", at: float | None = None) -> None:
    """The call is over: its marker goes, and the plugin's last call is noted (a folder
    change soon after it is the caller's)."""
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("DELETE FROM workspace_state WHERE key=?", (key,))
        _doc_put(conn, LAST_CALL_PREFIX + plugin,
                 {"at": time.time() if at is None else float(at), "actor": actor, "ducky": ducky})


def calls(plugin: str) -> dict[str, dict[str, Any]]:
    """``{marker key: {plugin, pid, started, actor, ducky}}`` of the plugin's running calls."""
    return _prefixed(f"{CALL_PREFIX}{plugin}:")


def _prefixed(prefix: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in db.connect().execute("SELECT key, value FROM workspace_state WHERE key>=? AND key<?",
                                  (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1))).fetchall():
        try:
            doc = json.loads(r[1])
        except ValueError:
            continue
        if isinstance(doc, dict):
            out[str(r[0])] = doc
    return out


def moving_add(plugin: str, pid: int) -> str:
    """A caller in process ``pid`` is pointing the plugin's folders at another copy: calls
    that start meanwhile wait for it. Returns the row's key (dropped with :func:`calls_drop`)."""
    key = f"{MOVING_PREFIX}{plugin}:{uuid.uuid4().hex}"
    conn = db.connect()
    with db.write_txn(conn):
        _doc_put(conn, key, {"plugin": plugin, "pid": int(pid), "started": time.time()})
    return key


def movers(plugin: str) -> dict[str, dict[str, Any]]:
    """``{row key: {plugin, pid, started}}`` of the moves of the plugin's folders under way."""
    return _prefixed(f"{MOVING_PREFIX}{plugin}:")


def calls_drop(keys: Iterable[str]) -> None:
    keys = list(keys)
    if not keys:
        return
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(f"DELETE FROM workspace_state WHERE key IN ({', '.join('?' * len(keys))})", keys)


def last_call(plugin: str) -> dict[str, Any]:
    return _doc(db.connect(), LAST_CALL_PREFIX + plugin)


def reload_bump(plugin: str, why: str = "") -> int:
    """The plugin's folders now point at another copy: its epoch row moves on with a reload
    mark, so a process that loaded the plugin reloads it before its next call. The row is
    the one ``api.data.on_change`` reads (an entry with no keys: nothing to tell it).
    Returns the new epoch."""
    conn = db.connect()
    key = EPOCH_PREFIX + plugin
    with db.write_txn(conn):
        doc = _doc(conn, key)
        epoch = int(doc.get("epoch") or 0) + 1
        changes = [c for c in doc.get("changes") or [] if isinstance(c, list) and len(c) == 2]
        changes.append([epoch, []])
        doc.update(epoch=epoch, changes=changes[-32:], reload=epoch, reload_why=str(why)[:200])
        if len(changes) > 32:
            doc["trimmed"] = max(int(doc.get("trimmed") or 0), int(changes[-33][0]))
        _doc_put(conn, key, doc)
    return epoch


def reload_epoch(plugin: str) -> int:
    """The epoch of the plugin's last reload mark (0: never)."""
    return int(_doc(db.connect(), EPOCH_PREFIX + plugin).get("reload") or 0)


def sandbox_put(plugin: str, doc: dict[str, Any]) -> None:
    conn = db.connect()
    with db.write_txn(conn):
        _doc_put(conn, SANDBOX_PREFIX + plugin, doc)


def sandbox_get(plugin: str) -> dict[str, Any] | None:
    doc = _doc(db.connect(), SANDBOX_PREFIX + plugin)
    return doc or None


def sandbox_delete(plugin: str) -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("DELETE FROM workspace_state WHERE key=?", (SANDBOX_PREFIX + plugin,))
