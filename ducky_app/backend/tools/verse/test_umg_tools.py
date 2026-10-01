"""The typed UMG tools are registered (not listener passthroughs that take one `params` dict)."""

from __future__ import annotations

import asyncio

import backend.tools  # noqa: F401  (registers every app tool)
from backend.server import mcp

UMG_TOOLS = (
    "add_verse_field", "edit_verse_field", "remove_verse_field", "duplicate_verse_field",
    "list_verse_field_types", "list_verse_fields", "bind_verse_field", "bind_widget_event",
    "build_widget_tree", "set_widget_slot", "list_named_slots", "create_widget_animation",
)


def test_umg_tools_take_flat_arguments() -> None:
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in UMG_TOOLS:
        assert name in tools, name
        props = (tools[name].inputSchema or {}).get("properties") or {}
        assert "params" not in props, f"{name} is a passthrough"
    assert {"widget_path", "field_name", "field_type", "event_parameters"} <= set(tools["add_verse_field"].inputSchema["properties"])
    assert "mode" in tools["bind_verse_field"].inputSchema["properties"]
