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

import json
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


def _has_file(root: Path | str, pattern: str) -> bool:
    try:
        base = Path(root)
        if not base.is_dir():
            return False
        return any(p.is_file() for p in base.glob(pattern))
    except OSError:
        return False


def has_uefnproject(root: Path | str) -> bool:
    """True when *root* holds a ``*.uefnproject`` file, the only disk proof of an island."""
    return _has_file(root, "*.uefnproject")


def has_uproject(root: Path | str) -> bool:
    """True when *root* holds a ``*.uproject``: an Unreal Engine project, never an island."""
    return _has_file(root, "*.uproject")


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
    if has_uproject(root):
        # Unreal Engine projects have a Content folder too; old rows saved them as islands.
        return FOLDER
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


# --------------------------------------------------------------------------- identity
#
# UEFN mounts an island's content under its ROOT PLUGIN name (``/<Plugin>/...``), and
# that is what the editor reports as the live project name. The plugin is usually named
# after the folder, but UEFN also names it by a module GUID (folder ``MyProjectBJJJ``,
# mount ``86ef2167-…``). The folder name alone therefore cannot identify an island; the
# names below are everything the island is called, read from its own descriptors.

# Mounts the editor uses for worlds that are not an island (unsaved level, Epic map).
RESERVED_MOUNTS = frozenset({"temp", "game", "engine", "script"})

_identity_cache: dict[str, tuple[tuple[object, ...], tuple[str, ...]]] = {}


def is_reserved_mount(name: str) -> bool:
    return str(name or "").strip().casefold() in RESERVED_MOUNTS


def read_uefnproject(root: Path | str) -> dict:
    """The island's ``*.uefnproject`` JSON, or ``{}`` when missing or unreadable."""
    try:
        base = Path(root)
        matches = sorted(base.glob("*.uefnproject"))
        if not matches:
            return {}
        data = json.loads(matches[0].read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def _root_plugin_names(data: dict) -> list[str]:
    """Plugin names from a ``.uefnproject``, the root plugin first."""
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return []
    roots: list[str] = []
    others: list[str] = []
    for entry in plugins:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        (roots if entry.get("bIsRoot") else others).append(name)
    return roots + others


def _uplugin_stems(root: Path) -> list[str]:
    """``<root>/*.uplugin`` (flat layout) then ``<root>/Plugins/*/*.uplugin`` (old layout)."""
    stems: list[str] = []
    try:
        for pattern in ("*.uplugin", "Plugins/*/*.uplugin"):
            for p in sorted(root.glob(pattern)):
                if p.is_file() and p.stem:
                    stems.append(p.stem)
    except OSError:
        pass
    return stems


def _identity_signature(root: Path) -> tuple[object, ...]:
    """Cheap change detector: the descriptor file's mtime and size."""
    try:
        matches = sorted(root.glob("*.uefnproject"))
        if not matches:
            return ("none",)
        st = matches[0].stat()
        return (str(matches[0]), st.st_mtime_ns, st.st_size)
    except OSError:
        return ("err",)


def island_identity_names(root: Path | str) -> list[str]:
    """Every name the island answers to, most specific first.

    Order: root plugin (the content mount), other plugins, ``.uplugin`` stems, the
    ``.uefnproject`` title, the folder name. Empty for an empty root. A folder project
    just yields its folder name. Results are cached per root until its ``.uefnproject``
    changes, so status polls do not re-read the descriptor every few seconds.
    """
    raw = str(root or "").strip()
    if not raw:
        return []
    try:
        base = project_root_path(raw)
    except (OSError, ValueError):
        base = Path(raw)
    key = _key(base)
    sig = _identity_signature(base)
    with _cache_lock:
        cached = _identity_cache.get(key)
        if cached and cached[0] == sig:
            return list(cached[1])
    names: list[str] = []
    data = read_uefnproject(base)
    names.extend(_root_plugin_names(data))
    names.extend(_uplugin_stems(base))
    title = str(data.get("title") or "").strip()
    if title:
        names.append(title)
    if base.name:
        names.append(base.name)
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        folded = name.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        out.append(name)
    with _cache_lock:
        _identity_cache[key] = (sig, tuple(out))
    return out


def island_mount_name(root: Path | str) -> str:
    """The island's content mount (root plugin name); the folder name when no descriptor
    says otherwise; empty for an empty root."""
    raw = str(root or "").strip()
    if not raw:
        return ""
    try:
        base = project_root_path(raw)
    except (OSError, ValueError):
        base = Path(raw)
    plugins = _root_plugin_names(read_uefnproject(base))
    if plugins:
        return plugins[0]
    stems = _uplugin_stems(base)
    if stems:
        return stems[0]
    return base.name


def is_island_identity(root: Path | str, name: str) -> bool:
    """True when ``name`` (the editor's live mount) is one of the island's names."""
    needle = str(name or "").strip().casefold()
    if not needle:
        return False
    return any(n.casefold() == needle for n in island_identity_names(root))


def forget_cached_identity(root: Path | str | None = None) -> None:
    with _cache_lock:
        if root is None:
            _identity_cache.clear()
        else:
            _identity_cache.pop(_key(root), None)


def resolve_project_root(selection: Path | str) -> tuple[Path, str]:
    """``(root, kind)`` for a user pick. Any folder works; drives and files are refused.

    A project Ducky already knows keeps its saved kind. A new one is an island only when
    it holds a ``*.uefnproject``; the caller saves the answer with the project.
    """
    root = project_root_path(selection)
    if has_uefnproject(root):
        return root, UEFN
    if has_uproject(root):
        return root, FOLDER
    saved = _saved_kind(root)
    return root, saved if saved in KINDS else FOLDER


def forget_cached_kind(root: Path | str | None = None) -> None:
    """Drop cached kinds (all of them when *root* is None) after a save or switch."""
    with _cache_lock:
        if root is None:
            _kind_cache.clear()
            _flavor_cache.clear()
        else:
            _kind_cache.pop(_key(root), None)
            _flavor_cache.pop(_key(root), None)


# --------------------------------------------------------------------------- flavor
#
# What a project is, for its icon only (the Content pane, the project list): a UEFN
# island, or a folder that is a Roblox, Unreal or Unity project, or just a folder. It
# never changes what Ducky does with the project; that is the kind's job.

ROBLOX = "roblox"
UNREAL = "unreal"
UNITY = "unity"
# Rojo's project file and the Roblox toolchain managers' manifests.
_ROBLOX_MARKERS = ("default.project.json", "wally.toml", "aftman.toml", "rokit.toml", "foreman.toml")

_flavor_cache: dict[str, str] = {}


def _compute_flavor(root: Path) -> str:
    try:
        if any((root / name).is_file() for name in _ROBLOX_MARKERS) or _has_file(root, "*.rbxl") or _has_file(
            root, "*.rbxlx"
        ):
            return ROBLOX
        if has_uproject(root):
            return UNREAL
        if (root / "Assets").is_dir() and (root / "ProjectSettings").is_dir():
            return UNITY
    except OSError:
        pass
    return FOLDER


def project_flavor(root: Path | str) -> str:
    """``uefn``, ``roblox``, ``unreal``, ``unity`` or ``folder`` for a project root; empty without one."""
    raw = str(root or "").strip()
    if not raw:
        return ""
    if project_kind(raw) == UEFN:
        return UEFN
    key = _key(raw)
    with _cache_lock:
        cached = _flavor_cache.get(key)
    if cached:
        return cached
    flavor = _compute_flavor(Path(raw))
    with _cache_lock:
        _flavor_cache[key] = flavor
    return flavor


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
