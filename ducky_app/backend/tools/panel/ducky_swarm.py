"""ducky_swarm_create: one call builds a whole swarm from a goal and its jobs.

Ask once (agent count, size limits, a model per job) → route each job to a template and
model → preview the tree → build it plan-first (sub plans and steps, then groups and seats
with their lanes, then assign). Every step before ``confirm=true`` is pure and builds
nothing, so the same arguments always give the same preview.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from backend.server import mcp
from backend.util.json_util import tool_json

SUGGESTED_MAX_AGENTS = 8
SUGGESTED_PER_GROUP = 5
MAX_DEPTH = 3  # root group → area group → split group
DONE_LINE = "Done when: the change and its tests pass; commit your files (git add <files>) and push."

# Job kind → (area, purpose) of the sub-group related jobs nest into. test/review stay at the top.
_AREAS: dict[str, tuple[str, str]] = {
    "modeling": ("Art", "assets"), "material": ("Art", "assets"), "rig": ("Art", "assets"),
    "animation": ("Art", "assets"), "concept": ("Art", "assets"), "vfx": ("Art", "assets"),
    "verse": ("Code", "gameplay"), "ui": ("Code", "gameplay"), "npc": ("Code", "gameplay"),
    "app": ("Code", "app"), "developer": ("Code", "app"),
    "level": ("World", "levels"), "sound": ("Audio", "sound"),
    "narrative": ("Story", "writing"), "writing": ("Story", "writing"),
    "research": ("Research", "findings"), "video": ("Media", "video"),
}
_TOP_KINDS = {"test": "Tester", "review": "Reviewer"}


# ---- jobs and routing ---------------------------------------------------------------------

def _routing_context() -> tuple[Any, Any]:
    """(settings, profiles) for swarm_routing.route; (None, None) when they can't load."""
    try:
        from frontend.agent_profiles import list_agent_profiles_available
        from frontend.settings import PanelSettings

        return PanelSettings.load(), list_agent_profiles_available()
    except Exception:
        return None, None


def _steps(raw: Any) -> list[dict[str, str]]:
    out = []
    for s in raw or []:
        if isinstance(s, dict):
            content = str(s.get("content") or s.get("title") or "").strip()
            body = str(s.get("body_markdown") or s.get("body") or "").strip()
        else:
            content, body = str(s or "").strip(), ""
        if content:
            if "done when" not in body.lower():
                body = (body + "\n" if body else "") + DONE_LINE
            out.append({"content": content, "body_markdown": body})
    return out


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


DETAILS = {1: "Areas", 2: "Jobs", 3: "Parts", 4: "Parts in sub-groups"}
SUGGESTED_DETAIL = 2


def apply_detail(jobs: list[dict[str, Any]], detail: int) -> list[dict[str, Any]]:
    """swarm_routing.split_jobs for *detail*, with the steps each reshaped job really owns:
    an area job gets every merged job's steps, a part gets its parent's steps marked with the
    part (split_jobs copies only the first job's / the whole parent's)."""
    from frontend.swarm_routing import area_of, split_jobs

    out = split_jobs(jobs, detail)
    for job in out:
        if job.get("part"):
            part = str(job["part"])
            # ponytail: each part runs every parent step for its slice; real per-part steps need the lead.
            job["steps"] = [{"content": f"{part}: {s['content']}", "body_markdown": s["body_markdown"]}
                            for s in job["steps"]] or _steps([job["name"]])
        elif "kinds" in job and job.get("area"):
            same = [j for j in jobs if area_of(j["kind"]) == job["area"]]
            job["steps"] = [s for j in same for s in j["steps"]]
            job["purpose"] = "; ".join(j["purpose"] for j in same if j["purpose"])
    return out


# ---- s4-ask: the questions ----------------------------------------------------------------

def _parse_agents(agents: Any) -> str | int:
    """'' (not answered), 'auto', or a positive int."""
    if isinstance(agents, bool):
        return ""
    if isinstance(agents, int):
        return agents if agents > 0 else ""
    text = str(agents or "").strip().lower()
    if text == "auto":
        return "auto"
    return int(text) if text.isdigit() and int(text) > 0 else ""


def detail_levels(jobs: list[dict[str, Any]], agents: Any, max_agents: int, per_group: int) -> list[dict[str, Any]]:
    """[{detail, agents, groups}] for every detail level; unanswered limits count as the suggested ones."""
    max_agents = max_agents if max_agents > 0 else SUGGESTED_MAX_AGENTS
    per_group = per_group if per_group > 0 else SUGGESTED_PER_GROUP
    out = []
    for d in DETAILS:
        tree = plan_tree(apply_detail(jobs, d), agents, max_agents, per_group)
        out.append({"detail": d, "name": DETAILS[d], "agents": len(list(walk_seats(tree))),
                    "groups": len(list(walk_groups(tree)))})
    return out


