"""Copy duckies out of settings into the ``duckies`` table, once per database.

Custom duckies, edits to shipped ones and the Archive list come across. The hide list
for shipped duckies does not: it is what wiped every shipped ducky, and shipped
duckies are now always there unless the user archives one. The settings rows are
left exactly as they are (an older build still reads them).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.store.repos import duckies as repo
from backend.store.switch import use_db

NAME = "duckies"


def _settings_values(root: Path) -> dict[str, Any]:
    if use_db("settings"):
        from backend.store.repos import settings as settings_repo

        rows, _version = settings_repo.load_fields_versioned()
        return rows
    path = root / "panel_settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def rows_from_settings(values: dict[str, Any], *, now: float | None = None) -> list[dict[str, Any]]:
    base = time.time() if now is None else now
    archived = {str(x).strip() for x in values.get("archived_agent_profile_ids") or [] if str(x).strip()}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    custom = values.get("agent_profiles")
    for i, item in enumerate(custom if isinstance(custom, list) else []):
        pid = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if not pid or pid in seen:
            continue
        seen.add(pid)
        # Keep the list order: created steps by a millisecond per ducky.
        rows.append({"id": pid, "kind": "custom", "data": {**item, "kind": "custom"},
                     "archived": pid in archived, "created": base + i / 1000})
    overrides = values.get("agent_profile_overrides")
    for pid, patch in (overrides.items() if isinstance(overrides, dict) else []):
        key = str(pid or "").strip()
        if key and key not in seen and isinstance(patch, dict):
            seen.add(key)
            rows.append({"id": key, "kind": "bundled", "data": patch, "archived": key in archived, "created": base})
    for key in sorted(archived - seen):
        rows.append({"id": key, "kind": "bundled", "data": {}, "archived": True, "created": base})
    return rows


def run(root: Path) -> dict[str, Any]:
    values = _settings_values(root)
    rows = rows_from_settings(values)
    added = repo.insert_missing(rows)
    hidden = values.get("hidden_bundled_agent_profile_ids")
    return {
        "custom": sum(1 for r in rows if r["kind"] == "custom"),
        "bundled_edits": sum(1 for r in rows if r["kind"] == "bundled" and r["data"]),
        "archived": sum(1 for r in rows if r["archived"]),
        "added": added,
        "hidden_list_ignored": len(hidden) if isinstance(hidden, list) else 0,
    }


def ensure() -> None:
    from backend.store.importers import phase1

    # Settings rows first, outside once(): its lock is not re-entrant.
    if use_db("settings"):
        phase1.ensure("settings")
    phase1.once(NAME, run)
