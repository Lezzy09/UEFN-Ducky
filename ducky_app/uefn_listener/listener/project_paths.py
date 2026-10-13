"""Pin Content Browser *create* paths to the active project's content_root.

UEFN islands must not invent ``/Game/Materials`` (or ``/Game/VFX``, ``/Game/UI``, …)
for new assets — that yields unsaved ``/Game/...`` packages and cook/publish
``Disallowed reference to /Game/...``. Reads under ``/Game/Creative`` stay OK;
this module is only for create/save destinations.
"""

from __future__ import annotations

import os

import unreal

# Epic Content Browser roots. Mirroring these under the island
# (/MyProject/Creative/...) is not a project folder.
_EPIC_GALLERY = frozenset({
    "creative",
    "environments",
    "packages",
    "athena",
    "items",
    "building",
    "props",
})

_MESH_EXT = frozenset({".fbx", ".obj", ".gltf", ".glb", ".usd"})
_TEXTURE_EXT = frozenset({".png", ".jpg", ".jpeg", ".tga", ".exr"})
_AUDIO_EXT = frozenset({".wav", ".ogg", ".mp3"})


# Mounts the editor uses for worlds that are not an island (unsaved level, Epic map).
_RESERVED_MOUNTS = frozenset({"temp", "engine", "script", "game"})


def mount_from_world_path(path: str) -> str:
    """``/<Mount>/...`` → ``Mount``; empty for a reserved (non-island) mount. Pure."""
    parts = str(path or "").split("/")
    if len(parts) >= 2 and parts[1] and parts[1].lower() not in _RESERVED_MOUNTS:
        return parts[1]
    return ""


def mount_from_world() -> str:
    """The open island's content mount (its root plugin name), or empty when the
    editor world is not an island map."""
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if not world:
            return ""
        return mount_from_world_path(world.get_path_name())
    except Exception:
        return ""


def island_directory() -> str:
    """On-disk folder of the open island (``ValkyrieProjectLibrary``), or empty.

    ``unreal.Paths.project_dir()`` is NOT this: inside UEFN that is the engine's
    FortniteGame project, never the island.
    """
    try:
        lib = unreal.ValkyrieProjectLibrary
        handle = lib.get_main_project()
        if handle and lib.is_project_handle_valid(handle):
            raw = str(lib.get_project_directory(handle) or "").strip()
            return os.path.normpath(raw) if raw else ""
    except Exception:
        pass
    return ""


def root_plugin_name_from_dir(directory: str) -> str:
    """The island's root plugin name read from its own descriptors on disk. Pure.

    ``<dir>/*.uefnproject`` ``plugins[]`` (``bIsRoot`` first), else a ``*.uplugin`` stem
    at ``<dir>`` or under ``<dir>/Plugins/*/`` (old layout). Empty when nothing is found:
    the folder name is NOT the mount (UEFN names some root plugins by a GUID).
    """
    import glob
    import json

    base = str(directory or "").strip()
    if not base or not os.path.isdir(base):
        return ""
    for desc in sorted(glob.glob(os.path.join(base, "*.uefnproject"))):
        try:
            with open(desc, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, list):
            continue
        roots = [
            str(p.get("name") or "").strip()
            for p in plugins
            if isinstance(p, dict) and p.get("bIsRoot") and str(p.get("name") or "").strip()
        ]
        others = [
            str(p.get("name") or "").strip()
            for p in plugins
            if isinstance(p, dict) and str(p.get("name") or "").strip()
        ]
        if roots:
            return roots[0]
        if others:
            return others[0]
    for pattern in ("*.uplugin", os.path.join("Plugins", "*", "*.uplugin")):
        found = sorted(glob.glob(os.path.join(base, pattern)))
        if found:
            return os.path.splitext(os.path.basename(found[0]))[0]
    return ""


def content_root() -> str:
    """Active project Content Browser mount, e.g. ``/MyProject/`` (trailing slash).

    Empty when no island map is open. Never falls back to ``Paths.project_dir()``:
    inside UEFN that is ``FortniteGame``, a mount that holds no island content, and
    create-path pins built on it landed assets outside the island.
    """
    name = mount_from_world()
    if not name:
        # Hub / unsaved level: the island's own descriptor still names its mount.
        name = root_plugin_name_from_dir(island_directory())
    return f"/{name}/" if name else ""


