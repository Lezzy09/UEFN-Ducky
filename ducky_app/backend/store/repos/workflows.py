"""Per-account workflow state that never syncs (migration 0012): the run log, last
run and "Run on this PC" (``workflow_runtime``), plus one meta row per shared space
(``space_meta``, 0019): whether this account may change the space's workflows, and the
space's web page. The workflow docs themselves are ``plugin_data`` rows.
"""

from __future__ import annotations

import time
from typing import Any

from backend.store import db


def runtime_get(account: str, workflow_id: str) -> dict[str, Any]:
    r = db.connect().execute(
        "SELECT runs, last_run, run_here FROM workflow_runtime WHERE account_id=? AND workflow_id=?",
        (account, workflow_id),
    ).fetchone()
    if not r:
        return {"runs": "", "last_run": 0.0, "run_here": False}
    return {"runs": str(r[0] or ""), "last_run": float(r[1] or 0.0), "run_here": bool(r[2])}


def runtime_put(account: str, workflow_id: str, **fields: Any) -> None:
    """Merge ``fields`` (runs, last_run, run_here) into the workflow's row."""
    row = runtime_get(account, workflow_id)
    row.update(fields)
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO workflow_runtime(account_id, workflow_id, runs, last_run, run_here) "
            "VALUES (?, ?, ?, ?, ?)",
            (account, workflow_id, str(row["runs"] or ""), float(row["last_run"] or 0.0), 1 if row["run_here"] else 0),
        )


def runtime_delete(account: str, workflow_ids: list[str]) -> None:
    if not workflow_ids:
        return
    conn = db.connect()
    with db.write_txn(conn):
        conn.executemany(
            "DELETE FROM workflow_runtime WHERE account_id=? AND workflow_id=?",
            [(account, wid) for wid in workflow_ids],
        )


def workflows_writable(account: str, space: str) -> bool:
    r = db.connect().execute(
        "SELECT workflows_writable FROM space_meta WHERE account_id=? AND space_id=?", (account, space)
    ).fetchone()
    return bool(r and r[0])


def meta_put(account: str, space: str, *, workflows_writable: bool, web_slug: str = "") -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO space_meta(account_id, space_id, workflows_writable, web_slug, updated) "
            "VALUES (?, ?, ?, ?, ?)",
            (account, space, 1 if workflows_writable else 0, web_slug, time.time()),
        )


def web_slug(account: str, space: str) -> str:
    """The space's web page id, ``""`` until the provider recorded it."""
    r = db.connect().execute(
        "SELECT web_slug FROM space_meta WHERE account_id=? AND space_id=?", (account, space)
    ).fetchone()
    return str(r[0]) if r else ""


def synced_spaces(account: str) -> list[str]:
    """Spaces this account has a sync row for (linked or listed once), in label order."""
    rows = db.connect().execute(
        "SELECT space_id FROM scope_sync WHERE account_id=? ORDER BY label COLLATE NOCASE, space_id", (account,)
    ).fetchall()
    return [str(r[0]) for r in rows]
