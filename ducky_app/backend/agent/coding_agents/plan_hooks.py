"""What runs when plan steps complete: the tick check, completion reports, and the pushes
that tell each owner's chat to re-read its part of the plan (which starts a member's turn).

``plans.py`` calls these; it never decides who hears about a completion itself.
"""

from __future__ import annotations

from typing import Any


def before_complete(plan: dict[str, Any], node: dict[str, Any], chat_id: str) -> None:
    """Runs before ``node`` is ticked completed by ``chat_id``; raise ValueError to refuse."""
    return None


def on_step_completed(plan: dict[str, Any], node: dict[str, Any]) -> None:
    """Runs after a saved plan has ``node`` (a leaf) newly completed."""
    return None


def on_section_completed(plan: dict[str, Any], node: dict[str, Any]) -> None:
    """Runs after a saved plan has ``node`` (a section) newly completed."""
    return None


def completion_reports(previous: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, str]]:
    """The lead's reports for what this save finished (stored on the plan before it is written)."""
    from backend.agent.coding_agents.team_plan_events import completion_reports as reports

    return reports(previous, plan)


def after_save(previous: dict[str, Any], plan: dict[str, Any], reports: list[dict[str, str]],
               project_root: str | None) -> None:
    """Side work of a written plan: acknowledge the lead's own change, send the reports,
    then the per-node completion hooks, steps before the sections they closed."""
    from backend.agent.a2a_client import acknowledge_saved_plan
    from backend.agent.coding_agents.plans import _flatten_nodes
    from backend.agent.coding_agents.team_plan_events import deliver_reports

    acknowledge_saved_plan(previous, plan, project_root)
    deliver_reports(plan, reports)
    was = {str(n.get("id")): n.get("status") for n in _flatten_nodes(previous.get("nodes"))}
    done = [n for n in _flatten_nodes(plan.get("nodes"))
            if n.get("status") == "completed" and was.get(str(n.get("id"))) != "completed"]
    for node in done:
        if not node.get("children"):
            on_step_completed(plan, node)
    for node in reversed(done):
        if node.get("children"):
            on_section_completed(plan, node)


def _section_audience(owners: set[str], project_root: str | None) -> set[str]:
    """Every chat that owns a part of the plan: the owners, chats filed under an owning group
    at any depth, and an owning group's roster and leader (a lead seated with as_leader stays
    filed in the outer group). Reads chat metadata only: walking parents with load_conversation
    loaded every chat's whole history on each tick (4-15 s per tick on Oct 24 2026)."""
    from frontend.ui_web.group_orchestrator import group_members
    from frontend.ui_web.project_chats import list_all_conversation_metadata

    convs = {str(getattr(c, "id", "")): c for c in list_all_conversation_metadata(project_root)}
    out = set(owners)
    for cid in convs:
        cur, seen = cid, set()
        while cur and cur not in seen and cur in convs:
            if cur in owners:
                out.add(cid)
                break
            seen.add(cur)
            cur = str(getattr(convs[cur], "parent_conv_id", "") or "").strip()
    for gid in owners.intersection(convs):
        group = convs[gid]
        if getattr(group, "is_group", False):
            out.add(str(getattr(group, "leader_conv_id", "") or ""))
            out.update(m["member_conv_id"] for m in group_members(group))
    out.discard("")
    return out


def _push_assignment_invalidated(before: dict[str, Any], after: dict[str, Any],
                                 project_root: str | None) -> None:
    """Tell every chat that owns a part of this plan to re-read its section of the ONE plan,
    without sending the lead's plan body: ``plan_assignment_changed`` when owners changed, else
    ``plan_updated`` (a tick), so each member's plan bar moves with the lead's."""
    from backend.agent.coding_agents.plans import _flatten_nodes

    def owners(doc: dict[str, Any]) -> dict[str, str]:
        return {str(n["id"]): str(n["assignee"]) for n in _flatten_nodes(doc.get("nodes")) if n.get("assignee")}

    was, now = owners(before), owners(after)
    if not was and not now:
        return
    try:
        from frontend.ui_web.agent_modes import _resolve_push

        changed = was != now
        recipients = _section_audience(set(was.values()) | set(now.values()) if changed else set(now.values()),
                                       project_root)
        push = _resolve_push(None)
        for cid in sorted(recipients - {str(after.get("chat_id") or "")}):
            if changed:
                push({"type": "plan_assignment_changed", "conv_id": cid})
            else:
                push({"type": "plan_updated", "conv_id": cid, "plan_id": str(after.get("id") or "")})
    except Exception:
        # Saving the authoritative document must not depend on a UI connection.
        pass
