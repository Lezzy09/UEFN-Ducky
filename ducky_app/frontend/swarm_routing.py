"""Swarm routing: which template (ducky profile) and which model each job gets.

Jobs are decided when a swarm is created. Each job kind has its own model: the person's
pick in Settings (``swarm_job_models``), else the template profile's own model, else the
kind's suggested model. Pure functions; nothing here starts a chat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FALLBACK_KIND = "developer"
FALLBACK_PROFILE = "developer"


@dataclass(frozen=True)
class JobKind:
    kind: str
    keywords: tuple[str, ...]
    profile_id: str
    model: str
    """Suggested model for this kind; the person changes it per kind in Settings."""


JOB_KINDS: tuple[JobKind, ...] = (
    JobKind("narrative", ("narrative", "story", "dialogue", "quest", "lore", "character arc"), "developer",
            "claude-opus-5-5"),
    JobKind("research", ("research", "investigate", "survey", "compare", "benchmark"), "developer",
            "claude-sonnet-5-5"),
    JobKind("concept", ("concept", "art direction", "moodboard", "style guide", "art style"), "developer",
            "claude-sonnet-5-5"),
    JobKind("modeling", ("modeling", "modelling", "mesh", "blender", "sculpt", "prop", "3d"), "3d-modeler",
            "claude-sonnet-5-5"),
    JobKind("material", ("texture", "material", "shader"), "material-artist", "claude-sonnet-5-5"),
    JobKind("verse", ("verse", "gameplay", "device", "game logic", "logic"), "verse-coder", "claude-opus-5-5"),
    JobKind("ui", ("ui", "hud", "widget", "umg", "menu"), "ui-engineer", "claude-sonnet-5-5"),
    JobKind("level", ("level", "layout", "blockout", "map"), "level-designer", "claude-sonnet-5-5"),
    JobKind("npc", ("npc", "creature", "enemy", "enemies"), "npc-author", "claude-sonnet-5-5"),
    JobKind("vfx", ("vfx", "niagara", "particle", "effect"), "niagara-vfx", "claude-sonnet-5-5"),
    JobKind("sound", ("sound", "audio", "music", "sfx"), "sound-designer", "claude-sonnet-5-5"),
    JobKind("rig", ("rig", "rigging", "skeleton", "skin weights"), "rigging-artist", "claude-sonnet-5-5"),
    JobKind("animation", ("animation", "animate", "anim"), "animation-artist", "claude-sonnet-5-5"),
    JobKind("video", ("video", "trailer", "editing", "footage", "montage"), "developer", "claude-sonnet-5-5"),
    JobKind("writing", ("writing", "docs", "documentation", "readme", "patch notes", "copy"), "developer",
            "claude-sonnet-5-5"),
    JobKind("test", ("test", "qa", "playtest", "tester"), "tester", "claude-sonnet-5-5"),
    JobKind("review", ("review", "reviewer", "audit"), "reviewer", "claude-opus-5-5"),
    JobKind("app", ("app", "python", "backend", "frontend", "api", "sqlite", "database", "migration",
                    "typescript", "server", "script"), "developer", "claude-opus-5-5"),
)

_BY_KIND = {row.kind: row for row in JOB_KINDS}
_SUFFIX = r"(?:s|es|ing|ed)?"


def _pattern(keyword: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(w) for w in keyword.split())
    return re.compile(rf"(?<![a-z0-9]){words}{_SUFFIX}(?![a-z0-9])")


_PATTERNS = {row.kind: tuple(_pattern(k) for k in row.keywords) for row in JOB_KINDS}


def job_kind(kind: str) -> JobKind | None:
    return _BY_KIND.get((kind or "").strip().lower())


def _match(text: str) -> tuple[JobKind | None, list[str]]:
    """The row with the most keyword hits (the job's name, before ':', counts double); ties go
    to the earlier row."""
    low = (text or "").lower()
    name = low.split(":", 1)[0] if ":" in low else ""
    best: JobKind | None = None
    best_score = 0
    best_hits: list[str] = []
    for row in JOB_KINDS:
        hits = [kw for kw, pat in zip(row.keywords, _PATTERNS[row.kind]) if pat.search(low)]
        if not hits:
            continue
        score = len(hits) + sum(1 for kw, pat in zip(row.keywords, _PATTERNS[row.kind]) if name and pat.search(name))
        if score > best_score:
            best, best_score, best_hits = row, score, hits
    return best, best_hits


def _profile_model(profile: Mapping[str, Any] | None) -> str:
    favs = (profile or {}).get("favorite_models") or []
    return next((str(m).strip() for m in favs if str(m).strip()), "") if isinstance(favs, list) else ""


def _agent_may_use(model: str, settings: Any) -> bool:
    """False when *model* bills a pay-per-token API key agents may not start chats on."""
    from frontend import favorite_models as fm

    selection = fm.parse_selection(model)
    if selection is not None:
        if selection.is_coding_agent:
            return True
        result: Any = fm.ResolveOk(coding_agent="ducky", model=selection.model_id,
                                   provider=selection.provider, selection=selection)
    else:
        try:
            result = fm.resolve_model_strict([model], settings)
        except Exception:
            return True  # unresolvable here: the spawn reports it
    refused = fm.refuse_paid_api_for_agent(result, settings)
    return not (isinstance(refused, fm.ResolveErr) and refused.code == "api_key_blocked")


def job_model(kind: str, profile: Mapping[str, Any] | None, settings: Any) -> str:
    """The model a job of *kind* runs on: Settings' ``swarm_job_models[kind]``, else the
    template profile's own model, else ''. Never a paid API model agents may not use."""
    picks = getattr(settings, "swarm_job_models", None) or {}
    key = (kind or "").strip().lower()
    for model in (str(picks.get(key) or "").strip() if isinstance(picks, Mapping) else "", _profile_model(profile)):
        if model:
            return model if _agent_may_use(model, settings) else ""
    return ""


def route(
    text: str,
    kind: str = "",
    *,
    settings: Any = None,
    profiles: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    """Route one job (its name and task) to {kind, profile_id, model, why}.

    An explicit *kind* wins, else keyword match on *text*, else 'developer'. A kind with no
    specialist profile runs on Developer and keeps its own name and model. *profiles* (the
    available ducky profiles) lets a missing specialist fall back to Developer; *settings*
    applies the person's model per kind.
    """
    explicit = (kind or "").strip().lower()
    row = job_kind(explicit) if explicit else None
    if explicit:
        why = f"kind '{explicit}' was given"
        if row is None:
            why += " (no table row: Developer runs it)"
    else:
        row, hits = _match(text)
        why = (f"matched {', '.join(repr(h) for h in hits)}" if row
               else "no job kind matched: Developer runs it")
    out_kind = row.kind if row else (explicit or FALLBACK_KIND)
    profile_id = row.profile_id if row else FALLBACK_PROFILE
    by_id = {str(p.get("id") or ""): p for p in profiles} if profiles is not None else None
    if by_id is not None and profile_id not in by_id:
        why += f"; profile '{profile_id}' is not available, Developer runs it"
        profile_id = FALLBACK_PROFILE
    profile = by_id.get(profile_id) if by_id is not None else None
    if settings is not None:
        model = job_model(out_kind, profile, settings)
    else:
        model = _profile_model(profile)
    if not model:
        model = row.model if row else ""
    return {"kind": out_kind, "profile_id": profile_id, "model": model, "why": why}
