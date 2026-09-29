"""Project kinds: a UEFN island or a plain folder.

A UEFN island has ``<Name>.uefnproject`` at its root. Any other folder Ducky opens is a
folder project: the Content pane lists the folder itself, agents may write anywhere
under it except ``.git/``, and none of the island machinery runs against it (listener
init, Python quarantine, Verse workspace, digests, UEFN sync).

Projects saved before kinds existed stay ``uefn`` (the store defaults to it). A folder
project becomes an island once it gains a ``.uefnproject``; an island never turns
back into a folder on its own.

Destructive island steps never trust the stored kind: they check
``has_uefnproject`` on disk, so a wrong row can't make Ducky move a repo's files.
"""

from __future__ import annotations

import threading
from pathlib import Path

UEFN = "uefn"
FOLDER = "folder"
KINDS = frozenset({UEFN, FOLDER})

# Content pane root per kind, as a project-relative tree path: the island's Content
# folder, or the folder project itself.
UEFN_CONTENT_ROOT = "Content"
FOLDER_CONTENT_ROOT = "."

_kind_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _key(root: Path | str) -> str:
    try:
        return str(Path(root).resolve()).lower()
    except OSError:
        return str(root).lower()


def has_uefnproject(root: Path | str) -> bool:
    """True when *root* holds a ``*.uefnproject`` file, the only disk proof of an island."""
    try:
        base = Path(root)
        if not base.is_dir():
            return False
        return any(p.is_file() for p in base.glob("*.uefnproject"))
    except OSError:
        return False


def project_root_path(selection: Path | str) -> Path:
    """Project root for a pick: the folder, an island's ``Content/``, or a ``.uefnproject`` file.

    Disk facts only (no stored kinds), so path normalization can call it freely.
    """
    raw = str(selection or "").strip()
    if not raw:
        raise ValueError("No project folder selected.")
    p = Path(raw).resolve()
    if p.is_file():
        if p.suffix.lower() == ".uefnproject":
            return p.parent
        raise ValueError("Pick a project folder, not a file.")
    if not p.is_dir():
        raise ValueError(f"Folder not found: {raw}")
    if p.parent == p:
        raise ValueError("Pick a project folder, not a whole drive.")
    if p.name.lower() == "content" and not has_uefnproject(p) and has_uefnproject(p.parent):
        # Picked an island's Content/ instead of the island.
        return p.parent
    return p


def _saved_kind(root: Path | str) -> str:
    try:
        from frontend.ui_web.recent_projects import load_project_kind

        return load_project_kind(str(root))
    except Exception:
        return ""


def _compute_kind(root: Path) -> str:
    if has_uefnproject(root):
        return UEFN
    saved = _saved_kind(root)
    if saved in KINDS:
        return saved
    # Never recorded (a root set from Settings or env, or saved before kinds existed):
    # keep the rule Ducky always used, a Content folder means an island. New projects
    # are classified strictly by ``resolve_project_root`` and saved, so a repo with a
    # content/ folder that the user adds stays a folder project.
    try:
        return UEFN if (root / "Content").is_dir() else FOLDER
    except OSError:
        return FOLDER


def project_kind(root: Path | str) -> str:
    """``uefn`` or ``folder`` for a project root. Empty root keeps the old island default."""
    raw = str(root or "").strip()
    if not raw:
        return UEFN
    key = _key(raw)
    with _cache_lock:
        cached = _kind_cache.get(key)
    if cached:
        return cached
    kind = _compute_kind(Path(raw))
    with _cache_lock:
        _kind_cache[key] = kind
    return kind


def is_folder_project(root: Path | str) -> bool:
    return project_kind(root) == FOLDER


def is_saved_folder_project(root: Path | str) -> bool:
    """Strict form for write permissions: a folder project the user added, never a guess.

    An island (its own ``.uefnproject``, or its ``Content/`` handed in as the root) and any
    path Ducky never recorded answer False, so they keep the stricter island rules.
    """
    raw = str(root or "").strip()
    if not raw:
        return False
    base = Path(raw)
    if has_uefnproject(base):
        return False
    if base.name.lower() == "content" and has_uefnproject(base.parent):
        return False
    return _saved_kind(base) == FOLDER


def content_root_for(kind: str) -> str:
    return FOLDER_CONTENT_ROOT if kind == FOLDER else UEFN_CONTENT_ROOT


def resolve_project_root(selection: Path | str) -> tuple[Path, str]:
    """``(root, kind)`` for a user pick. Any folder works; drives and files are refused.

    A project Ducky already knows keeps its saved kind. A new one is an island only when
    it holds a ``*.uefnproject``; the caller saves the answer with the project.
    """
    root = project_root_path(selection)
    if has_uefnproject(root):
        return root, UEFN
    saved = _saved_kind(root)
    return root, saved if saved in KINDS else FOLDER


def forget_cached_kind(root: Path | str | None = None) -> None:
    """Drop cached kinds (all of them when *root* is None) after a save or switch."""
    with _cache_lock:
        if root is None:
            _kind_cache.clear()
        else:
            _kind_cache.pop(_key(root), None)


def islands_inside(folder: Path | str, *, limit: int = 12) -> list[dict[str, str]]:
    """UEFN islands one level below *folder* (someone picked ``Fortnite Projects``)."""
    out: list[dict[str, str]] = []
    try:
        children = sorted(Path(folder).iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return out
    for child in children:
        if len(out) >= limit:
            break
        try:
            if child.is_dir() and has_uefnproject(child):
                out.append({"name": child.name, "path": str(child.resolve())})
        except OSError:
            continue
    return out
