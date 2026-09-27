"""Invented MCP names map onto one registered tool, or onto none."""

from backend.agent.tools import resolve_invented_tool_name

_KNOWN = {"ducky_get_status", "blender_get_scene_info", "blender__read_image", "other_get_scene_info"}


def test_uefn_prefix_is_the_ducky_tool_itself() -> None:
    assert resolve_invented_tool_name("mcp__uefn__ducky_get_status", _KNOWN) == "ducky_get_status"


def test_mcp_dunder_prefix_becomes_flat_name() -> None:
    assert resolve_invented_tool_name("mcp__blender__read_image", _KNOWN) == "blender__read_image"


def test_hyphenated_tail_matches_one_registered_name() -> None:
    known = {"ducky_get_status", "blender_get_scene_info"}
    assert (
        resolve_invented_tool_name("mcp-blender-mcp-get_scene_info", known)
        == "blender_get_scene_info"
    )


def test_two_tails_is_no_match() -> None:
    assert resolve_invented_tool_name("mcp-blender-mcp-get_scene_info", _KNOWN) is None


def test_missing_and_junk_names_do_not_guess() -> None:
    assert resolve_invented_tool_name("mcp__uefn__missing", _KNOWN) is None
    assert resolve_invented_tool_name("computer", _KNOWN) is None
    assert resolve_invented_tool_name("computer_use", _KNOWN) is None
    assert resolve_invented_tool_name("vision_analyze", _KNOWN) is None
    assert resolve_invented_tool_name("blender_get_scene_info", _KNOWN) is None