def questions_for(jobs: list[dict[str, Any]], agents: Any, max_agents: int, per_group: int,
                  detail: int = SUGGESTED_DETAIL) -> list[dict[str, Any]]:
    """The ducky_ask_user questions still unanswered (empty = go on)."""
    qs: list[dict[str, Any]] = []
    if detail not in DETAILS:
        qs.append({
            "id": "detail",
            "prompt": "How finely should the work be split?",
            "options": [
                {"id": str(lv["detail"]),
                 "label": f"{lv['detail']} {lv['name']}" + (" (suggested)" if lv["detail"] == SUGGESTED_DETAIL else ""),
                 "description": f"{lv['agents']} agents" + (f" in {lv['groups']} sub-group{'s' if lv['groups'] > 1 else ''}" if lv["groups"] else "")}
                for lv in detail_levels(jobs, agents, max_agents, per_group)
            ],
        })
    if _parse_agents(agents) == "":
        qs.append({
            "id": "agents",
            "prompt": f"How many agents should work on this? There are {len(jobs)} jobs.",
            "options": [
                {"id": "auto", "label": f"Auto ({len(jobs)})", "description": "One agent per job, up to the size limit."},
                {"id": "number", "label": "A number", "description": "Type how many agents; related jobs share one."},
            ],
        })
    if max_agents <= 0 or per_group <= 0:
        qs.append({
            "id": "size_limits",
            "prompt": (
                "Size limits: the most agents in the whole swarm, and the most agents directly in one "
                "group before Ducky splits them into sub-groups."
            ),
            "options": [
                {"id": f"{SUGGESTED_MAX_AGENTS}/{SUGGESTED_PER_GROUP}",
                 "label": f"{SUGGESTED_MAX_AGENTS} total · {SUGGESTED_PER_GROUP} per group (suggested)",
                 "description": ("Example: a game team of 8 becomes 'Art: assets' (Modeling, Texture) and "
                                 "'Code: gameplay' (Verse, UI) as sub-groups, with Narrative, Research, Tester "
                                 "and Reviewer directly under the lead.")},
                {"id": "other", "label": "Other limits", "description": "Type 'total / per group', e.g. 12 / 4."},
            ],
        })
    for i, job in enumerate(jobs):
        if job["model"]:
            continue
        suggested = job["suggested_model"]
        qs.append({
            "id": f"model:{i}",
            "prompt": f"Model for {job['name']} ({job['profile']})?",
            "options": [
                *([{"id": suggested, "label": f"{suggested} (suggested)",
                    "description": f"The {job['kind']} job's usual model."}] if suggested else []),
                {"id": "other", "label": "Another model", "description": "Type a model id, e.g. codex:gpt-5-mini."},
            ],
        })
    return qs


# ---- s4-split: size the team and the tree -------------------------------------------------

def _merge(into: dict[str, Any], job: dict[str, Any]) -> None:
    into["name"] = f"{into['name']} + {job['name']}"
    into["steps"] = into["steps"] + job["steps"]
    into["paths"] = into["paths"] + [p for p in job["paths"] if p not in into["paths"]]
    into["purpose"] = "; ".join(x for x in (into["purpose"], job["purpose"]) if x)
    into["task"] = "\n".join(x for x in (into["task"], job["task"]) if x)


