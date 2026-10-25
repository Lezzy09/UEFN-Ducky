"""Teams are built with one ducky_swarm_create call. Oct 2026: hand-built swarms (group_create /
spawn_chat / set_lane chained by hand) left half-made groups and seats without lanes."""

from __future__ import annotations

from pathlib import Path

from backend.agent.hard_rules import AGENT_HARD_RULES

SKILL = Path(__file__).resolve().parents[2] / "frontend" / "skill_packs" / "ducky" / "references" / "groups_and_lanes.md"


def test_hard_rules_teams_go_through_swarm_create() -> None:
    assert "Team = one `ducky_swarm_create` call (HARD)" in AGENT_HARD_RULES
    assert "all seats or none" in AGENT_HARD_RULES
    assert "never hand-chain group/spawn/lane tools" in AGENT_HARD_RULES


def test_groups_skill_names_swarm_create_with_an_example() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "ducky_swarm_create(" in text
    assert "never hand-chain" in text
