"""UMG / Widget Blueprint tools: create, inspect, tree scaffold, MVVM bindings."""

from __future__ import annotations

from typing import Any

from backend.bridge import send_command
from backend.util.json_util import tool_json
from backend.tools.support.plugin_gate import plugin_mcp_tool


@plugin_mcp_tool("verse")
def umg_capabilities(pretty: bool = False) -> str:
    """Probe UMG / MVVM / ToolsetRegistry availability (run before other umg tools).

    Never dumps toolset JSON schemas — that crashes UEFN.
    """
    return tool_json(send_command("umg_capabilities", {}), pretty=pretty)


@plugin_mcp_tool("verse")
def list_widget_blueprints(search: str = "", offset: int = 0, limit: int = 50, pretty: bool = False) -> str:
    """List WidgetBlueprint assets in the project (filter with search, paged)."""
    return tool_json(
        send_command("list_widget_blueprints", {"search": search, "offset": offset, "limit": limit}),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def get_widget_blueprint_info(widget_path: str, pretty: bool = False) -> str:
    """Inspect a WidgetBlueprint: member vars (Verse fields), event dispatchers, tree, MVVM bindings."""
    return tool_json(send_command("get_widget_blueprint_info", {"widget_path": widget_path}), pretty=pretty)


@plugin_mcp_tool("verse")
def create_widget_blueprint(
    asset_name: str,
    folder: str = "",
    parent_class: str = "UserWidget",
    pretty: bool = False,
) -> str:
    """Create an empty WidgetBlueprint (errors if it already exists). Prefer UW_ name prefix."""
    return tool_json(
        send_command(
            "create_widget_blueprint",
            {"asset_name": asset_name, "folder": folder, "parent_class": parent_class},
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def add_widget_to_tree(
    widget_path: str,
    widget_class: str,
    widget_name: str,
    parent_ref_path: str = "",
    pretty: bool = False,
) -> str:
    """Add a widget under a panel via UMGToolSet.AddWidget. Scaffold only — polish in the designer."""
    return tool_json(
        send_command(
            "add_widget_to_tree",
            {
                "widget_path": widget_path,
                "widget_class": widget_class,
                "widget_name": widget_name,
                "parent_ref_path": parent_ref_path,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def remove_widget_from_tree(widget_path: str, widget_ref_path: str, pretty: bool = False) -> str:
    """Remove a widget instance from the tree via UMGToolSet.RemoveWidget."""
    return tool_json(
        send_command(
            "remove_widget_from_tree",
            {"widget_path": widget_path, "widget_ref_path": widget_ref_path},
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def set_widget_property(
    widget_path: str,
    target_ref_path: str,
    properties: dict[str, Any],
    list_first: bool = True,
    pretty: bool = False,
) -> str:
    """Set properties on a widget/slot via ObjectTools (list_properties first by default)."""
    return tool_json(
        send_command(
            "set_widget_property",
            {
                "widget_path": widget_path,
                "target_ref_path": target_ref_path,
                "properties": properties,
                "list_first": list_first,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_widget_bindings(widget_path: str, pretty: bool = False) -> str:
    """List MVVM view bindings on a WidgetBlueprint."""
    return tool_json(send_command("list_widget_bindings", {"widget_path": widget_path}), pretty=pretty)


@plugin_mcp_tool("verse")
def add_widget_binding(
    widget_path: str,
    source_path: str = "",
    destination_path: str = "",
    pretty: bool = False,
) -> str:
    """Add an MVVM binding (best-effort; finish complex binds in the View Bindings panel)."""
    return tool_json(
        send_command(
            "add_widget_binding",
            {
                "widget_path": widget_path,
                "source_path": source_path,
                "destination_path": destination_path,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def remove_widget_binding(widget_path: str, binding_index: int = 0, pretty: bool = False) -> str:
    """Remove an MVVM binding by index."""
    return tool_json(
        send_command(
            "remove_widget_binding",
            {"widget_path": widget_path, "binding_index": binding_index},
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_widget_classes(pretty: bool = False) -> str:
    """UEFN UMG palette (ListWidgetClasses). Call before guessing a widget class."""
    return tool_json(send_command("list_widget_classes", {}), pretty=pretty)


@plugin_mcp_tool("verse")
def get_widget_class_info(widget_class: str, pretty: bool = False) -> str:
    """Describe one widget class (panel, category). Class must exist on unreal."""
    return tool_json(
        send_command("get_widget_class_info", {"widget_class": widget_class}),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def build_widget_tree(
    tree: dict[str, Any],
    widget_path: str = "",
    asset_name: str = "",
    folder: str = "",
    pretty: bool = False,
) -> str:
    """Build a nested Widget Blueprint tree (class, name, slot, properties, children). One compile."""
    return tool_json(
        send_command(
            "build_widget_tree",
            {
                "tree": tree,
                "widget_path": widget_path,
                "asset_name": asset_name,
                "folder": folder,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def set_widget_slot(
    widget_path: str,
    widget_name: str,
    slot: dict[str, Any],
    pretty: bool = False,
) -> str:
    """Set anchors, offsets, alignment, ZOrder, padding, or grid row/column on one child."""
    return tool_json(
        send_command(
            "set_widget_slot",
            {"widget_path": widget_path, "widget_name": widget_name, "slot": slot},
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_named_slots(widget_path: str, pretty: bool = False) -> str:
    """List NamedSlot widgets on a Widget Blueprint."""
    return tool_json(send_command("list_named_slots", {"widget_path": widget_path}), pretty=pretty)


@plugin_mcp_tool("verse")
def set_named_slot_content(
    widget_path: str,
    slot_name: str,
    content_class: str = "",
    content_widget_name: str = "",
    pretty: bool = False,
) -> str:
    """Place a widget class or an existing widget into a NamedSlot."""
    return tool_json(
        send_command(
            "set_named_slot_content",
            {
                "widget_path": widget_path,
                "slot_name": slot_name,
                "content_class": content_class,
                "content_widget_name": content_widget_name,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def create_widget_animation(
    widget_path: str,
    animation_name: str,
    length_seconds: float = 1.0,
    pretty: bool = False,
) -> str:
    """Create a UWidgetAnimation on a Widget Blueprint."""
    return tool_json(
        send_command(
            "create_widget_animation",
            {
                "widget_path": widget_path,
                "animation_name": animation_name,
                "length_seconds": length_seconds,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def bind_widget_animation(
    widget_path: str,
    animation_name: str,
    widget_name: str,
    pretty: bool = False,
) -> str:
    """Possess a widget on an animation so tracks can key it."""
    return tool_json(
        send_command(
            "bind_widget_animation",
            {
                "widget_path": widget_path,
                "animation_name": animation_name,
                "widget_name": widget_name,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def add_animation_keys(
    widget_path: str,
    animation_name: str,
    widget_name: str,
    track_type: str,
    keys: list[dict[str, Any]],
    channel: str = "",
    pretty: bool = False,
) -> str:
    """Key Opacity, Color (R/G/B/A), or Transform channels. keys are {time, value} in seconds."""
    return tool_json(
        send_command(
            "add_animation_keys",
            {
                "widget_path": widget_path,
                "animation_name": animation_name,
                "widget_name": widget_name,
                "track_type": track_type,
                "keys": keys,
                "channel": channel,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_widget_animations(widget_path: str, pretty: bool = False) -> str:
    """List animations with track names and key counts."""
    return tool_json(send_command("list_widget_animations", {"widget_path": widget_path}), pretty=pretty)


@plugin_mcp_tool("verse")
def add_verse_field(
    widget_path: str,
    field_name: str,
    field_type: str,
    default_value: str = "",
    pretty: bool = False,
) -> str:
    """Add a Verse field (logic, int, float, message, material, texture, color, event)."""
    return tool_json(
        send_command(
            "add_verse_field",
            {
                "widget_path": widget_path,
                "field_name": field_name,
                "field_type": field_type,
                "default_value": default_value,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_verse_fields(widget_path: str, pretty: bool = False) -> str:
    """List Verse fields on a Widget Blueprint."""
    return tool_json(send_command("list_verse_fields", {"widget_path": widget_path}), pretty=pretty)


@plugin_mcp_tool("verse")
def bind_verse_field(
    widget_path: str,
    source_field: str,
    widget_name: str,
    destination_property: str,
    conversion_name: str = "",
    pretty: bool = False,
) -> str:
    """Bind a Verse field on the widget blueprint to a child widget property."""
    return tool_json(
        send_command(
            "bind_verse_field",
            {
                "widget_path": widget_path,
                "source_field": source_field,
                "widget_name": widget_name,
                "destination_property": destination_property,
                "conversion_name": conversion_name,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def bind_widget_event(
    widget_path: str,
    widget_name: str,
    event_name: str,
    destination_field: str,
    pretty: bool = False,
) -> str:
    """Bind OnClicked / OnHighlight / OnUnhighlight to a Verse event field."""
    return tool_json(
        send_command(
            "bind_widget_event",
            {
                "widget_path": widget_path,
                "widget_name": widget_name,
                "event_name": event_name,
                "destination_field": destination_field,
            },
        ),
        pretty=pretty,
    )


@plugin_mcp_tool("verse")
def list_bindable_properties(widget_path: str, widget_name: str, pretty: bool = False) -> str:
    """Property paths on one widget that View Bindings can target."""
    return tool_json(
        send_command(
            "list_bindable_properties",
            {"widget_path": widget_path, "widget_name": widget_name},
        ),
        pretty=pretty,
    )
