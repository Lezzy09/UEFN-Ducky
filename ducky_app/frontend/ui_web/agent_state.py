"""One plain state per running agent, so a lead waiting on a question or a terminal call
waiting for its Allow card never looks stuck.

Reads in-process structures only (no panel RPC: this runs inside the app), checked in
this order: ``needs_answer``, ``needs_approval``, ``running_command`` (a Ducky tool
running over 30 s, named), ``working`` (output in the last 60 s), ``silent``.
"""

from __future__ import annotations

import time
from typing import Any

TOOL_SLOW_S = 30.0
OUTPUT_FRESH_S = 60.0


def _call(module: Any, name: str, *args: Any) -> Any:
    """An accessor of another lane; None while it does not exist yet or fails."""
    fn = getattr(module, name, None)
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001 - a meter never breaks ducky_health
        return None


def _question(conv_id: str) -> dict[str, Any] | None:
    from frontend.ui_web import ui_rpc

    found = _call(ui_rpc, "pending_question", conv_id)  # {"prompt", "age_s"}
    if found:
        return found
    if not _call(ui_rpc, "has_pending_for_conv", conv_id):
        return None
    for row in _call(ui_rpc, "pending_questions") or []:
        params = row.get("params") or {}
        if str(params.get("conv_id") or "") == conv_id:
            first = (params.get("questions") or [{}])[0]
            return {"prompt": str(first.get("prompt") or ""), "age_s": None}
    return {"prompt": "", "age_s": None}


def _approval(conv_id: str) -> dict[str, Any] | None:
    from frontend.ui_web.terminal import get_terminal_manager

    rows = _call(get_terminal_manager(), "list_pending") or []
    for row in rows:  # oldest first
        if conv_id in (row.get("conv_id"), row.get("lead_conv_id")):
            return row
    return None


def classify(question: dict[str, Any] | None, approval: dict[str, Any] | None, tool: dict[str, Any] | None,
             output_age_s: float | None, now: float | None = None) -> dict[str, Any]:
    """The state from the facts: ``{state, since_s, detail}``."""
    now = time.time() if now is None else now

    def secs(value: Any) -> int | None:
        return None if value is None else int(round(float(value)))

    if question is not None:
        return {"state": "needs_answer", "since_s": secs(question.get("age_s")), "detail": question.get("prompt") or ""}
    if approval is not None:
        created = approval.get("created_at")
        return {"state": "needs_approval", "since_s": secs(now - float(created)) if created else None,
                "detail": str(approval.get("command") or "")[:200]}
    if tool is not None and float(tool.get("age_s") or 0) > TOOL_SLOW_S:
        return {"state": "running_command", "since_s": secs(tool["age_s"]), "detail": str(tool.get("tool") or "")}
    if output_age_s is not None and output_age_s <= OUTPUT_FRESH_S:
        return {"state": "working", "since_s": secs(output_age_s), "detail": ""}
    return {"state": "silent", "since_s": secs(output_age_s), "detail": ""}


def agent_state(conv_id: str) -> dict[str, Any]:
    from frontend.ui_web import agent_modes

    cid = (conv_id or "").strip()
    return classify(_question(cid), _approval(cid),
                    _call(agent_modes, "running_tool", cid),  # {"tool", "age_s"}
                    _call(agent_modes, "last_output_age_s", cid))


def running_agents() -> list[dict[str, Any]]:
    """Every running agent with its state, ones that need the person first."""
    from frontend.ui_web.agent_modes import list_running_agents

    order = {"needs_answer": 0, "needs_approval": 1, "running_command": 2, "silent": 3, "working": 4}
    rows = [{"id": cid, **agent_state(cid)} for cid in list_running_agents()]
    return sorted(rows, key=lambda r: order.get(r["state"], 9))
