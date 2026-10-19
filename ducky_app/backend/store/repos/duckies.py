"""``duckies`` table: the user's duckies, kept apart from settings (migration 0014).

Nothing here deletes a row. Removing a shipped ducky archives it, deleting a custom one
stamps ``deleted`` and keeps the row, and every write first copies the row it replaces
into ``duckies_history``. A settings save can no longer touch duckies at all.

Rows belong to the signed-in account (migration 0024, :mod:`backend.store.account_rows`):
custom duckies and edits to shipped ones are per account, and their data is sealed for it.
Shipped duckies themselves are not rows; every account has them. ``ducky_id`` is the
ducky's id; ``id`` is only the row key (the ducky id on rows from before 0024,
``<account>~<ducky id>`` on new ones). ``account`` defaults to the signed-in one.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from backend.store import account_rows, db

_COLS = "ducky_id, kind, data, archived, deleted, created, updated"


def _who(account: str | None) -> str:
    return account or account_rows.current()


def _data(stored: str, account: str) -> dict[str, Any]:
    try:
        data = json.loads(account_rows.open_text(stored or "{}", account))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _sealed(data: dict[str, Any], account: str, **dumps: Any) -> str:
    return account_rows.seal(json.dumps(data, ensure_ascii=False, **dumps), account)


def _row(r: tuple, account: str) -> dict[str, Any]:
    return {
        "id": str(r[0]),
        "kind": str(r[1]),
        "data": _data(r[2], account),
        "archived": bool(r[3]),
        "deleted": float(r[4] or 0),
        "created": float(r[5] or 0),
        "updated": float(r[6] or 0),
    }


def list_all(*, include_deleted: bool = False, account: str | None = None) -> list[dict[str, Any]]:
    """Every ducky row of the account, oldest first (the order the user made them)."""
    account = _who(account)
    sql = f"SELECT {_COLS} FROM duckies WHERE account_id=?"
    if not include_deleted:
        sql += " AND deleted = 0"
    rows = db.connect().execute(sql + " ORDER BY created, ducky_id", (account,)).fetchall()
    return [_row(r, account) for r in rows]


def get(ducky_id: str, *, account: str | None = None) -> dict[str, Any] | None:
    account = _who(account)
    r = db.connect().execute(
        f"SELECT {_COLS} FROM duckies WHERE account_id=? AND ducky_id=?", (account, ducky_id)
    ).fetchone()
    return None if r is None else _row(r, account)


def history(ducky_id: str, *, account: str | None = None) -> list[dict[str, Any]]:
    """Earlier copies of one ducky, newest first."""
    account = _who(account)
    rows = db.connect().execute(
        "SELECT seq, kind, data, archived, deleted, saved FROM duckies_history WHERE account_id=? AND id=? "
        "ORDER BY seq DESC",
        (account, ducky_id),
    ).fetchall()
    return [
        {"seq": r[0], "kind": r[1], "data": _data(r[2], account), "archived": bool(r[3]),
         "deleted": float(r[4] or 0), "saved": float(r[5])}
        for r in rows
    ]


def _keep_previous(conn: sqlite3.Connection, account: str, ducky_id: str, now: float) -> None:
    conn.execute(
        "INSERT INTO duckies_history(account_id, id, kind, data, archived, deleted, saved) "
        "SELECT account_id, ducky_id, kind, data, archived, deleted, ? FROM duckies WHERE account_id=? AND ducky_id=?",
        (now, account, ducky_id),
    )


def _insert(conn: sqlite3.Connection, account: str, ducky_id: str, kind: str, data: str, *,
            archived: int = 0, deleted: float = 0.0, created: float, updated: float, ignore: bool = False) -> int:
    verb = "INSERT OR IGNORE" if ignore else "INSERT"
    return conn.execute(
        f"{verb} INTO duckies(id, account_id, ducky_id, kind, data, archived, deleted, created, updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"{account}~{ducky_id}", account, ducky_id, kind, data, archived, deleted, created, updated),
    ).rowcount


def save(ducky_id: str, kind: str, data: dict[str, Any], *, account: str | None = None) -> None:
    """Write one ducky's fields. Archived/deleted state is left as it is."""
    account = _who(account)
    account_rows.ready(account)
    sealed = _sealed(data, account)
    now = time.time()
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, account, ducky_id, now)
        cur = conn.execute(
            "UPDATE duckies SET data=?, updated=? WHERE account_id=? AND ducky_id=?", (sealed, now, account, ducky_id)
        )
        if not cur.rowcount:
            _insert(conn, account, ducky_id, kind, sealed, created=now, updated=now)


