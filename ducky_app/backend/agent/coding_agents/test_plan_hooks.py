"""Completion hooks: what runs when a plan step or section completes."""

from __future__ import annotations

import pytest

from backend.agent import verify_evidence
from backend.agent.coding_agents import plan_hooks, plans, tick_gate


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKY_STORE_BACKEND_PLANS", "files")
    root = str(tmp_path)
    plans.create_plan("lead", nodes=[
        {"id": "sec", "content": "Seat work", "children": [
            {"id": "s1", "content": "First"}, {"id": "s2", "content": "Second"}]},
    ], project_root=root)
    plans.update_node("lead", "s1", status="in_progress", project_root=root)
    yield root
    plans.drain_after_save()


def _status(root: str, node_id: str) -> str:
    return plans._walk_find(plans.load_plan("lead", root)["nodes"], node_id)[2]["status"]


def test_a_refusing_gate_keeps_the_step_open(store, monkeypatch):
    seen = []
    message = "Can't tick: 2 files in your lane aren't committed: a.py, b.py."
    monkeypatch.setattr(verify_evidence, "current_conversation", lambda: "member")
    monkeypatch.setattr(tick_gate, "check_tick", lambda cid, node: seen.append((cid, node["id"])) or message)
    with pytest.raises(ValueError, match="aren't committed"):
        plans.update_node("lead", "s1", status="completed", project_root=store)
    assert _status(store, "s1") == "in_progress"
    assert seen == [("member", "s1")]  # the member calling, not the lead whose plan it is


def test_a_passing_gate_completes_the_step(store, monkeypatch):
    monkeypatch.setattr(tick_gate, "check_tick", lambda cid, node: None)
    plans.update_node("lead", "s1", status="completed", project_root=store)
    assert _status(store, "s1") == "completed"


def test_a_broken_gate_never_blocks_the_tick(store, monkeypatch):
    def boom(cid, node):
        raise RuntimeError("git missing")
    monkeypatch.setattr(tick_gate, "check_tick", boom)
    plans.update_node("lead", "s1", status="completed", project_root=store)
    assert _status(store, "s1") == "completed"


@pytest.fixture
def team(tmp_path, monkeypatch):
    """A lead's plan with two seats' sections, fake lanes and a fake hand-over table."""
    from types import SimpleNamespace

    from backend.tools.panel import swarm_build
    from frontend.ui_web import project_chats

    monkeypatch.setenv("DUCKY_STORE_BACKEND_PLANS", "files")
    monkeypatch.setattr(project_chats, "load_conversation_meta",
                        lambda cid, project_root=None: SimpleNamespace(parent_conv_id="grp"))
    monkeypatch.setattr(tick_gate, "check_tick", lambda cid, node: None)
    from backend.agent import a2a_client
    monkeypatch.setattr(a2a_client, "send_notice", lambda **kw: None)
    lanes = {"seat-a": ["x.py", "y.py"], "seat-b": ["z.py"]}
    sets: list[tuple[str, list[str]]] = []
    table: list[dict] = []

    def set_lane(conv, lane):
        sets.append((conv, lane))
        lanes[conv] = lane

    monkeypatch.setattr(plan_hooks, "_lane", lambda conv: lanes.get(conv))
    monkeypatch.setattr(plan_hooks, "_set_lane", set_lane)
    monkeypatch.setattr(swarm_build, "handovers_for", lambda nid: [r for r in table if r["from_section"] == nid])
    root = str(tmp_path)
    plans.create_plan("lead", nodes=[
        {"id": "A", "content": "Split", "assignee": "seat-a", "children": [
            {"id": "a1", "content": "Split the file"}, {"id": "a2", "content": "Tests"}]},
        {"id": "B", "content": "Composer", "assignee": "seat-b", "children": [{"id": "b1", "content": "Use it"}]},
    ], project_root=root)
    yield SimpleNamespace(root=root, lanes=lanes, sets=sets, table=table)
    plans.drain_after_save()


def _tick(root: str, node_id: str) -> None:
    plans.update_node("lead", node_id, status="completed", project_root=root)
    plans.drain_after_save()
    plans.drain_after_save()  # a lead point added by a hook saves again


def test_a_finished_section_hands_its_files_over_once(team):
    team.table.append({"from_section": "A", "to_section": "B", "paths": ["x.py"]})
    _tick(team.root, "a1")
    assert team.sets == []  # the section isn't done yet
    _tick(team.root, "a2")
    assert team.lanes == {"seat-a": ["y.py"], "seat-b": ["z.py", "x.py"]}
    assert len(team.sets) == 2
    _tick(team.root, "b1")
    assert len(team.sets) == 2  # moved once


def test_a_hand_over_tied_to_a_step_moves_when_the_step_completes(team):
    team.table.append({"from_section": "a1", "to_section": "B", "paths": ["x.py"]})
    _tick(team.root, "a1")
    assert team.lanes["seat-b"] == ["z.py", "x.py"] and team.lanes["seat-a"] == ["y.py"]


def test_a_failed_hand_over_keeps_the_tick_and_adds_a_lead_point(team, monkeypatch):
    def refuse(conv, lane):
        raise ValueError("Lane overlaps another member's lane")
    monkeypatch.setattr(plan_hooks, "_set_lane", refuse)
    team.table.append({"from_section": "a1", "to_section": "B", "paths": ["x.py"]})
    _tick(team.root, "a1")
    doc = plans.load_plan("lead", team.root)
    assert plans._walk_find(doc["nodes"], "a1")[2]["status"] == "completed"
    point = [n for n in doc["nodes"] if n["content"].startswith("Move lane by hand")]
    assert len(point) == 1 and "x.py from seat-a to seat-b" in point[0]["content"]
    assert "overlaps" in point[0]["body_markdown"]


def test_sections_are_not_gated(monkeypatch):
    monkeypatch.setattr(tick_gate, "check_tick", lambda cid, node: "refused")
    plan_hooks.before_complete({}, {"id": "sec", "children": [{"id": "s1"}]}, "lead")
