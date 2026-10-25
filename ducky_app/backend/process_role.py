"""What this Ducky process is: ``app`` (the window), ``tool_server`` (an MCP bridge) or
``agent_host`` (a supervisor child that runs agent turns).

Work only the window should do (pollers, presence, sync rounds, crash heal) checks
``role() == "app"``; "an agent made this" checks treat any other role as an agent.
"""

from __future__ import annotations

import os

ENV = "UEFN_DUCKY_PROCESS_ROLE"
ROLES = ("app", "tool_server", "agent_host")


def role() -> str:
    value = os.environ.get(ENV, "").strip()
    if value in ROLES:
        return value
    return "tool_server" if os.environ.get("UEFN_DUCKY_MCP_BRIDGE") == "1" else "app"


def set_role(value: str) -> None:
    """Set before anything that checks it is imported."""
    if value not in ROLES:
        raise ValueError(f"unknown process role: {value}")
    os.environ[ENV] = value
    if value == "tool_server":
        os.environ["UEFN_DUCKY_MCP_BRIDGE"] = "1"


def is_app() -> bool:
    return role() == "app"
