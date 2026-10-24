"""Plan review: the written protocol for plans and the check for steps a person can't follow."""

from __future__ import annotations

import re
from typing import Any

# Single copy of the Diagnose→Fix→Verify protocol (prompt / MCP / BYOA / modes).
PLAN_PROTOCOL = (
    "Followable `nodes`: Diagnose → Fix → Verify. Size each leaf as ONE outcome one agent "
    "finishes in about 15–30 minutes; a step covering several features or checks (all, every, "
    "end to end) becomes one step per feature or check, so progress shows and a blocker names "
    "itself. Each leaf: `content` = a short title in plain words (under 80 characters); "
    "`body_markdown` = its description: what to do, Done when (name the check tool) and one "
    "concrete example of the result. Give each section a one-line description too. "
    "`ducky_plan_update_node` `in_progress` BEFORE the work, in the same turn ahead of the "
    "work's calls (a turn's calls run in order), never a turn of its own; "
    "`completed` when Done-when is met. Mutators are blocked until a leaf is "
    "in_progress. If the approach changes, update the tree before more mutators — "
    "never thrash off-plan. Team plans: ONE main plan, the lead's, with one sub plan per agent "
    "(a section whose `assignee` is that agent) holding that agent's points; members never make "
    "plans of their own. The agent ticks its points; ticking the last one checks its sub plan off "
    "in the main plan and tells the lead, so nobody sends reports. A sub plan's description says "
    "Files (what it may change), Done when (the change and its tests, never evidence files, "
    "read-backs or live checks only the person can do) and Not yours (what to leave to others); `after` = ids "
    "of steps or sub plans that must finish first. Templates: `ducky_create_plan_template` / "
    "`ducky_instantiate_plan_template`. Plan mode: create/update then stop."
)

_TITLE_MAX = 100
_BIG_STEP_RE = re.compile(r"\b(all|every|everything|end[ -]to[ -]end|whole)\b", re.IGNORECASE)
_REVIEW_MAX = 8


def plan_review(plan: dict[str, Any] | None) -> list[dict[str, str]]:
    """Open steps a person can't follow: too big to show progress, or with no description.

    A team kept one step ("check all original feature paths end to end") open for two hours
    while fifteen checks inside it passed one by one; the plan read 15/19 the whole time.
    """
    from backend.agent.coding_agents.plans import _DONE, _flatten_nodes, outline_numbers

    issues: list[dict[str, str]] = []
    flat = _flatten_nodes((plan or {}).get("nodes"))
    known = {str(n.get("id")) for n in flat}
    # A team plan (any step has an owner): an open step nobody owns is work nobody does.
    team = any(n.get("assignee") for n in flat)
    owned_sections = {str(c.get("id")) for n in flat if n.get("assignee")
                      for c in _flatten_nodes(n.get("children") or [])}
    # An agent with several loose steps at the top: they belong in one sub plan assigned to it,
    # so the agent works through its points and the lead hears once, when the sub plan is done.
    loose: dict[str, int] = {}
    for node in (plan or {}).get("nodes") or []:
        if node.get("assignee") and not node.get("children") and node.get("status") not in _DONE:
            loose[str(node["assignee"])] = loose.get(str(node["assignee"]), 0) + 1
    for owner, count in loose.items():
        if count > 1:
            issues.append({"n": "-", "issue": f"{count} top-level steps are assigned to {owner}: put them in one "
                                              "sub plan assigned to that agent (its points inside)."})
    for label, node in outline_numbers((plan or {}).get("nodes")):
        if node.get("status") in _DONE:
            continue
        unknown = [sid for sid in node.get("after") or [] if sid not in known]
        if unknown:
            issues.append({"n": label, "issue": f"Waits for steps that don't exist ({', '.join(unknown)}): use ids from the outline."})
        if team and not node.get("children") and not node.get("assignee") and str(node.get("id")) not in owned_sections:
            issues.append({"n": label, "issue": "No owner: set its assignee to the member who does it."})
        content = str(node.get("content") or "").strip()
        described = bool(str(node.get("body_markdown") or "").strip())
        if node.get("children"):
            if not described:
                issues.append({"n": label, "issue": "Section has no description: add one line saying what it delivers."})
            continue
        if _BIG_STEP_RE.search(content):
            issues.append({"n": label, "issue": "Too big for one step: split it into one step per feature or check."})
        elif len(content) > _TITLE_MAX:
            issues.append({"n": label, "issue": "Title too long: keep it short and move the details into its description."})
        if not described:
            issues.append({"n": label, "issue": "No description: say what to do, Done when, and one example of the result."})
        if len(issues) >= _REVIEW_MAX:
            break
    return issues


def with_plan_review(payload: dict[str, Any], plan: dict[str, Any] | None) -> dict[str, Any]:
    """Add ``plan_review`` to a tool result that wrote steps, when any step needs fixing."""
    issues = plan_review(plan)
    if not issues:
        return payload
    return {**payload, "plan_review": issues,
            "plan_review_hint": "Fix these with ducky_update_plan or ducky_plan_update_node before starting the work."}
