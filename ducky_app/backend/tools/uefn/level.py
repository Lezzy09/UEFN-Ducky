"""Level tools: duplicate, organize, and query level actors."""

from __future__ import annotations

from typing import Optional

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("uefn")
def duplicate_actor(actor_path: str, location_offset: Optional[list[float]] = None, pretty: bool = False) -> str:
    """Duplicate a placed actor, optionally offset by [x,y,z]. Never a second Verse device copy (_v2)."""
    return tool_json(send_command("duplicate_actor", {"actor_path": actor_path, "location_offset": location_offset}), pretty=pretty)


@plugin_mcp_tool("uefn")
def set_actor_folder(actor_path: str, folder: str, pretty: bool = False) -> str:
    """Move an actor into a World Outliner folder. Does not move it in the level."""
    return tool_json(send_command("set_actor_folder", {"actor_path": actor_path, "folder": folder}), pretty=pretty)


@plugin_mcp_tool("uefn")
def set_actor_label(actor_path: str, label: str, pretty: bool = False) -> str:
    """Rename an actor's Outliner label. Does not rename its asset."""
    return tool_json(send_command("set_actor_label", {"actor_path": actor_path, "label": label}), pretty=pretty)


@plugin_mcp_tool("uefn")
def set_actor_tags(actor_path: str, tags: list[str], pretty: bool = False) -> str:
    """Replace an actor's gameplay tags with the whole list given (not an append)."""
    return tool_json(send_command("set_actor_tags", {"actor_path": actor_path, "tags": tags}), pretty=pretty)


@plugin_mcp_tool("uefn")
def get_actors_in_radius(center: list[float], radius: float, class_filter: str = "", pretty: bool = False) -> str:
    """List actors within radius of a world point [x,y,z]. Not a full census (get_all_actors)."""
    return tool_json(send_command("get_actors_in_radius", {"center": center, "radius": radius, "class_filter": class_filter}), pretty=pretty)


@plugin_mcp_tool("uefn")
def attach_actor(child_path: str, parent_path: str, socket: str = "", rule: str = "keep_world", pretty: bool = False) -> str:
    """Attach one actor to another, optionally at a socket/bone. Does not move it unless rule snaps.

    rule="snap_to_target" jumps the child onto the socket/bone (put a prop on a
    skeleton socket); default "keep_world" leaves it in place and it follows.
    """
    return tool_json(send_command("attach_actor", {"child_path": child_path, "parent_path": parent_path, "socket": socket, "rule": rule}), pretty=pretty)


@plugin_mcp_tool("uefn")
def list_actor_components(actor_path: str, pretty: bool = False) -> str:
    """List a placed actor's components (name, class, mesh, parent/socket). Never probe Blueprint CDOs."""
    return tool_json(send_command("list_actor_components", {"actor_path": actor_path}), pretty=pretty)
