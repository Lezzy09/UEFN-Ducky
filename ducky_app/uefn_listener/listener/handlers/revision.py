"""Unreal Revision Control (Lore): push saved island changes, pull the remote.

The host works out *which* files are not on the remote yet (``lore_cli`` runs in the
Ducky process: no subprocess on the editor thread). These commands only do what has
to happen inside UEFN: save, check in, sync, reload the map.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

import unreal

from listener.dispatch import register
from listener.project_paths import content_root, island_directory


def _dirty_packages() -> list:
    utils = unreal.EditorLoadingAndSavingUtils
    return list(utils.get_dirty_content_packages() or []) + list(utils.get_dirty_map_packages() or [])


def _names(packages) -> List[str]:
    return [str(p.get_name()) for p in packages]


def _last_error() -> str:
    try:
        return str(unreal.SourceControl.last_error_msg() or "")
    except Exception:
        return ""


@register("revision_status")
def cmd_revision_status() -> dict:
    """The open island's folder, its unsaved packages and the revision control provider. Never touches the network."""
    sc = unreal.SourceControl
    return {
        "island": island_directory() or "",
        "dirty": _names(_dirty_packages()),
        "provider": str(sc.current_provider() or ""),
        "available": bool(sc.is_available()),
    }


@register("revision_check_in")
def cmd_revision_check_in(files: Optional[List[str]] = None, description: str = "") -> dict:
    """Save every dirty package, then check ``files`` plus the island's saved packages in.

    Pushes to the remote with no dialog. ``files`` come from the host (lore_cli).
    """
    if not str(description or "").strip():
        raise ValueError("description must not be empty (it is the check-in message)")
    packages = _dirty_packages()
    saved = _names(packages)
    if packages and not unreal.EditorLoadingAndSavingUtils.save_packages(packages, True):
        return {"ok": False, "checked_in": [], "saved": [], "error": "saving the dirty packages failed"}
    # Only the island's own packages can be checked in (not /Temp, not Fortnite's).
    mount = content_root()
    own = [n for n in saved if not mount or n.startswith(mount)]
    targets = list(dict.fromkeys([*(files or []), *own]))
    if not targets:
        return {"ok": True, "checked_in": [], "saved": saved, "error": ""}
    ok = bool(unreal.SourceControl.check_in_files(targets, str(description), True))
    return {
        "ok": ok,
        "targets": targets,
        "checked_in": targets if ok else [],
        "saved": saved,
        "error": "" if ok else _last_error() or "check-in failed",
    }


@register("revision_sync")
def cmd_revision_sync(force: bool = False, reload: bool = True) -> dict:
    """Pull the remote into the island, then reload the open map to show the changes.

    A loaded actor keeps its file open, so Lore can't overwrite it: the map is swapped
    for a blank one during the sync, then opened again. Refuses (does nothing) while
    packages are unsaved, unless ``force``; even then it never unloads or reloads over
    unsaved work (only files that aren't loaded arrive then).
    """
    dirty = _names(_dirty_packages())
    if dirty and not force:
        return {"ok": False, "needs_save": dirty, "synced": False, "reloaded": False, "error": ""}
    island = island_directory()
    content = os.path.join(island, "Content") if island else ""
    if not content or not os.path.isdir(content):
        return {"ok": False, "synced": False, "reloaded": False, "error": f"island Content folder not found: {island!r}"}
    import glob

    # The island's descriptors sit beside Content/ and change too (.uefnproject lists plugins).
    targets = [content.replace("\\", "/") + "/"]
    for pattern in ("*.uefnproject", "*.uplugin"):
        targets += [p.replace("\\", "/") for p in sorted(glob.glob(os.path.join(island, pattern)))]
    started = time.time()
    world = unreal.EditorLevelLibrary.get_editor_world()
    map_path = str(world.get_path_name()).split(".", 1)[0] if world else ""
    release = bool(reload and not dirty and map_path)
    if release and not unreal.EditorLoadingAndSavingUtils.new_blank_map(False):
        return {"ok": False, "synced": False, "reloaded": False, "seconds": round(time.time() - started, 2),
                "error": "could not close the map before syncing"}
    synced = bool(unreal.SourceControl.sync_files(targets, True))
    error = "" if synced else _last_error() or "sync failed"
    # Open the map again even after a failed sync: the person must never be left on the blank one.
    reloaded = bool(unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(map_path)) if release else False
    return {
        "ok": synced,
        "synced": synced,
        "reloaded": reloaded,
        "dirty": dirty,
        "seconds": round(time.time() - started, 2),
        "error": error,
    }
