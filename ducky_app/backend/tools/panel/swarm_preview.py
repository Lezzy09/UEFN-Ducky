"""Swarm preview: the questions, the tree and the preview ducky_swarm_create shows. Pure: builds nothing.

``build_preview`` returns the ``preview`` part of the swarm card payload
(``ui: "swarm_builder"``, pinned in web/src/swarm/fixtures/swarm_builder.json):

- ``goal``, ``detail`` (1-4), ``agents``, ``max_agents``, ``per_group``
- ``levels``: [{detail, name, agents, groups}] — one per detail level (the slider)
- ``tree``: groups first, then root seats. Group = {group, purpose, muted, seats, groups};
  seat = {name, job, kind, profile, model, paths, sub_plan: {title, done, total, steps}}
- ``muted``: names of muted groups; ``lanes``: {seat name: [paths]}
- ``plan``: {title, sections: [{seat, title, steps}]} — the plan Build makes
- ``estimate``: {seats: {name: {tokens, minutes, cost_usd}}, total: {tokens, minutes, cost_usd, text}}
- ``jobs`` (server only, dropped before it reaches the card)

The card payload adds, around ``preview``: ``ui``, ``status``, ``goal``, ``seats`` (flat:
{name, group, profile, model, lane, steps, flags}) and ``estimate`` ({seats: {name: {minutes,
cost_usd}}, total: {minutes, cost_usd}}).
"""

from __future__ import annotations

from typing import Any

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


# ---- jobs ---------------------------------------------------------------------------------

_CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".rs", ".go", ".cs", ".cpp", ".c", ".h", ".java")
# Kinds the keyword router picks from a job's words that can't be right when every path is code.
_PROSE_KINDS = {"writing", "narrative", "research", "concept", "video"}


def _is_code_path(path: str) -> bool:
    return path.strip().lower().endswith(_CODE_EXT)


def fix_routes(jobs: list[dict[str, Any]], lead_model: str = "") -> list[dict[str, Any]]:
    """Jobs whose paths are all code run as 'developer' (the words said 'docs' or 'safety'), and
    every job has a suggested model: its kind's, else the lead's, else the app kind's."""
    from frontend.swarm_routing import job_kind

    out = []
    for job in jobs:
        job = dict(job)
        if job.get("paths") and job.get("kind") in _PROSE_KINDS and all(_is_code_path(p) for p in job["paths"]):
            job.update(kind="developer", profile="developer", suggested_model="")
        if not job.get("suggested_model"):
            row = job_kind(job.get("kind") or "")
            job["suggested_model"] = (row.model if row else "") or lead_model or job_kind("app").model
        out.append(job)
    return out


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


