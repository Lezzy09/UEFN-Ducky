"""Per-account workflow state that never syncs (migration 0012): the run log, last
run and "Run on this PC" (``workflow_runtime``), plus what the account may do in
each team (``team_perms``). The workflow docs themselves are ``plugin_data`` rows.
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


def perms_get(account: str, team: str) -> bool:
    r = db.connect().execute(
        "SELECT manage_automations FROM team_perms WHERE account_id=? AND team_id=?", (account, team)
    ).fetchone()
    return bool(r and r[0])


def perms_put(account: str, team: str, *, manage_automations: bool, slug: str = "") -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT OR REPLACE INTO team_perms(account_id, team_id, manage_automations, slug, updated) "
            "VALUES (?, ?, ?, ?, ?)",
            (account, team, 1 if manage_automations else 0, slug, time.time()),
        )


def team_slug(account: str, team: str) -> str:
    """The team's web slug (``/profile/teams/{slug}``), ``""`` until the hub was read once."""
    r = db.connect().execute("SELECT slug FROM team_perms WHERE account_id=? AND team_id=?", (account, team)).fetchone()
    return str(r[0]) if r else ""


def synced_teams(account: str) -> list[str]:
    """Teams this account has a sync row for (linked or listed once), in label order."""
    rows = db.connect().execute(
        "SELECT team_id FROM scope_sync WHERE account_id=? ORDER BY label COLLATE NOCASE, team_id", (account,)
    ).fetchall()
    return [str(r[0]) for r in rows]