def pin_folder_string(folder: str, root: str, *, default_leaf: str = "Materials") -> str:
    """Pure path pin (no UE). ``root`` is ``/MyProject`` or ``/MyProject/``."""
    root = (root or "").rstrip("/")
    if not root:
        raise RuntimeError(
            "No active UEFN project content_root — open an island project before "
            "creating materials/meshes/VFX/UI assets."
        )

    f = (folder or "").strip().replace("\\", "/")
    if not f:
        return f"{root}/{default_leaf}".rstrip("/") if default_leaf else root

    while f.endswith("/") and len(f) > 1:
        f = f[:-1]

    if f == root or f.startswith(root + "/"):
        rest = f[len(root):].lstrip("/")
        collapsed = _collapsed_epic_folder(rest, root, default_leaf) if rest else ""
        return collapsed or f

    low = f.lower()
    if low == "/engine" or low.startswith("/engine/"):
        raise ValueError(f"Cannot create assets under {f!r} — use {root}/{default_leaf}/...")
    if low == "/fortnite" or low.startswith("/fortnite/"):
        raise ValueError(f"Cannot create assets under {f!r} — Fortnite gallery is read-only")

    if low == "/game":
        return f"{root}/{default_leaf}".rstrip("/") if default_leaf else root
    if low.startswith("/game/"):
        rest = f[6:]  # len("/Game/") == 6
        if not rest:
            rest = default_leaf
        collapsed = _collapsed_epic_folder(rest, root, default_leaf)
        if collapsed:
            return collapsed
        return f"{root}/{rest}".rstrip("/") if rest else root

    if not f.startswith("/"):
        return f"{root}/{f}"

    leaf_hint = default_leaf or "Materials"
    raise ValueError(
        f"Create folder {f!r} is outside project mount {root}/. "
        f"Pass {root}/{leaf_hint}/... — never invent /Game/... for new island assets "
        "(causes Disallowed reference / unsaved /Game packages)."
    )


def _collapsed_epic_folder(rest: str, root: str, default_leaf: str) -> str:
    """``Creative/BuildingActors/.../SM_X`` → ``{root}/{leaf}/SM_X``. Empty if not a gallery path."""
    first = rest.split("/", 1)[0].lower()
    if first not in _EPIC_GALLERY:
        return ""
    leaf = (default_leaf or "Imported").strip("/") or "Imported"
    last = rest.rstrip("/").rsplit("/", 1)[-1]
    if not last or last.lower() in _EPIC_GALLERY:
        return f"{root}/{leaf}"
    return f"{root}/{leaf}/{last}"


def import_destination_leaf(source_file: str) -> str:
    """Content folder for an import, from the file extension."""
    ext = os.path.splitext(source_file or "")[1].lower()
    if ext in _MESH_EXT:
        return "Meshes"
    if ext in _TEXTURE_EXT:
        return "Textures"
    if ext in _AUDIO_EXT:
        return "Audio"
    return "Imported"


def require_island_ref(path: str, root: str | None = None) -> str:
    """Allow the project mount and ``/Game/Creative``. Refuse other ``/Game`` refs.

    ponytail: prefix allowlist, not a validator run. Upgrade path is calling
    ``validate_uefn_asset`` after assigning.
    """
    p = (path or "").strip().replace("\\", "/")
    if not p:
        raise ValueError("asset path required")
    low = p.lower()
    if low == "/game/creative" or low.startswith("/game/creative/"):
        return p
    if low == "/game" or low.startswith("/game/"):
        raise ValueError(
            f"{p} fails publish (AssetReferenceRestrictions). "
            "Use a /Game/Creative material or a project material with project textures."
        )
    mount = content_root() if root is None else root
    mount = (mount or "").rstrip("/")
    if mount and (low == mount.lower() or low.startswith(mount.lower() + "/")):
        return p
    raise ValueError(
        f"{p} fails publish (AssetReferenceRestrictions). "
        "Use a /Game/Creative material or a project material with project textures."
    )


def pin_project_folder(folder: str = "", *, default_leaf: str = "Materials") -> str:
    """Return a create folder under ``content_root``, retargeting ``/Game/...``."""
    return pin_folder_string(folder, content_root(), default_leaf=default_leaf)


def pin_asset_path_string(asset_path: str, root: str, *, default_leaf: str = "Assets") -> str:
    """Pin a full asset path (``/Game/Materials/M_X`` → ``/MyProject/Materials/M_X``)."""
    p = (asset_path or "").strip().replace("\\", "/")
    if not p:
        raise ValueError("asset path required")
    # Drop object suffix: /Pkg/Name.Name → /Pkg/Name
    package = p.split(".")[0]
    while package.endswith("/") and len(package) > 1:
        package = package[:-1]
    if "/" not in package.lstrip("/"):
        # Bare name → under default_leaf
        folder = pin_folder_string("", root, default_leaf=default_leaf)
        return f"{folder}/{package.lstrip('/')}"
    folder, name = package.rsplit("/", 1)
    pinned = pin_folder_string(folder, root, default_leaf=default_leaf)
    return f"{pinned}/{name}"


def pin_project_asset_path(asset_path: str, *, default_leaf: str = "Assets") -> str:
    """Pin a create/duplicate/rename destination asset path to content_root."""
    return pin_asset_path_string(asset_path, content_root(), default_leaf=default_leaf)
