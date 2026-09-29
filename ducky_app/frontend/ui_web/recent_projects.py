"""Recently opened projects, UEFN islands and plain folders (does not modify panel_settings).

Each project also remembers its kind (``frontend.project_kind``). Paths saved before
kinds existed report ``uefn``: they were only ever accepted as islands.
"""

from __future__ import annotations

import json
from pathlib import Path

from frontend.atomic_json import write_json_atomic
from frontend.project_kind import KINDS, UEFN, forget_cached_kind, project_root_path
from frontend.settings import default_app_data_dir

_MAX_RECENT = 20


def _store_path() -> Path:
    return default_app_data_dir() / "recent_projects.json"


def _normalize(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    try:
        return str(project_root_path(raw))
    except (OSError, ValueError):
        try:
            return str(Path(raw).resolve())
        except OSError:
            return raw


def _use_db() -> bool:
    from backend.store.switch import use_db

    return use_db("projects")


def _repo():
    from backend.store.importers import phase1
    from backend.store.repos import projects as repo

    phase1.ensure("projects")
    return repo


def _read_store() -> dict:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, list):
        return {"projects": data}
    return data if isinstance(data, dict) else {}


def _stored_kinds(data: dict) -> dict[str, str]:
    raw = data.get("kinds")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if str(v) in KINDS}


def _write_store(items: list[str], kinds: dict[str, str]) -> None:
    kept = items[:_MAX_RECENT]
    write_json_atomic(
        _store_path(),
        {"projects": kept, "kinds": {p: kinds[p] for p in kept if p in kinds}},
    )


def load_recent_projects() -> list[str]:
    if _use_db():
        try:
            out: list[str] = []
            seen: set[str] = set()
            for item in _repo().recent_paths():
                norm = _normalize(item)
                if norm and norm not in seen:
                    seen.add(norm)
                    out.append(norm)
            return out[:_MAX_RECENT]
        except (OSError, RuntimeError):
            pass
    raw = _read_store().get("projects")
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        norm = _normalize(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out[:_MAX_RECENT]


def load_project_kind(path: str) -> str:
    """Saved kind for *path*: 'uefn', 'folder', or '' when Ducky never recorded it."""
    norm = _normalize(path)
    if not norm:
        return ""
    if _use_db():
        try:
            return _repo().kind_for(norm)
        except (OSError, RuntimeError):
            pass
    data = _read_store()
    kind = _stored_kinds(data).get(norm, "")
    if kind:
        return kind
    listed = data.get("projects")
    if isinstance(listed, list) and any(_normalize(str(p)) == norm for p in listed if isinstance(p, str)):
        return UEFN  # saved before kinds existed: only islands were accepted then
    return ""


def add_recent_project(path: str, *, kind: str = "") -> None:
    norm = _normalize(path)
    if not norm:
        return
    kind = kind if kind in KINDS else ""
    if _use_db():
        try:
            _repo().touch(norm, kind=kind)
        except (OSError, RuntimeError):
            pass
    else:
        data = _read_store()
        kinds = _stored_kinds(data)
        previous = kinds.get(norm) or (UEFN if norm in load_recent_projects() else "")
        if previous == UEFN or not kind:
            kind = previous or kind
        if kind:
            kinds[norm] = kind
        items = [p for p in load_recent_projects() if p != norm]
        items.insert(0, norm)
        _write_store(items, kinds)
    forget_cached_kind(norm)
    try:
        from frontend.appdata_maintenance import prune_empty_project_dirs

        prune_empty_project_dirs()
    except Exception:
        pass


def remove_recent_project(path: str) -> None:
    norm = _normalize(path)
    if not norm:
        return
    if _use_db():
        try:
            _repo().forget(norm)
            return
        except (OSError, RuntimeError):
            pass
    data = _read_store()
    items = [p for p in load_recent_projects() if p != norm]
    _write_store(items, _stored_kinds(data))
