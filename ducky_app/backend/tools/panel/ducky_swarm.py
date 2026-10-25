"""ducky_swarm_create: one call builds a whole swarm from a goal and its jobs.

Ask once (agent count, size limits, a model per job) → route each job to a template and
model → preview the tree → build it plan-first (sub plans and steps, then groups and seats
with their lanes, then assign). Every step before ``confirm=true`` is pure and builds
nothing, so the same arguments always give the same preview.

The preview lives in ``swarm_preview`` (payload fields listed there), the build in ``swarm_build``;
this module keeps the tool entry point, job routing and the big-plan suggestion.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.server import mcp
from backend.tools.panel.swarm_build import PanelSwarmApi, build_swarm  # noqa: F401
from backend.tools.panel.swarm_preview import (  # noqa: F401
    DETAILS, SUGGESTED_DETAIL, SUGGESTED_MAX_AGENTS, SUGGESTED_PER_GROUP, _parse_agents, _steps, build_preview,
    plan_tree, questions_for, walk_groups, walk_seats,
)
from backend.util.json_util import tool_json


# ---- jobs and routing ---------------------------------------------------------------------

def _routing_context() -> tuple[Any, Any]:
    """(settings, profiles) for swarm_routing.route; (None, None) when they can't load."""
    try:
        from frontend.agent_profiles import list_agent_profiles_available
        from frontend.settings import PanelSettings

        return PanelSettings.load(), list_agent_profiles_available()
    except Exception:
        return None, None


