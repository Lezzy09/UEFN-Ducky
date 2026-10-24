"""``ducky_mirror_chats`` / ``ducky_mirror_peers`` (migration 0023): read-only copies of
your other UEFN Duckies' chats, pulled by ``frontend.ducky_sync``. Copies only: a chat
lives on its home Ducky, so nothing here is ever sent back or run.

A copy's title and rows are sealed for its account (:mod:`backend.store.account_rows`);
copies an older build stored plain still read, and are sealed in place.
"""

from __future__ import annotations

import json
import time
from typing import Any

from backend.store import account_rows, db


def note_chat(account: str, ducky: str, conv_id: str, title: str, updated: float) -> bool:
    """Record a chat the home Ducky lists. True when its rows need pulling: never
    pulled, or changed there since the rows here (a failed pull stays True)."""
    account_rows.ready(account)
    conn = db.connect()
    row = conn.execute(
        "SELECT title FROM ducky_mirror_chats WHERE account_id=? AND ducky=? AND conv_id=?", (account, ducky, conv_id)
    ).fetchone()
    # Every round lists every chat: a title that didn't change isn't sealed and written again.
    stored = row[0] if row is not None and account_rows.open_cached(str(row[0]), account) == title else None
    if stored is None:
        stored = account_rows.seal(title, account)
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO ducky_mirror_chats(account_id, ducky, conv_id, title, updated, gone) VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(account_id, ducky, conv_id) DO UPDATE SET title=excluded.title, updated=excluded.updated, gone=0",
            (account, ducky, conv_id, stored, float(updated)),
        )
        (rows_of,) = conn.execute(
            "SELECT rows_of FROM ducky_mirror_chats WHERE account_id=? AND ducky=? AND conv_id=?",
            (account, ducky, conv_id),
        ).fetchone()
    return float(rows_of) < 0 or float(updated) > float(rows_of)


def put_rows(account: str, ducky: str, conv_id: str, rows: list[dict[str, Any]], *, of: float) -> None:
    """The chat's newest rows, as of the home's updated time ``of``."""
    account_rows.ready(account)
    sealed = account_rows.seal(json.dumps(rows, ensure_ascii=False, default=str), account)
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "UPDATE ducky_mirror_chats SET rows=?, rows_of=?, synced=? WHERE account_id=? AND ducky=? AND conv_id=?",
            (sealed, float(of), time.time(), account, ducky, conv_id),
        )


def mark_gone(account: str, ducky: str, listed: set[str]) -> int:
    """Chats the home Ducky no longer lists drop out of the lists; their copies stay."""
    conn = db.connect()
    have = [r[0] for r in conn.execute(
        "SELECT conv_id FROM ducky_mirror_chats WHERE account_id=? AND ducky=? AND gone=0", (account, ducky)
    ).fetchall()]
    gone = [c for c in have if c not in listed]
    if gone:
        with db.write_txn(conn):
            conn.executemany(
                "UPDATE ducky_mirror_chats SET gone=1 WHERE account_id=? AND ducky=? AND conv_id=?",
                [(account, ducky, c) for c in gone],
            )
    return len(gone)


def note_peer(account: str, ducky: str, name: str) -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO ducky_mirror_peers(account_id, ducky, name, synced) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_id, ducky) DO UPDATE SET name=excluded.name, synced=excluded.synced",
            (account, ducky, name, time.time()),
        )


def forget_peer(account: str, ducky: str) -> int:
    """Drop one other Ducky and all its copies here. Returns how many chats went."""
    conn = db.connect()
    with db.write_txn(conn):
        gone = conn.execute(
            "DELETE FROM ducky_mirror_chats WHERE account_id=? AND ducky=?", (account, ducky)
        ).rowcount
        conn.execute("DELETE FROM ducky_mirror_peers WHERE account_id=? AND ducky=?", (account, ducky))
    return int(gone or 0)


def peers(account: str) -> list[dict[str, Any]]:
    """Every other Ducky with copies here, its chats newest first (rows left out)."""
    conn = db.connect()
    out: list[dict[str, Any]] = []
    for ducky, name, synced in conn.execute(
        "SELECT ducky, name, synced FROM ducky_mirror_peers WHERE account_id=? ORDER BY name, ducky", (account,)
    ).fetchall():
        chats = [
            {"conv_id": c, "title": account_rows.open_cached(str(t or ""), account), "updated": float(u or 0),
             "synced": float(s or 0)}
            for c, t, u, s in conn.execute(
                "SELECT conv_id, title, updated, synced FROM ducky_mirror_chats "
                "WHERE account_id=? AND ducky=? AND gone=0 ORDER BY updated DESC",
                (account, ducky),
            ).fetchall()
        ]
        out.append({"ducky": ducky, "name": name, "synced": float(synced or 0), "chats": chats})
    return out


def rows(account: str, ducky: str, conv_id: str) -> dict[str, Any] | None:
    r = db.connect().execute(
        "SELECT title, updated, rows, synced FROM ducky_mirror_chats WHERE account_id=? AND ducky=? AND conv_id=?",
        (account, ducky, conv_id),
    ).fetchone()
    if r is None:
        return None
    try:
        parsed = json.loads(account_rows.open_text(str(r[2] or "[]"), account) or "[]")
    except ValueError:
        parsed = []
    return {
        "title": account_rows.open_cached(str(r[0] or ""), account),
        "updated": float(r[1] or 0),
        "rows": parsed if isinstance(parsed, list) else [],
        "synced": float(r[3] or 0),
    }
