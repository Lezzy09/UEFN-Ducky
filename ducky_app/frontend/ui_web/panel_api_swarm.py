"""Swarm builder card methods. Mixin for PanelApi.

``swarm_preview`` reruns the pure preview on every slider move: it never creates a group,
chat or plan step. It runs on the default ``bg`` call lane; ``LIGHT_METHODS`` lists it for
the Chat API hand-off that registers this mixin.
"""

from __future__ import annotations

from typing import Any

LIGHT_METHODS = frozenset({"swarm_preview", "swarm_suggest"})


class PanelApiSwarmMixin:
    def swarm_preview(self, goal: str, jobs: list[dict[str, Any]], detail: int = 2, agents: Any = "auto",
                      max_agents: int = 8, per_group: int = 5,
                      edits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """The ``ui: swarm_builder`` card for these answers; ``{ok: false, error}`` on a bad edit."""
        from backend.tools.panel.ducky_swarm import build_preview, card, normalize_jobs

        goal = str(goal or "").strip()
        routed = normalize_jobs(jobs)
        if not goal or not routed:
            return {"ok": False, "error": "goal and jobs are required"}
        try:
            preview = build_preview(goal, routed, agents, int(max_agents or 0), int(per_group or 0),
                                    edits, int(detail or 2))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **card("preview", preview)}

    def swarm_suggest(self, chat_id: str, project_root: str | None = None) -> dict[str, Any]:
        """``{ok, suggestion}``: the chat's plan as a swarm card (one seat per unassigned sub plan), or None."""
        from backend.agent.coding_agents.plans import load_plan_view
        from backend.tools.panel.ducky_swarm import suggest_from_plan

        if project_root is None:
            from frontend.settings import PanelSettings

            project_root = PanelSettings.load().uefn_project_root
        try:
            plan = load_plan_view(str(chat_id or "").strip(), project_root=project_root)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "suggestion": suggest_from_plan(plan)}