def save_synced(ducky_id: str, kind: str, data: dict[str, Any], updated: float, *, account: str | None = None) -> bool:
    """Take another of your UEFN Duckies' copy of one ducky (frontend.ducky_sync).

    Only when it changed there after it changed here, and only its fields: archive and
    delete stay this computer's own, and a new ducky comes in active. ``updated`` keeps
    the other Ducky's time, so the two never pass the same copy back and forth. The row
    it replaces goes to ``duckies_history`` first. True when something was written.
    """
    account = _who(account)
    account_rows.ready(account)
    new = json.dumps(data, ensure_ascii=False, sort_keys=True)
    sealed = account_rows.seal(new, account)
    conn = db.connect()
    with db.write_txn(conn):
        cur = conn.execute(
            "SELECT kind, data, updated FROM duckies WHERE account_id=? AND ducky_id=?", (account, ducky_id)
        ).fetchone()
        if cur is not None:
            same = json.dumps(_data(cur[1], account), ensure_ascii=False, sort_keys=True) == new
            if same or float(cur[2] or 0) >= float(updated) or str(cur[0]) != kind:
                return False
            _keep_previous(conn, account, ducky_id, time.time())
            conn.execute(
                "UPDATE duckies SET data=?, updated=? WHERE account_id=? AND ducky_id=?",
                (sealed, float(updated), account, ducky_id),
            )
            return True
        _insert(conn, account, ducky_id, kind, sealed, created=float(updated), updated=float(updated))
        return True


def set_archived(ducky_id: str, kind: str, archived: bool, *, account: str | None = None) -> None:
    account = _who(account)
    account_rows.ready(account)
    empty = _sealed({}, account)
    now = time.time()
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, account, ducky_id, now)
        cur = conn.execute(
            "UPDATE duckies SET archived=?, updated=? WHERE account_id=? AND ducky_id=?",
            (1 if archived else 0, now, account, ducky_id),
        )
        if not cur.rowcount:
            _insert(conn, account, ducky_id, kind, empty, archived=1 if archived else 0, created=now, updated=now)


def set_deleted(ducky_id: str, deleted: bool, *, kind: str = "custom", account: str | None = None) -> bool:
    """Mark a ducky deleted (or bring it back). The row and its data stay.

    A custom ducky must already have a row; a shipped one gets a row if it has none.
    """
    account = _who(account)
    account_rows.ready(account)
    empty = _sealed({}, account)
    now = time.time()
    stamp = now if deleted else 0.0
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, account, ducky_id, now)
        if kind == "bundled":
            changed = conn.execute(
                "UPDATE duckies SET deleted=?, updated=? WHERE account_id=? AND ducky_id=?",
                (stamp, now, account, ducky_id),
            ).rowcount
            if not changed:
                changed = _insert(conn, account, ducky_id, "bundled", empty, deleted=stamp, created=now, updated=now)
        else:
            changed = conn.execute(
                "UPDATE duckies SET deleted=?, updated=? WHERE account_id=? AND ducky_id=? AND kind='custom'",
                (stamp, now, account, ducky_id),
            ).rowcount
    return changed > 0


def insert_missing(rows: list[dict[str, Any]], *, account: str | None = None) -> int:
    """Importer entry: add rows whose id the account doesn't have yet. Never overwrites."""
    account = _who(account)
    account_rows.ready(account)
    sealed = [(row, _sealed(row.get("data") or {}, account)) for row in rows]
    conn = db.connect()
    added = 0
    with db.write_txn(conn):
        for row, data in sealed:
            added += _insert(
                conn, account, str(row["id"]), str(row["kind"]), data,
                archived=1 if row.get("archived") else 0,
                created=float(row.get("created") or 0),
                updated=float(row.get("updated") or row.get("created") or 0),
                ignore=True,
            )
    return added
