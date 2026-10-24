"""Compact JSON serialization for MCP tool responses."""

from __future__ import annotations

import json
from typing import Any


def _without_empty(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _without_empty(v) for k, v in obj.items() if v is not None and v != "" and v != [] and v != {}}
    return obj


def tool_json(obj: Any, *, pretty: bool = False, drop_empty: bool = False) -> str:
    """Serialize tool output; compact by default to reduce token usage.

    ``drop_empty`` leaves out top-level and nested dict fields that are None, "", [] or {}.
    """
    return json.dumps(
        _without_empty(obj) if drop_empty else obj,
        separators=(",", ":"),
        ensure_ascii=False,
        indent=2 if pretty else None,
    )