def normalize_jobs(jobs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Jobs with their route (kind, profile, suggested model) filled in."""
    from frontend.swarm_routing import route

    settings, profiles = _routing_context()
    out = []
    for raw in jobs or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        purpose = str(raw.get("purpose") or "").strip()
        task = str(raw.get("task") or "").strip()
        routed = route(f"{name}: {purpose} {task}", str(raw.get("kind") or ""), settings=settings, profiles=profiles)
        out.append({
            "name": name,
            "purpose": purpose,
            "task": task,
            # A sub plan without steps can't be assigned: a job with none gets itself as its step.
            "steps": _steps(raw.get("steps")) or _steps([{"content": name, "body_markdown": task}]),
            "paths": [str(p).strip() for p in raw.get("paths") or [] if str(p).strip()],
            "kind": routed["kind"],
            "profile": routed["profile_id"],
            "suggested_model": routed["model"],
            "model": str(raw.get("model") or "").strip(),
        })
    return out


# ---- the card payload ---------------------------------------------------------------------

def _flat_seats(nodes: list[dict[str, Any]], group: str = "") -> list[dict[str, Any]]:
    """The card's flat seat list: each seat with its nearest group's name."""
    out = []
    for node in nodes:
        if "group" in node:
            out += _flat_seats(node["seats"], node["group"]) + _flat_seats(node["groups"], node["group"])
        else:
            out.append({"name": node["name"], "group": group, "profile": node["profile"], "model": node["model"],
                        "lane": node["paths"], "steps": node["sub_plan"]["total"],
                        "flags": [] if node["paths"] else ["no_lane"]})
    return out


def card(status: str, preview: dict[str, Any]) -> dict[str, Any]:
    """The ``ui: swarm_builder`` fields (see web/src/swarm/fixtures/swarm_builder.json) for *preview*."""
    public = {k: v for k, v in preview.items() if k != "jobs"}
    return {"ui": "swarm_builder", "status": status, "goal": preview["goal"], "preview": public,
            "seats": _flat_seats(public["tree"])}


# ---- the tool -----------------------------------------------------------------------------

def swarm_create(goal: str, jobs: list[dict[str, Any]] | None, agents: Any = "", max_agents: int = 0,
                 per_group: int = 0, edits: list[dict[str, Any]] | None = None, confirm: bool = False,
                 api: Any = None, detail: int = 0) -> dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal is required")
    routed = normalize_jobs(jobs)
    if not routed:
        raise ValueError("jobs is required: [{name, purpose, task, steps[], paths[], kind?, model?}]")
    detail = int(detail or 0)
    questions = questions_for(routed, agents, int(max_agents or 0), int(per_group or 0), detail)
    if questions:
        # The card shows the suggested answers' preview; the agent still asks the questions.
        draft = build_preview(goal, routed, agents if _parse_agents(agents) != "" else "auto",
                              int(max_agents or 0) or SUGGESTED_MAX_AGENTS, int(per_group or 0) or SUGGESTED_PER_GROUP,
                              edits, detail if detail in DETAILS else SUGGESTED_DETAIL)
        return {
            **card("needs_answers", draft),
            "questions": questions,
            "next": ("Ask these with ONE ducky_ask_user(questions=...), then call ducky_swarm_create again "
                     "with detail (1-4), agents='auto' or a number, max_agents and per_group, and each job's "
                     "chosen model in jobs[i].model. Nothing was built."),
            "routes": [{"job": j["name"], "kind": j["kind"], "profile": j["profile"],
                        "suggested_model": j["suggested_model"]} for j in routed],
        }
    preview = build_preview(goal, routed, agents, int(max_agents), int(per_group), edits, detail)
    if not confirm:
        return {
            **card("needs_confirm", preview),
            "next": ("Show the person this preview. Build: same call with confirm=true. Change: same call "
                     "with another detail (1-4) or edits=[{drop}, {rename, to}, {seat, model}, {mute}|{unmute}] "
                     "(keep earlier edits)."),
        }
    try:
        built = build_swarm(preview, api or PanelSwarmApi())
    except Exception as exc:
        # Chats made before the failure stay: say which so nobody seats them twice.
        return {"status": "error", "goal": goal, "error": str(exc), "tree": preview["tree"]}
    return {"status": "done", "goal": goal, "agents": preview["agents"], **built}


@mcp.tool()
def ducky_swarm_create(
    goal: str,
    jobs: list[dict[str, Any]] | None = None,
    agents: str = "",
    max_agents: int = 0,
    per_group: int = 0,
    edits: list[dict[str, Any]] | None = None,
    confirm: bool = False,
    detail: int = 0,
    pretty: bool = False,
) -> str:
    """Make a swarm: write every job from the request ({name, purpose, task, steps[], paths[]}), call
    WITHOUT detail; needs_answers: ask its questions (detail too) in ONE ducky_ask_user, call again;
    needs_confirm: show the preview (tree, steps, detail slider), confirm=true builds exactly it.
    """
    return tool_json(swarm_create(goal, jobs, agents, max_agents, per_group, edits, confirm, detail=detail),
                     pretty=pretty)


# ---- suggest a swarm for a big plan -------------------------------------------------------

# "Files: a", "**Files**: a" and "**Files:** a".
_FILES = re.compile(r"^\s*(?:\*\*)?files(?:\*\*)?\s*:(?:\*\*)?\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    kids = [c for c in node.get("children") or [] if isinstance(c, dict)]
    return [x for c in kids for x in _leaves(c)] if kids else [node]


def _files(node: dict[str, Any]) -> set[str]:
    m = _FILES.search(str(node.get("body_markdown") or ""))
    return {p.strip(" `.") for p in re.split(r"[,;]", m.group(1)) if p.strip(" `.")} if m else set()


def suggest_swarm(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """A swarm suggestion for a plan with 3+ sections or 10+ steps whose sections' Files lists
    don't overlap; None for small plans."""
    from frontend.swarm_routing import route

    nodes = [n for n in (plan or {}).get("nodes") or [] if isinstance(n, dict)]
    sections = [n for n in nodes if n.get("children")]
    steps = sum(len(_leaves(n)) for n in nodes)
    if not sections or (len(sections) < 3 and steps < 10):
        return None
    seen: set[str] = set()
    for sec in sections:
        files = _files(sec)
        if files & seen:
            return None
        seen |= files
    jobs = []
    for sec in sections:
        name = str(sec.get("content") or "").strip()
        r = route(f"{name}: {sec.get('body_markdown') or ''}")
        jobs.append({"name": name, "kind": r["kind"], "profile": r["profile_id"], "model": r["model"],
                     "steps": [str(x.get("content") or "") for x in _leaves(sec)], "paths": sorted(_files(sec))})
    goal = str((plan or {}).get("title") or "").strip() or "Plan"
    call_jobs = [{"name": j["name"], "kind": j["kind"], "steps": j["steps"], "paths": j["paths"]} for j in jobs]
    return {
        "agents": len(jobs),
        "jobs": [j["name"] for j in jobs],
        "routes": [{"job": j["name"], "profile": j["profile"], "model": j["model"]} for j in jobs],
        "ask": f"Run this as a swarm of {len(jobs)}?",
        "call": f"ducky_swarm_create(goal={json.dumps(goal)}, jobs={json.dumps(call_jobs)})",
    }


def _sub_plans(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sections whose children are all steps, at any depth (one member's sub plan each)."""
    out = []
    for node in nodes:
        kids = [c for c in node.get("children") or [] if isinstance(c, dict)]
        if kids and all(not c.get("children") for c in kids):
            out.append(node)
        elif kids:
            out += _sub_plans(kids)
    return out


def suggest_from_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """A ``swarm_builder`` card drafted from *plan*: one seat per unassigned sub plan, its Files as
    the lane. None unless there are 2+ such sub plans and no file is in two of them."""
    sections = [s for s in _sub_plans([n for n in (plan or {}).get("nodes") or [] if isinstance(n, dict)])
                if not str(s.get("assignee") or "").strip()]
    if len(sections) < 2:
        return None
    seen: set[str] = set()
    for sec in sections:
        if _files(sec) & seen:
            return None
        seen |= _files(sec)
    jobs = normalize_jobs([{
        "name": str(sec.get("content") or "").strip(),
        "purpose": str(sec.get("body_markdown") or "").strip()[:200],
        "steps": [{"content": str(x.get("content") or ""), "body_markdown": str(x.get("body_markdown") or "")}
                  for x in sec["children"]],
        "paths": sorted(_files(sec)),
    } for sec in sections])
    goal = str((plan or {}).get("title") or "").strip() or "Plan"
    # ponytail: one seat per sub plan (detail 2, no cap); the card's sliders reshape it via swarm_preview.
    return card("needs_confirm", build_preview(goal, jobs, "auto", len(jobs), SUGGESTED_PER_GROUP, None,
                                               SUGGESTED_DETAIL))
