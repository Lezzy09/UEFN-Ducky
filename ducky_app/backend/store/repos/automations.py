"""``automations`` table: one row per workflow graph (automation or pipeline)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from backend.store import db


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


_COLS = "id, name, enabled, graph, runs, updated, last_run, kind, description"


def get(workflow_id: str) -> dict[str, Any] | None:
    row = db.connect().execute(
        f"SELECT {_COLS} FROM automations WHERE id=?",
        (workflow_id,),
    ).fetchone()
    return None if row is None else _row(row)


def put(doc: dict[str, Any], *, versioned: bool = False) -> None:
    conn = db.connect()
    kind = str(doc.get("kind") or "automation").strip().lower() or "automation"
    if kind not in ("automation", "pipeline"):
        kind = "automation"
    with db.write_txn(conn):
        if versioned:
            previous = get(str(doc["id"]))
            if previous and not conn.execute("SELECT 1 FROM workflow_versions WHERE workflow_id=? LIMIT 1", (str(doc["id"]),)).fetchone():
                _archive(conn, previous)
            _archive(conn, doc)
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
                kind,
                str(doc.get("description") or ""),
            ),
        )


def delete(workflow_id: str) -> bool:
    conn = db.connect()
    with db.write_txn(conn):
        cur = conn.execute("DELETE FROM automations WHERE id=?", (workflow_id,))
    return cur.rowcount > 0


def list_all() -> list[dict[str, Any]]:
    rows = db.connect().execute(
        f"SELECT {_COLS} FROM automations ORDER BY updated DESC, name"
    ).fetchall()
    return [_row(r) for r in rows]


def _row(row: Any) -> dict[str, Any]:
    try:
        graph = json.loads(row[3])
    except ValueError:
        graph = {"nodes": [], "edges": []}
    if not isinstance(graph, dict):
        graph = {"nodes": [], "edges": []}
    try:
        runs = json.loads(row[4])
    except ValueError:
        runs = []
    if not isinstance(runs, list):
        runs = []
    kind = str(row[7] or "automation").strip().lower() if len(row) > 7 else "automation"
    if kind not in ("automation", "pipeline"):
        kind = "automation"
    description = str(row[8] or "") if len(row) > 8 else ""
    return {
        "id": str(row[0]),
        "name": str(row[1] or ""),
        "enabled": bool(int(row[2] or 0)),
        "graph": graph,
        "runs": runs,
        "updated": float(row[5] or 0.0),
        "last_run": float(row[6] or 0.0),
        "kind": kind,
        "description": description,
    }


def _archive(conn: Any, doc: dict[str, Any]) -> None:
    from backend.automations.versions import snapshot
    conn.execute("INSERT INTO workflow_versions(id, workflow_id, saved_at, snapshot) VALUES (?, ?, ?, ?)",
                 (str(uuid.uuid4()), str(doc["id"]), float(doc.get("updated") or 0), _dumps(snapshot(doc))))


def list_versions(workflow_id: str) -> list[dict[str, Any]]:
    from backend.automations.versions import summary
    rows = db.connect().execute("SELECT id, snapshot FROM workflow_versions WHERE workflow_id=? ORDER BY sequence DESC", (workflow_id,)).fetchall()
    return [summary(row[0], json.loads(row[1])) for row in rows]


def get_version(workflow_id: str, version_id: str) -> dict[str, Any] | None:
    row = db.connect().execute("SELECT snapshot FROM workflow_versions WHERE workflow_id=? AND id=?", (workflow_id, version_id)).fetchone()
    return json.loads(row[0]) if row else None
