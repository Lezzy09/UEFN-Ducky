"""Introspection tools: discover the unreal API before writing execute_python."""

from __future__ import annotations

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("uefn")
def describe_class(class_name: str, max_members: int = 200, pretty: bool = False) -> str:
    """List methods, attributes and base classes of an unreal or Verse class. Never calls or edits it."""
    return tool_json(send_command("describe_class", {"class_name": class_name, "max_members": max_members}), pretty=pretty)


@plugin_mcp_tool("uefn")
def search_unreal_api(query: str, max_results: int = 60, pretty: bool = False) -> str:
    """Find names in the unreal Python module containing query. Not Verse APIs (search_verse_digest)."""
    return tool_json(send_command("search_unreal_api", {"query": query, "max_results": max_results}), pretty=pretty)


@plugin_mcp_tool("uefn")
def list_subsystems(pretty: bool = False) -> str:
    """List unreal classes whose name ends with Subsystem. Read-only: never instantiates them."""
    return tool_json(send_command("list_subsystems", {}), pretty=pretty)


@plugin_mcp_tool("uefn")
def list_actor_classes(prefix: str = "", max_results: int = 200, pretty: bool = False) -> str:
    """List unreal Actor-derived classes (prefix filter). Not placed actors (get_all_actors)."""
    return tool_json(send_command("list_actor_classes", {"prefix": prefix, "max_results": max_results}), pretty=pretty)
