"""swarm_preview panel method: pure, repeatable, fast."""

from __future__ import annotations

import time

from backend.tools.panel import ducky_swarm as sw
from frontend.ui_web.panel_api_swarm import PanelApiSwarmMixin

KINDS = ["Narrative", "Research", "Modeling", "Texture", "Verse", "UI", "Level", "Sound", "NPC", "VFX"]


def _jobs(n):
    return [{"name": f"{KINDS[i % len(KINDS)]}: part {i}", "steps": [f"step {i}a", f"step {i}b"],
             "paths": [f"src/p{i}/**"], "model": "m1"} for i in range(n)]


def test_same_args_same_tree_and_nothing_built(monkeypatch):
    monkeypatch.setattr(sw, "_routing_context", lambda: (None, None))
    monkeypatch.setattr(sw, "build_swarm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("built")))
    api = PanelApiSwarmMixin()
    one = api.swarm_preview("Shop island", _jobs(8), detail=2)
    two = api.swarm_preview("Shop island", _jobs(8), detail=2)
    assert one["ok"] and one["ui"] == "swarm_builder" and one["preview"]["tree"] == two["preview"]["tree"]
    assert one["preview"]["agents"] == len(one["seats"]) == 8
    assert api.swarm_preview("Shop island", _jobs(8), edits=[{"seat": "Nobody", "model": "x"}])["ok"] is False
    assert api.swarm_preview("", _jobs(2))["ok"] is False


def _sub(name, files, assignee=""):
    return {"id": name, "content": name, "assignee": assignee, "body_markdown": f"**Files:** {files}",
            "children": [{"id": f"{name}-1", "content": f"{name} step", "body_markdown": "Done when: tests pass."}]}


INVENTORY = {"title": "Inventory UI", "nodes": [{"id": "s", "content": "Inventory", "children": [
    _sub("API", "`backend/inv/**`"), _sub("Widget", "`web/src/inv/**`"), _sub("Tests", "`tests/inv/**`")]}]}


def test_swarm_suggest_drafts_one_seat_per_unassigned_sub_plan(monkeypatch):
    import backend.agent.coding_agents.plans as plans

    monkeypatch.setattr(sw, "_routing_context", lambda: (None, None))
    monkeypatch.setattr(plans, "load_plan_view", lambda cid, project_root=None: INVENTORY)
    out = PanelApiSwarmMixin().swarm_suggest("lead", project_root="x")["suggestion"]
    assert out["ui"] == "swarm_builder" and out["goal"] == "Inventory UI"
    assert sorted(map(tuple, out["preview"]["lanes"].values())) == [
        ("backend/inv/**",), ("tests/inv/**",), ("web/src/inv/**",)]
    assert len(out["seats"]) == 3 and all(s["steps"] == 1 for s in out["seats"])


def test_no_suggestion_for_one_sub_plan_assigned_or_overlapping(monkeypatch):
    monkeypatch.setattr(sw, "_routing_context", lambda: (None, None))
    assert sw.suggest_from_plan({"title": "t", "nodes": [_sub("API", "a/**")]}) is None
    assert sw.suggest_from_plan({"nodes": [_sub("A", "a/**"), _sub("B", "b/**", assignee="c1")]}) is None
    assert sw.suggest_from_plan({"nodes": [_sub("A", "a/**"), _sub("B", "a/**")]}) is None


def test_plan_launch_calls_launch_plan_once_and_passes_it_through(monkeypatch):
    from backend.tools.panel import swarm_build as sb

    calls = []
    result = {"ok": True, "seated": ["API", "Widget"], "failed": [], "root_group_id": "g1"}
    monkeypatch.setattr(sb, "launch_plan", lambda chat_id, api=None: calls.append(chat_id) or result)
    assert PanelApiSwarmMixin().plan_launch(" lead ") is result and calls == ["lead"]

    def boom(chat_id, api=None):
        raise sb.SwarmBuildError("Nothing to seat", created=0)

    monkeypatch.setattr(sb, "launch_plan", boom)
    assert PanelApiSwarmMixin().plan_launch("lead") == {"ok": False, "error": "Nothing to seat", "created": 0}


def test_plan_set_planned_assignee_stores_it_and_starts_nobody(monkeypatch):
    import json as _json

    from backend.tools.panel import ducky_panel, swarm_build as sb

    seen = []
    monkeypatch.setattr(ducky_panel, "ducky_plan_update_node",
                        lambda **kw: seen.append(kw) or _json.dumps({"ok": True, "node": {"id": kw["node_id"],
                                                                     "planned_assignee": kw["planned_assignee"]}}))
    monkeypatch.setattr(sb, "launch_plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    out = PanelApiSwarmMixin().plan_set_planned_assignee("lead", "api", " developer ")
    assert out == {"ok": True, "node": {"id": "api", "planned_assignee": "developer"}}
    assert seen == [{"node_id": "api", "chat_id": "lead", "planned_assignee": "developer"}]
    assert set(seen[0]) == {"node_id", "chat_id", "planned_assignee"}  # no assignee: nobody starts
    monkeypatch.setattr(ducky_panel, "ducky_plan_update_node",
                        lambda **kw: _json.dumps({"ok": False, "error": "node not found"}))
    assert PanelApiSwarmMixin().plan_set_planned_assignee("lead", "x", "dev") == {"ok": False, "error": "node not found"}


def test_twenty_jobs_under_50_ms(monkeypatch):
    monkeypatch.setattr(sw, "_routing_context", lambda: (None, None))
    api = PanelApiSwarmMixin()
    api.swarm_preview("warm", _jobs(20), max_agents=20)
    start = time.perf_counter()
    out = api.swarm_preview("Big", _jobs(20), max_agents=20)
    assert out["ok"] and out["preview"]["agents"] == 20
    assert time.perf_counter() - start < 0.05
