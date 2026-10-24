"""Ducky tools a coding agent gets up front, without a ToolSearch round trip.

Claude Code defers every MCP tool behind tool search by default. A tool whose
``tools/list`` entry carries ``_meta["anthropic/alwaysLoad"] = true`` loads up front
instead (Claude Code v2.1.285+), while the rest of the ~1,000 Ducky tools stay
deferred: https://code.claude.com/docs/en/mcp#mark-a-tool-to-load-upfront-or-stay-deferred
A server-level ``alwaysLoad`` in the MCP config would load all of them, so the
config leaves it unset. Clients without tool search ignore the key.
"""

from __future__ import annotations

from typing import Any

ALWAYS_LOAD_META_KEY = "anthropic/alwaysLoad"

CORE_TOOLS: tuple[str, ...] = (
    "workspace_read_file",
    "workspace_read_files",
    "workspace_edit_file",
    "workspace_multi_edit",
    "workspace_replace_lines",
    "workspace_write_file",
    "workspace_find",
    "workspace_search",
    "workspace_git",
    "ducky_terminal_open",
    "ducky_terminal_run",
    "ducky_ask_user",
    "ducky_plan_update_node",
    "ducky_rename_self",
    "view_image",
)


def mark_always_load(mcp: Any, names: tuple[str, ...] = CORE_TOOLS) -> list[str]:
    """Set the always-load flag on the registered tools named in *names*; returns those marked."""
    tools = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
    if not isinstance(tools, dict):
        return []
    marked: list[str] = []
    for name in names:
        tool = tools.get(name)
        if tool is None:
            continue
        meta = getattr(tool, "meta", None) or {}
        if meta.get(ALWAYS_LOAD_META_KEY) is not True:
            # A new dict, never an in-place edit: the catalog watcher keys on object ids.
            tool.meta = {**meta, ALWAYS_LOAD_META_KEY: True}
        marked.append(name)
    return marked
