"""``plugin_kv`` table: Store plugin cache documents and UI prefs.

Rows are read fresh on every call (coding agents in other processes write the
same keys; a sticky in-memory copy is exactly the bug the file store had to
work around). ``sensitive=True`` values are DPAPI-encrypted by the caller
(``backend/agent/secrets.protect_text``) and stored base64 with ``encrypted=1``.

Every row belongs to one ``(account, scope)`` (migration 0009): callers always
say whose row it is. ``UNCLAIMED`` is where legacy rows wait until
:func:`claim_unclaimed` hands them to the first account that opens plugin data.
"""

from __future__ import annotations

import json
import time
from typing import Any

from backend.store import db

PREFS_KEY = "__prefs__"
UNCLAIMED = ""


def get(plugin_id: str, key: str, *, account: str, scope: str) -> tuple[Any | None, bool]:
    """Returns (value, encrypted). Encrypted values come back as the base64 text."""
    row = db.connect().execute(
        "SELECT value, encrypted FROM plugin_kv WHERE account_id=? AND scope_id=? AND plugin_id=? AND key=?",
        (account, scope, plugin_id, key),
    ).fetchone()
    if row is None:
        return None, False
    if int(row[1]):
        return str(row[0]), True
    try:
        return json.loads(row[0]), False
    except ValueError:
        return None, False


def set(  # noqa: A001
    plugin_id: str, key: str, value: Any, *, account: str, scope: str, encrypted_b64: str | None = None
) -> None:
    conn = db.connect()
    stored = encrypted_b64 if encrypted_b64 is not None else json.dumps(value, ensure_ascii=False)
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO plugin_kv(account_id, scope_id, plugin_id, key, value, encrypted, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, scope_id, plugin_id, key) DO UPDATE SET "
            "value=excluded.value, encrypted=excluded.encrypted, updated=excluded.updated",
            (account, scope, plugin_id, key, stored, 1 if encrypted_b64 is not None else 0, time.time()),
        )


def delete(plugin_id: str, key: str, *, account: str, scope: str) -> bool:
    conn = db.connect()
    with db.write_txn(conn):
        cur = conn.execute(
            "DELETE FROM plugin_kv WHERE account_id=? AND scope_id=? AND plugin_id=? AND key=?",
            (account, scope, plugin_id, key),
        )
    return cur.rowcount > 0


def keys(plugin_id: str, prefix: str = "", *, account: str, scope: str) -> list[str]:
    rows = db.connect().execute(
        "SELECT key FROM plugin_kv WHERE account_id=? AND scope_id=? AND plugin_id=? AND key LIKE ? "
        "AND key<>? ORDER BY key",
        (account, scope, plugin_id, prefix + "%", PREFS_KEY),
    ).fetchall()
    return [str(r[0]) for r in rows]


def delete_prefix(plugin_id: str, prefix: str, *, account: str, scope: str) -> list[str]:
    conn = db.connect()
    cleared = keys(plugin_id, prefix, account=account, scope=scope)
    if cleared:
        with db.write_txn(conn):
            conn.execute(
                "DELETE FROM plugin_kv WHERE account_id=? AND scope_id=? AND plugin_id=? AND key LIKE ? AND key<>?",
                (account, scope, plugin_id, prefix + "%", PREFS_KEY),
            )
    return cleared


def all_prefs(*, account: str, scope: str) -> dict[str, dict[str, Any]]:
    rows = db.connect().execute(
        "SELECT plugin_id, value FROM plugin_kv WHERE account_id=? AND scope_id=? AND key=? ORDER BY plugin_id",
        (account, scope, PREFS_KEY),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for pid, value in rows:
        try:
            slot = json.loads(value)
        except ValueError:
            continue
        if isinstance(slot, dict):
            out[str(pid)] = slot
    return out


def set_prefs(plugin_id: str, slot: dict[str, Any], *, account: str, scope: str) -> None:
    set(plugin_id, PREFS_KEY, slot, account=account, scope=scope)


def has_rows() -> bool:
    return db.connect().execute("SELECT 1 FROM plugin_kv LIMIT 1").fetchone() is not None


def has_unclaimed() -> bool:
    return db.connect().execute("SELECT 1 FROM plugin_kv WHERE account_id=? LIMIT 1", (UNCLAIMED,)).fetchone() is not None


def claim_unclaimed(account: str) -> int:
    """Legacy rows (account ``''``) become ``account``'s. A key the account already
    has keeps the account's row. Returns how many rows moved."""
    conn = db.connect()
    with db.write_txn(conn):
        cur = conn.execute("UPDATE OR IGNORE plugin_kv SET account_id=? WHERE account_id=?", (account, UNCLAIMED))
        conn.execute("DELETE FROM plugin_kv WHERE account_id=?", (UNCLAIMED,))
    return max(cur.rowcount, 0)


def delete_scope(account: str, scope: str) -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("DELETE FROM plugin_kv WHERE account_id=? AND scope_id=?", (account, scope))
