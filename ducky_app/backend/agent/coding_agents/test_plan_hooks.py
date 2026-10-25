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


def test_sections_are_not_gated(monkeypatch):
    monkeypatch.setattr(tick_gate, "check_tick", lambda cid, node: "refused")
    plan_hooks.before_complete({}, {"id": "sec", "children": [{"id": "s1"}]}, "lead")
