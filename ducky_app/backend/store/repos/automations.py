"""``automations`` table (legacy workflow rows, claimed into the data service by
``backend.automations.owned``) and ``workflow_versions`` (saved copies per PC)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from backend.store import db


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


_COLS = "id, name, enabled, graph, runs, updated, last_run, kind, description"


# --------------------------------------------------------------------------- legacy rows


def put(doc: dict[str, Any]) -> None:
    """Write a legacy row (the boot importer of old AppData JSON files uses this)."""
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO automations(id, name, enabled, graph, runs, updated, last_run, kind, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, enabled=excluded.enabled, "
            "graph=excluded.graph, runs=excluded.runs, updated=excluded.updated, "
            "last_run=excluded.last_run, kind=excluded.kind, description=excluded.description",
            (
                str(doc["id"]),
                str(doc.get("name") or ""),
                1 if doc.get("enabled", True) else 0,
                _dumps(doc.get("graph") or {"nodes": [], "edges": []}),
                _dumps(doc.get("runs") or []),
                float(doc.get("updated") or 0.0),
                float(doc.get("last_run") or 0.0),
                "automation",
                str(doc.get("description") or ""),
            ),
        )


def delete(workflow_id: str) -> bool:
    conn = db.connect()
    with db.write_txn(conn):
        cur = conn.execute("DELETE FROM automations WHERE id=?", (workflow_id,))
    return cur.rowcount > 0


def has_legacy() -> bool:
    return db.connect().execute("SELECT 1 FROM automations LIMIT 1").fetchone() is not None


def list_all() -> list[dict[str, Any]]:
    rows = db.connect().execute(f"SELECT {_COLS} FROM automations ORDER BY updated DESC, name").fetchall()
    return [_row(r) for r in rows]


def _row(row: Any) -> dict[str, Any]:
    try:
        graph = json.loads(row[3])
    except ValueError:
        graph = {"nodes": [], "edges": []}
    try:
        runs = json.loads(row[4])
    except ValueError:
        runs = []
    return {
        "id": str(row[0]),
        "name": str(row[1] or ""),
        "enabled": bool(int(row[2] or 0)),
        "graph": graph if isinstance(graph, dict) else {"nodes": [], "edges": []},
        "runs": runs if isinstance(runs, list) else [],
        "updated": float(row[5] or 0.0),
        "last_run": float(row[6] or 0.0),
        "description": str(row[8] or ""),
    }


# --------------------------------------------------------------------------- saved versions


def archive(conn: Any, workflow_id: str, saved_at: float, snapshot: str) -> None:
    """Inside the caller's transaction. ``snapshot`` is sealed for the account that
    saved it (or legacy plaintext JSON)."""
    conn.execute(
        "INSERT INTO workflow_versions(id, workflow_id, saved_at, snapshot) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), workflow_id, float(saved_at or 0), snapshot),
    )


def has_versions(workflow_id: str) -> bool:
    return db.connect().execute(
        "SELECT 1 FROM workflow_versions WHERE workflow_id=? LIMIT 1", (workflow_id,)
    ).fetchone() is not None


def version_rows(workflow_id: str) -> list[tuple[str, str]]:
    """``(version_id, stored snapshot)``, newest first."""
    rows = db.connect().execute(
        "SELECT id, snapshot FROM workflow_versions WHERE workflow_id=? ORDER BY sequence DESC", (workflow_id,)
    ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def version_row(workflow_id: str, version_id: str) -> str | None:
    row = db.connect().execute(
        "SELECT snapshot FROM workflow_versions WHERE workflow_id=? AND id=?", (workflow_id, version_id)
    ).fetchone()
    return str(row[0]) if row else None


def reseal_versions(old_id: str, new_id: str, convert: Callable[[str], str | None]) -> None:
    """Re-key and re-seal a workflow's versions (claim / import). ``convert`` returns
    the new stored text, or ``None`` to leave a row as it is."""
    conn = db.connect()
    rows = conn.execute("SELECT id, snapshot FROM workflow_versions WHERE workflow_id=?", (old_id,)).fetchall()
    updates = [(text, new_id, str(r[0])) for r in rows if (text := convert(str(r[1]))) is not None]
    with db.write_txn(conn):
        conn.executemany("UPDATE workflow_versions SET snapshot=?, workflow_id=? WHERE id=?", updates)
        if old_id != new_id:
            conn.execute("UPDATE workflow_versions SET workflow_id=? WHERE workflow_id=?", (new_id, old_id))