def _cap(jobs: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    """Fit jobs into *cap* seats: the last job merges into an earlier one of its area, else
    into the job before it. Nothing is dropped."""
    jobs = [dict(j) for j in jobs]
    while len(jobs) > max(cap, 1):
        last = jobs.pop()
        area = _AREAS.get(last["kind"])
        same = [j for j in jobs if area and _AREAS.get(j["kind"]) == area]
        _merge(same[-1] if same else jobs[-1], last)
    return jobs


def capped_jobs(jobs: list[dict[str, Any]], agents: Any, max_agents: int) -> list[dict[str, Any]]:
    """The jobs as seated: 'auto' = one per job, a number = that many, both capped at max_agents."""
    want = _parse_agents(agents)
    cap = len(jobs) if want in ("", "auto") else int(want)
    return _cap(jobs, min(cap, max_agents) if max_agents > 0 else cap)


def _seat_name(job: dict[str, Any], taken: set[str]) -> str:
    part = str(job.get("part") or "").strip()
    head = part[:1].upper() + part[1:] if part else job["name"].split(":", 1)[0].split(" + ", 1)[0].strip()
    base = _TOP_KINDS.get(job["kind"]) or f"{head} lead"
    name, n = base, 2
    while name in taken:
        name, n = f"{base} {n}", n + 1
    taken.add(name)
    return name


def _seat(job: dict[str, Any], taken: set[str]) -> dict[str, Any]:
    return {
        "name": _seat_name(job, taken),
        "job": job["name"],
        "kind": job["kind"],
        "profile": job["profile"],
        "model": job["model"] or job["suggested_model"],
        "paths": job["paths"],
        "sub_plan": {"title": job["name"], "done": 0, "total": len(job["steps"]),
                     "steps": [dict(s) for s in job["steps"]]},
    }


def _group(name: str, purpose: str, seats: list[dict[str, Any]], per_group: int, depth: int) -> dict[str, Any]:
    """A group of seats; more than *per_group* seats split into numbered sub-groups."""
    node = {"group": f"{name}: {purpose}", "purpose": purpose, "muted": True, "seats": seats, "groups": []}
    if len(seats) > per_group and depth < MAX_DEPTH:
        chunks = [seats[i:i + per_group] for i in range(0, len(seats), per_group)]
        node["seats"] = []
        node["groups"] = [_group(f"{name} {i}", purpose, c, per_group, depth + 1) for i, c in enumerate(chunks, 1)]
    return node


def plan_tree(jobs: list[dict[str, Any]], agents: Any, max_agents: int, per_group: int) -> list[dict[str, Any]]:
    """Tree nodes (groups first, then root seats) for the answered size limits.

    'auto' = one agent per job; a number = that many; both capped at *max_agents* (jobs merge,
    never drop). The root keeps at most *per_group* seats: related jobs nest into
    '<Area>: <purpose>' sub-groups, biggest area first; Tester and Reviewer stay at the root.
    """
    per_group = max(per_group, 1)
    taken: set[str] = set()
    seated = [(job, _seat(job, taken)) for job in capped_jobs(jobs, agents, max_agents)]
    # Detail 4: the parts of one job (split_jobs tags them with group = the parent) form its sub-group.
    parts: dict[str, list[dict[str, Any]]] = {}
    for job, seat in seated:
        if job.get("group"):
            parts.setdefault(str(job["group"]).split(":", 1)[0].strip(), []).append(seat)
    groups: list[dict[str, Any]] = [_group(parent, "parts", seats, per_group, 2) for parent, seats in parts.items()]
    in_parts = [s for seats in parts.values() for s in seats]
    seated = [(j, s) for j, s in seated if s not in in_parts]
    top = [s for _j, s in seated]
    if len(top) <= per_group:
        return [*groups, *top]
    areas: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for job, seat in seated:
        if job["kind"] not in _TOP_KINDS:
            areas.setdefault(_AREAS.get(job["kind"], ("Team", "jobs")), []).append(seat)
    for (area, purpose), seats in sorted(areas.items(), key=lambda kv: -len(kv[1])):
        if len(top) <= per_group or len(seats) < 2:
            break
        groups.append(_group(area, purpose, seats, per_group, 2))
        top = [s for s in top if s not in seats]
    loose = [s for s in top if s["kind"] not in _TOP_KINDS]
    if len(top) > per_group and len(loose) > 1:
        # ponytail: one catch-all group when no area has two jobs left; smarter pairing if it shows up.
        groups.append(_group("Team", "more jobs", loose, per_group, 2))
        top = [s for s in top if s not in loose]
    return [*groups, *top]


def walk_groups(nodes: list[dict[str, Any]]):
    for node in nodes:
        if "group" in node:
            yield node
            yield from walk_groups(node["groups"])


def walk_seats(nodes: list[dict[str, Any]]):
    for node in nodes:
        if "group" in node:
            yield from walk_seats(node["seats"])
            yield from walk_seats(node["groups"])
        else:
            yield node


# ---- preview and edits --------------------------------------------------------------------

def _job_edits(jobs: list[dict[str, Any]], edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs = [dict(j) for j in jobs]
    for e in edits:
        if "drop" in e:
            jobs = [j for j in jobs if j["name"] != str(e["drop"]).strip()]
        elif "rename" in e:
            for j in jobs:
                if j["name"] == str(e["rename"]).strip():
                    j["name"] = str(e.get("to") or "").strip() or j["name"]
    return jobs


def _tree_edits(tree: list[dict[str, Any]], edits: list[dict[str, Any]]) -> None:
    groups = {g["group"]: g for g in walk_groups(tree)}
    seats = {s["name"]: s for s in walk_seats(tree)}
    for e in edits:
        seat = seats.get(str(e.get("seat") or "").strip())
        if "seat" in e and seat is None:
            raise ValueError(f"No seat called {e['seat']!r}; seats: {', '.join(seats)}")
        if seat is not None and any(k in e for k in ("add_step", "drop_step", "rename_step")):
            steps = seat["sub_plan"]["steps"]
            if "add_step" in e:
                steps.extend(_steps([e["add_step"]]))
            else:
                key = str(e.get("drop_step") or e.get("rename_step") or "").strip()
                hit = next((s for s in steps if s["content"] == key), None)
                if hit is None:
                    raise ValueError(f"{seat['name']} has no step {key!r}; steps: "
                                     + "; ".join(s["content"] for s in steps))
                if "drop_step" in e:
                    if len(steps) == 1:
                        raise ValueError(f"{seat['name']}'s sub plan needs at least one step: drop the job instead.")
                    steps.remove(hit)
                else:
                    hit["content"] = str(e.get("to") or "").strip() or hit["content"]
            seat["sub_plan"]["total"] = len(steps)
        elif seat is not None and e.get("model"):
            seat["model"] = str(e["model"]).strip()
        elif "mute" in e or "unmute" in e or ("group" in e and "muted" in e):
            key = str(e.get("mute") or e.get("unmute") or e.get("group")).strip()
            if key not in groups:
                raise ValueError(f"No group called {key!r}; groups: {', '.join(groups) or 'none'}")
            groups[key]["muted"] = bool(e["muted"]) if "muted" in e else "mute" in e
        elif "rename" in e and str(e["rename"]).strip() in groups:
            groups[str(e["rename"]).strip()]["group"] = str(e.get("to") or "").strip() or e["rename"]


def build_preview(goal: str, jobs: list[dict[str, Any]], agents: Any, max_agents: int, per_group: int,
                  edits: list[dict[str, Any]] | None = None, detail: int = SUGGESTED_DETAIL) -> dict[str, Any]:
    edits = [e for e in edits or [] if isinstance(e, dict)]
    kept = capped_jobs(_job_edits(apply_detail(jobs, detail), edits), agents, max_agents)
    tree = plan_tree(kept, agents, max_agents, per_group)
    _tree_edits(tree, edits)
    seats = list(walk_seats(tree))
    return {
        "goal": goal,
        "detail": detail,
        "levels": detail_levels(jobs, agents, max_agents, per_group),
        "agents": len(seats),
        "max_agents": max_agents,
        "per_group": per_group,
        "tree": tree,
        "muted": [g["group"] for g in walk_groups(tree) if g["muted"]],
        "lanes": {s["name"]: s["paths"] for s in seats},
        # The plan Build makes, as one outline: the person approves it with the tree.
        "plan": {"title": goal, "sections": [{"seat": s["name"], "title": s["sub_plan"]["title"],
                                               "steps": s["sub_plan"]["steps"]} for s in seats]},
        "jobs": {s["name"]: next(j for j in kept if j["name"] == s["job"]) for s in seats},
    }


# ---- s4-build -----------------------------------------------------------------------------

def _loads(text: str) -> dict[str, Any]:
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        data = json.loads(data["result"])
    if not isinstance(data, dict) or data.get("ok") is False:
        raise ValueError(str((data or {}).get("error") if isinstance(data, dict) else data))
    return data


class PanelSwarmApi:
    """The live calls a build makes, over the existing group and plan tools."""

    def caller(self) -> str:
        from backend.tools.panel.ducky_panel import _resolve_plan_chat_id

        return _resolve_plan_chat_id("")

    def group_create(self, name: str, parent_folder_id: str = "") -> dict[str, Any]:
        from backend.tools.panel.ducky_panel import ducky_group_create

        res = _loads(ducky_group_create(name=name, parent_folder_id=parent_folder_id))
        return {"id": res.get("id") or "", "folder_id": res.get("folder_id") or ""}

    def add_leader(self, group_id: str, conv_id: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_group_add_member

        _loads(ducky_group_add_member(group_id=group_id, conv_id=conv_id, as_leader=True, move_folder=True))

    def rename_chat(self, conv_id: str, title: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_rename_chat

        _loads(ducky_rename_chat(conv_id=conv_id, title=title))

    def ensure_plan(self, chat_id: str, goal: str) -> None:
        from backend.agent.coding_agents.plans import load_plan_view
        from backend.tools.panel.ducky_panel import _project_root, ducky_create_plan

        try:
            plan = load_plan_view(chat_id, project_root=_project_root())
        except ValueError:
            plan = None
        if not plan:
            _loads(ducky_create_plan(title=goal, overview=f"Swarm: {goal}", nodes=[], chat_id=chat_id))

    def plan_add_node(self, chat_id: str, content: str, parent_id: str = "", kind: str = "step",
                      body_markdown: str = "") -> str:
        from backend.tools.panel.ducky_panel import ducky_plan_add_node

        res = _loads(ducky_plan_add_node(content=content, parent_id=parent_id, chat_id=chat_id, kind=kind,
                                         body_markdown=body_markdown))
        return str((res.get("node") or {}).get("id") or "")

    def invite(self, group_id: str, profile: str, name: str, model: str,
               write_allowed: Optional[list[str]]) -> str:
        from backend.tools.panel.ducky_panel import ducky_group_invite

        res = _loads(ducky_group_invite(group_id=group_id, ducky=profile, write_allowed=write_allowed,
                                        name=name, model=model))
        return str((res.get("member") or {}).get("member_conv_id") or "")

    def set_muted(self, conv_id: str, muted: bool) -> None:
        from backend.tools.panel.ducky_panel import ducky_set_muted

        _loads(ducky_set_muted(conv_id=conv_id, muted=muted))

    def assign(self, chat_id: str, node_id: str, assignee: str) -> None:
        from backend.tools.panel.ducky_panel import ducky_plan_update_node

        _loads(ducky_plan_update_node(node_id=node_id, chat_id=chat_id, assignee=assignee))


def build_swarm(preview: dict[str, Any], api: Any) -> dict[str, Any]:
    """Build *preview* exactly: (1) root group + caller as lead, (2) one sub plan per job with
    its steps, no assignee, (3) nested groups and seats with lanes, then mute, (4) assign."""
    goal = preview["goal"]
    tree = preview["tree"]
    lead = api.caller()
    if not lead:
        raise ValueError("No calling chat: ducky_swarm_create must run in the lead's chat.")
    root = api.group_create(goal)
    api.add_leader(root["id"], lead)
    api.rename_chat(lead, f"Lead: {goal}")

    api.ensure_plan(lead, goal)
    sections: dict[str, str] = {}
    for seat in walk_seats(tree):
        job = preview["jobs"][seat["name"]]
        body = "\n".join(x for x in (job["purpose"], job["task"],
                                     f"Files: {', '.join(job['paths'])}" if job["paths"] else "", DONE_LINE) if x)
        sid = api.plan_add_node(lead, seat["sub_plan"]["title"], kind="subplan", body_markdown=body)
        for step in seat["sub_plan"]["steps"]:  # exactly the previewed steps, edits included
            api.plan_add_node(lead, step["content"], parent_id=sid, body_markdown=step["body_markdown"])
        sections[seat["name"]] = sid
        seat["sub_plan"]["id"] = sid

    def seat_in(group_id: str, seat: dict[str, Any]) -> None:
        seat["conv_id"] = api.invite(group_id, seat["profile"], seat["name"], seat["model"], seat["paths"] or None)
        seat["created"] = True

    def make(node: dict[str, Any], parent_folder: str) -> None:
        made = api.group_create(node["group"], parent_folder)
        node["group_id"], node["created"] = made["id"], True
        for seat in node["seats"]:
            seat_in(made["id"], seat)
        for sub in node["groups"]:
            make(sub, made["folder_id"])

    for node in tree:
        if "group" in node:
            make(node, root["folder_id"])
        else:
            seat_in(root["id"], node)
    for group in walk_groups(tree):
        if group["muted"]:
            api.set_muted(group["group_id"], True)
    for seat in walk_seats(tree):
        api.assign(lead, sections[seat["name"]], seat["conv_id"])
    return {"root_group_id": root["id"], "lead": lead, "tree": tree}


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
        return {
            "status": "needs_answers",
            "goal": goal,
            "questions": questions,
            "next": ("Ask these with ONE ducky_ask_user(questions=...), then call ducky_swarm_create again "
                     "with detail (1-4), agents='auto' or a number, max_agents and per_group, and each job's "
                     "chosen model in jobs[i].model. Nothing was built."),
            "routes": [{"job": j["name"], "kind": j["kind"], "profile": j["profile"],
                        "suggested_model": j["suggested_model"]} for j in routed],
        }
    preview = build_preview(goal, routed, agents, int(max_agents), int(per_group), edits, detail)
    public = {k: v for k, v in preview.items() if k != "jobs"}
    if not confirm:
        return {
            "status": "needs_confirm",
            "goal": goal,
            "preview": public,
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

_FILES = re.compile(r"^\s*(?:\*\*)?files(?:\*\*)?\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


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
