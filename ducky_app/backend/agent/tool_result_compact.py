"""Shared tool-result size limits (no MCP / serialization imports)."""
from __future__ import annotations

# What the model sees of one tool result. It must hold a whole tool schema, a skill
# section and a spill page (tool_spills.READ_MAX_CHARS; the json format escapes a page
# twice): at 2,200 a 10k skill section arrived as 1k and spill pages were cut, so the
# agent re-read the same thing over and over (Oct 20 2026: 73 requests to file 3 workflows).
API_TOOL_RESULT_MAX = 16_000
# Tools whose payload IS the deliverable get a bigger budget.
TOOL_RESULT_MAX_OVERRIDES = {
    "web_search": 80_000,
    "web_fetch": 80_000,
    "web_video": 80_000,
    "web_github": 80_000,
    "sandbox_run": 60_000,
    "sandbox_look": 40_000,
    "sandbox_mcp": 60_000,
    "ducky_health": 40_000,
}


def tool_result_max(tool_name: str) -> int:
    return TOOL_RESULT_MAX_OVERRIDES.get(tool_name, API_TOOL_RESULT_MAX)
