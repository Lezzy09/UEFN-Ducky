"""Project metadata, level save/info, viewport camera, revision control push/pull."""

from __future__ import annotations

import time
from typing import Any, Optional

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("uefn")
def get_project_info(pretty: bool = False) -> str:
    """Get project name and content root (often /{ProjectName}/, not /Game/)."""
    result = send_command("get_project_info")
    return tool_json(result, pretty=pretty)


@plugin_mcp_tool("uefn")
def save_current_level(pretty: bool = False) -> str:
    """Save the current level. Never behind an open Save/Checkout popup (dismiss_uefn_modal)."""
    result = send_command("save_current_level")
    return tool_json(result, pretty=pretty)


@plugin_mcp_tool("uefn")
def get_level_info(pretty: bool = False) -> str:
    """Get the current level name and actor count. Not an actor list (get_all_actors)."""
    result = send_command("get_level_info")
    return tool_json(result, pretty=pretty)


@plugin_mcp_tool("uefn")
def get_viewport_camera(pretty: bool = False) -> str:
    """Get the viewport camera position and rotation. Does not move it."""
    result = send_command("get_viewport_camera")
    return tool_json(result, pretty=pretty)


@plugin_mcp_tool("uefn")
def set_viewport_camera(
    location: Optional[list[float]] = None,
    rotation: Optional[list[float]] = None,
    pretty: bool = False,
) -> str:
    """Move the viewport camera. Never moves actors."""
    params: dict[str, Any] = {}
    if location is not None:
        params["location"] = location
    if rotation is not None:
        params["rotation"] = rotation
    result = send_command("set_viewport_camera", params)
    return tool_json(result, pretty=pretty)


# Saving, checking in and syncing run on the editor thread; a big island takes a while.
_REVISION_TIMEOUT = 180.0
_CHECK_IN_RETRIES = 2
_CHECK_IN_RETRY_WAIT_S = 3.0


def _lore_cli():
    from frontend.ui_web.verse_editor.urc import lore_cli

    return lore_cli


def _island_root() -> str:
    # The island UEFN has open, not the project picked in Ducky: they can differ, and
    # Lore must read the repository the editor will check in to.
    island = str(send_command("revision_status").get("island") or "")
    return island.replace("/", "\\").rstrip("\\") if island else ""


def _remote_state(state: dict) -> dict:
    return {k: state.get(k) for k in ("in_sync", "behind", "ahead")}


@plugin_mcp_tool("uefn")
def revision_push(description: str, pretty: bool = False) -> str:
    """Save the island and push every change not yet on the remote (Unreal Revision Control). Never without a description."""
    if not (description or "").strip():
        return tool_json({"ok": False, "error": "description is required (the check-in message)"}, pretty=pretty)
    root = _island_root()
    if not root:
        return tool_json({"ok": False, "error": "UEFN has no island open"}, pretty=pretty)
    lore = _lore_cli()
    pending = lore.pending_paths(root)
    if not pending.get("ok"):
        return tool_json({"ok": False, "error": pending.get("error") or "could not list pending files"}, pretty=pretty)
    result = send_command(
        "revision_check_in",
        {"files": list(pending.get("paths") or []), "description": description},
        timeout=_REVISION_TIMEOUT,
    )
    saved = result.get("saved") or []
    # Right after a save UEFN is still backing it up on its personal branch, and a
    # check-in made then fails with no message; the same check-in passes seconds later.
    for _ in range(_CHECK_IN_RETRIES):
        if result.get("ok") or not saved or not result.get("targets"):
            break
        time.sleep(_CHECK_IN_RETRY_WAIT_S)
        result = send_command(
            "revision_check_in",
            {"files": list(result["targets"]), "description": description},
            timeout=_REVISION_TIMEOUT,
        )
    state = lore.repo_state(root)
    return tool_json(
        {
            "ok": bool(result.get("ok")),
            "checked_in": len(result.get("checked_in") or []),
            "saved": len(saved),
            **_remote_state(state),
            "error": result.get("error") or state.get("error") or "",
        },
        pretty=pretty,
    )


@plugin_mcp_tool("uefn")
def revision_pull(force: bool = False, pretty: bool = False) -> str:
    """Pull the remote's changes into the island and reload the map. Never force over unsaved work without asking the person."""
    root = _island_root()
    if not root:
        return tool_json({"ok": False, "error": "UEFN has no island open"}, pretty=pretty)
    lore = _lore_cli()
    before = lore.repo_state(root)
    if not before.get("ok"):
        return tool_json({"ok": False, "error": before.get("error") or "could not read the repository"}, pretty=pretty)
    if not before.get("behind"):
        return tool_json({"ok": True, "up_to_date": True, **_remote_state(before)}, pretty=pretty)
    result = send_command("revision_sync", {"force": bool(force)}, timeout=_REVISION_TIMEOUT)
    if result.get("needs_save"):
        return tool_json(
            {
                "ok": False,
                "needs_save": result["needs_save"],
                "error": "UEFN has unsaved changes: ask the person to push them first (revision_push) "
                "or to pull anyway (force=true, the map is then not reloaded)",
            },
            pretty=pretty,
        )
    after = lore.repo_state(root)
    return tool_json(
        {
            "ok": bool(result.get("ok")),
            "reloaded": bool(result.get("reloaded")),
            "seconds": result.get("seconds"),
            **_remote_state(after),
            "error": result.get("error") or after.get("error") or "",
        },
        pretty=pretty,
    )
