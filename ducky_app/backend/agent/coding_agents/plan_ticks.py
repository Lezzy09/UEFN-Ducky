"""Plan tick text: the exact ``ducky_plan_update_node`` call an agent should make next."""

from __future__ import annotations

from typing import Any


def next_tick_dict(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Exact ducky_plan_update_node call the agent should make next."""
    from backend.agent.coding_agents.plans import next_open_leaf

    leaf = next_open_leaf(plan)
    if not leaf:
        return None
    lab, node = leaf
    nid = str(node.get("id") or "")
    status = str(node.get("status") or "pending")
    content = str(node.get("content") or "").strip().replace("\n", " ")[:160]
    if status == "in_progress":
        action = "completed"
        call = f'ducky_plan_update_node(node_id="{nid}", status="completed")'
    else:
        action = "in_progress"
        call = f'ducky_plan_update_node(node_id="{nid}", status="in_progress")'
    return {
        "n": lab,
        "id": nid,
        "status": status,
        "content": content,
        "action": action,
        "call": call,
    }


def format_plan_tick_nudge(plan: dict[str, Any] | None) -> str:
    tick = next_tick_dict(plan)
    if not tick:
        return ""
    return (
        f"[PLAN TICK] CHECK OFF NOW: {tick['n']} `{tick['id']}` [{tick['status']}] "
        f"— {tick['content']}. Call {tick['call']} this turn. "
        "Re-check the plan every step; never leave done work pending."
    )


def attach_next_tick(payload: dict[str, Any], plan: dict[str, Any] | None) -> dict[str, Any]:
    """Add next_tick + tick_now onto a plan-tool JSON payload."""
    out = dict(payload)
    if plan and plan.get("assigned_from"):
        return out  # Read-only views must not suggest implicit own-chat writes.
    tick = next_tick_dict(plan)
    if tick:
        out["next_tick"] = tick
        out["tick_now"] = format_plan_tick_nudge(plan)
    return out
