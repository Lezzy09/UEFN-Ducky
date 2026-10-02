"""``duckies`` table: the user's duckies, kept apart from settings (migration 0014).

Nothing here deletes a row. Removing a shipped ducky archives it, deleting a custom one
stamps ``deleted`` and keeps the row, and every write first copies the row it replaces
into ``duckies_history``. A settings save can no longer touch duckies at all.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from backend.store import db

_COLS = "id, kind, data, archived, deleted, created, updated"


def _row(r: tuple) -> dict[str, Any]:
    try:
        data = json.loads(r[2] or "{}")
    except json.JSONDecodeError:
        data = {}
    return {
        "id": str(r[0]),
        "kind": str(r[1]),
        "data": data if isinstance(data, dict) else {},
        "archived": bool(r[3]),
        "deleted": float(r[4] or 0),
        "created": float(r[5] or 0),
        "updated": float(r[6] or 0),
    }


def list_all(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    """Every ducky row, oldest first (the order the user made them)."""
    sql = f"SELECT {_COLS} FROM duckies"
    if not include_deleted:
        sql += " WHERE deleted = 0"
    return [_row(r) for r in db.connect().execute(sql + " ORDER BY created, id").fetchall()]


def get(ducky_id: str) -> dict[str, Any] | None:
    r = db.connect().execute(f"SELECT {_COLS} FROM duckies WHERE id=?", (ducky_id,)).fetchone()
    return None if r is None else _row(r)


def history(ducky_id: str) -> list[dict[str, Any]]:
    """Earlier copies of one ducky, newest first."""
    rows = db.connect().execute(
        "SELECT seq, kind, data, archived, deleted, saved FROM duckies_history WHERE id=? ORDER BY seq DESC",
        (ducky_id,),
    ).fetchall()
    return [
        {"seq": r[0], "kind": r[1], "data": json.loads(r[2] or "{}"), "archived": bool(r[3]),
         "deleted": float(r[4] or 0), "saved": float(r[5])}
        for r in rows
    ]


def _keep_previous(conn: sqlite3.Connection, ducky_id: str, now: float) -> None:
    conn.execute(
        "INSERT INTO duckies_history(id, kind, data, archived, deleted, saved) "
        "SELECT id, kind, data, archived, deleted, ? FROM duckies WHERE id=?",
        (now, ducky_id),
    )


def save(ducky_id: str, kind: str, data: dict[str, Any]) -> None:
    """Write one ducky's fields. Archived/deleted state is left as it is."""
    now = time.time()
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, ducky_id, now)
        conn.execute(
            "INSERT INTO duckies(id, kind, data, archived, deleted, created, updated) VALUES (?, ?, ?, 0, 0, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
            (ducky_id, kind, json.dumps(data, ensure_ascii=False), now, now),
        )


def set_archived(ducky_id: str, kind: str, archived: bool) -> None:
    now = time.time()
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, ducky_id, now)
        conn.execute(
            "INSERT INTO duckies(id, kind, data, archived, deleted, created, updated) VALUES (?, ?, '{}', ?, 0, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET archived=excluded.archived, updated=excluded.updated",
            (ducky_id, kind, 1 if archived else 0, now, now),
        )


def set_deleted(ducky_id: str, deleted: bool, *, kind: str = "custom") -> bool:
    """Mark a ducky deleted (or bring it back). The row and its data stay.

    A custom ducky must already have a row; a shipped one gets a row if it has none.
    """
    now = time.time()
    stamp = now if deleted else 0.0
    conn = db.connect()
    with db.write_txn(conn):
        _keep_previous(conn, ducky_id, now)
        if kind == "bundled":
            cur = conn.execute(
                "INSERT INTO duckies(id, kind, data, archived, deleted, created, updated) VALUES (?, 'bundled', '{}', 0, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET deleted=excluded.deleted, updated=excluded.updated",
                (ducky_id, stamp, now, now),
            )
        else:
            cur = conn.execute(
                "UPDATE duckies SET deleted=?, updated=? WHERE id=? AND kind='custom'",
                (stamp, now, ducky_id),
            )
    return cur.rowcount > 0


def insert_missing(rows: list[dict[str, Any]]) -> int:
    """Importer entry: add rows whose id is not there yet. Never overwrites."""
    conn = db.connect()
    added = 0
    with db.write_txn(conn):
        for row in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO duckies(id, kind, data, archived, deleted, created, updated) "
                "VALUES (?, ?, ?, ?, 0, ?, ?)",
                (
                    str(row["id"]),
                    str(row["kind"]),
                    json.dumps(row.get("data") or {}, ensure_ascii=False),
                    1 if row.get("archived") else 0,
                    float(row.get("created") or 0),
                    float(row.get("updated") or row.get("created") or 0),
                ),
            )
            added += cur.rowcount
    return added
