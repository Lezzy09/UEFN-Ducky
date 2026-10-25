"""Importing backend.tools registers ducky_finish_team (it was written but never imported)."""

from __future__ import annotations


def test_finish_team_tool_registers():
    import backend.tools  # noqa: F401
    from backend.server import mcp
    from backend.tools.panel import ducky_finish_team

    assert mcp._tool_manager._tools["ducky_finish_team"].fn is ducky_finish_team.ducky_finish_team