def distinct_levels(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One level per (agents, groups) shape; the suggested level wins its shape, else the first."""
    by_shape: dict[tuple[int, int], dict[str, Any]] = {}
    for lv in levels:
        shape = (lv["agents"], lv["groups"])
        if shape not in by_shape or lv["detail"] == SUGGESTED_DETAIL:
            by_shape[shape] = lv
    return sorted(by_shape.values(), key=lambda lv: lv["detail"])


def questions_for(jobs: list[dict[str, Any]], agents: Any, max_agents: int, per_group: int,
                  detail: int = SUGGESTED_DETAIL, lead_model: str = "") -> list[dict[str, Any]]:
    """The ducky_ask_user questions still unanswered (empty = go on)."""
    jobs = fix_routes(jobs, lead_model)
    qs: list[dict[str, Any]] = []
    if detail not in DETAILS:
        qs.append({
            "id": "detail",
            "prompt": "How finely should the work be split?",
            "options": [
                {"id": str(lv["detail"]),
                 "label": f"{lv['detail']} {lv['name']}" + (" (suggested)" if lv["detail"] == SUGGESTED_DETAIL else ""),
                 "description": f"{lv['agents']} agents" + (f" in {lv['groups']} sub-group{'s' if lv['groups'] > 1 else ''}" if lv["groups"] else "")}
                for lv in distinct_levels(detail_levels(jobs, agents, max_agents, per_group))
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


# ---- seats as a step graph (job previews and real plans) ----------------------------------
# A graph seat = {name, id, lane, after: [refs], steps: [{id, content, body, after: [refs]}]}.
# A ref names a step id, or a seat/section id meaning all of its steps. In a job preview the
# step ids are "<seat name>#<n>" (1-based) and a seat's id is its name.

def preview_seats(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in walk_seats(tree):
        sub = s["sub_plan"]
        out.append({"name": s["name"], "id": s["name"], "lane": list(s["paths"]), "model": s["model"],
                    "after": list(sub.get("after") or []),
                    "steps": [{"id": f"{s['name']}#{i}", "content": st["content"],
                               "body": st.get("body_markdown") or "", "after": list(st.get("after") or [])}
                              for i, st in enumerate(sub["steps"], 1)]})
    return out


def step_deps(seats: list[dict[str, Any]], expand: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """{step id: the step ids it waits for}, from step and seat ``after`` refs. *expand* maps
    other ref ids (a plan's group sections) to their step ids."""
    refs: dict[str, list[str]] = dict(expand or {})
    for seat in seats:
        ids = [st["id"] for st in seat["steps"]]
        refs[seat["id"]] = ids
        refs.update({i: [i] for i in ids})
    deps: dict[str, list[str]] = {}
    for seat in seats:
        own = {st["id"] for st in seat["steps"]}
        seat_wide = [d for r in seat["after"] for d in refs.get(r, []) if d not in own]
        for st in seat["steps"]:
            mine = [d for r in st["after"] for d in refs.get(r, []) if d != st["id"]]
            deps[st["id"]] = list(dict.fromkeys(seat_wide + mine))
    return deps


def _finish_steps(seats: list[dict[str, Any]], deps: dict[str, list[str]]) -> dict[str, int]:
    """{step id: steps of work done when it finishes}: a seat works its steps in order and a
    step starts once everything it waits for is done. A cycle counts as not waiting."""
    prev = {st["id"]: (seat["steps"][i - 1]["id"] if i else None)
            for seat in seats for i, st in enumerate(seat["steps"])}
    done: dict[str, int] = {}
    busy: set[str] = set()

    def finish(sid: str) -> int:
        if sid in done:
            return done[sid]
        if sid in busy:
            return 0
        busy.add(sid)
        waits = [finish(d) for d in deps.get(sid, [])] + ([finish(prev[sid])] if prev.get(sid) else [])
        busy.discard(sid)
        done[sid] = max(waits, default=0) + 1
        return done[sid]

    for sid in prev:
        finish(sid)
    return done


# ---- cost and time --------------------------------------------------------------------------

TOKENS_PER_STEP = 150_000  # ponytail: one baseline for every step; tune it from real swarm runs
MINUTES_PER_STEP = 10
OUTPUT_SHARE = 0.05  # the rest is input, mostly cache reads in an agent loop
_AGENT_PREFIXES = ("claude", "codex", "ducky", "cursor")


def _price(model: str) -> tuple[float, float, float, float] | None:
    """(input, cached input, output, cache write) USD per 1M tokens, None when unknown."""
    head, sep, rest = model.partition(":")
    mid = rest if sep and head.lower() in _AGENT_PREFIXES else model
    try:
        from backend.agent.model_pricing import infer_provider, price_for_model

        return price_for_model(mid, infer_provider(mid))
    except Exception:
        return None


def estimate(seats: list[dict[str, Any]]) -> dict[str, Any]:
    """{seats: {name: {tokens, minutes, cost_usd}}, total: {tokens, minutes, cost_usd, text}}.
    Seat minutes = its own steps; total minutes = the longest chain through ``after``."""
    out: dict[str, Any] = {}
    for seat in seats:
        tokens = len(seat["steps"]) * TOKENS_PER_STEP
        price = _price(str(seat.get("model") or ""))
        cost = (None if price is None else
                round((tokens * (1 - OUTPUT_SHARE) * price[1] + tokens * OUTPUT_SHARE * price[2]) / 1e6, 2))
        out[seat["name"]] = {"tokens": tokens, "minutes": len(seat["steps"]) * MINUTES_PER_STEP, "cost_usd": cost}
    tokens = sum(v["tokens"] for v in out.values())
    minutes = max(_finish_steps(seats, step_deps(seats)).values(), default=0) * MINUTES_PER_STEP
    costs = [v["cost_usd"] for v in out.values() if v["cost_usd"] is not None]
    cost = round(sum(costs), 2) if costs else None
    text = f"~{tokens / 1e6:.1f}M tokens · ~{minutes} min" + (f" · ~${cost:.2f}" if cost is not None else "")
    return {"seats": out, "total": {"tokens": tokens, "minutes": minutes, "cost_usd": cost, "text": text}}


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
                  edits: list[dict[str, Any]] | None = None, detail: int = SUGGESTED_DETAIL,
                  lead_model: str = "") -> dict[str, Any]:
    edits = [e for e in edits or [] if isinstance(e, dict)]
    jobs = fix_routes(jobs, lead_model)
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
        "estimate": estimate(preview_seats(tree)),
        "jobs": {s["name"]: next(j for j in kept if j["name"] == s["job"]) for s in seats},
    }
