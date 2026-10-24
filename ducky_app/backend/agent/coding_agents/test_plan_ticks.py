"""A paused plan never tells agents to tick now."""

from __future__ import annotations

from backend.agent.coding_agents import plan_ticks


def _plan(status: str) -> dict:
    return {"id": "p1", "status": status, "nodes": [{"id": "s1", "content": "Step one", "status": "pending"}]}


def test_paused_plan_has_no_next_tick() -> None:
    out = plan_ticks.attach_next_tick({"ok": True}, _plan("paused"))
    assert out["next_tick"] is None
    assert out["tick_now"] == "Plan paused — do not start or tick steps until the owner resumes it."
    assert plan_ticks.format_plan_tick_nudge(_plan("paused")) == ""


def test_playing_plan_unchanged() -> None:
    out = plan_ticks.attach_next_tick({"ok": True}, _plan("playing"))
    assert out["next_tick"]["id"] == "s1"
    assert out["next_tick"]["action"] == "in_progress"
    assert out["tick_now"].startswith("[PLAN TICK] CHECK OFF NOW:")
