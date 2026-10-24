"""ducky_swarm_create: ask once, size the tree, preview, edits, mute, plan-first build, suggest."""

from __future__ import annotations

import json

import pytest

from backend.tools.panel import ducky_swarm as sw

GAME8 = ["Narrative: story", "Research: references", "Modeling: props", "Texture: props", "Verse: combat",
         "UI: HUD", "Tester: playtest", "Reviewer: code review"]
GAME12 = GAME8 + ["Level: layout", "Sound: sfx", "NPC: enemies", "VFX: hits"]


@pytest.fixture(autouse=True)
def _no_settings(monkeypatch):
    monkeypatch.setattr(sw, "_routing_context", lambda: (None, None))


def _jobs(names, model="m1"):
    return [{"name": n, "purpose": "", "task": "", "steps": [f"{n} step 1", f"{n} step 2"],
             "paths": [f"src/{n.split(':')[0].lower()}/**"], "model": model} for n in names]


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.n = 0

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def caller(self):
        return "lead"

    def group_create(self, name, parent_folder_id=""):
        self.calls.append(("group_create", name, parent_folder_id))
        gid = self._id("g")
        return {"id": gid, "folder_id": f"f-{gid}"}

    def add_leader(self, group_id, conv_id):
        self.calls.append(("add_leader", group_id, conv_id))

    def rename_chat(self, conv_id, title):
        self.calls.append(("rename_chat", conv_id, title))

    def ensure_plan(self, chat_id, goal):
        self.calls.append(("ensure_plan", chat_id))

    def plan_add_node(self, chat_id, content, parent_id="", kind="step", body_markdown=""):
        self.calls.append(("plan_add_node", content, parent_id, kind))
        return self._id("n")

    def invite(self, group_id, profile, name, model, write_allowed):
        self.calls.append(("invite", group_id, name, model, write_allowed))
        return self._id("c")

    def set_muted(self, conv_id, muted):
        self.calls.append(("set_muted", conv_id, muted))

    def assign(self, chat_id, node_id, assignee):
        self.calls.append(("assign", node_id, assignee))


def _create(names, model="m1", **kw):
    kw.setdefault("detail", 2)
    return sw.swarm_create("Shop island", _jobs(names, model), **kw)


# ---- s4-ask -------------------------------------------------------------------------------

def test_missing_answers_asks_agents_limits_and_each_model():
    api = FakeApi()
    out = sw.swarm_create("Shop island", _jobs(["Narrative: story", "Modeling: props", "Texture: props"], ""),
                          api=api)
    assert out["status"] == "needs_answers"
    ids = [q["id"] for q in out["questions"]]
    assert ids == ["detail", "agents", "size_limits", "model:0", "model:1", "model:2"]
    limits = out["questions"][2]
    assert limits["options"][0]["id"] == "8/5" and "Art: assets" in limits["options"][0]["description"]
    assert "Modeling" in out["questions"][4]["prompt"]
    assert api.calls == []


def test_given_model_is_not_asked_and_all_answers_go_on():
    jobs = _jobs(["Narrative: story", "Modeling: props"], "")
    jobs[0]["model"] = "claude-opus-5-5"
    out = sw.swarm_create("Shop island", jobs, agents="auto", max_agents=8, per_group=5, detail=2)
    assert [q["id"] for q in out["questions"]] == ["model:1"]
    out = _create(["Narrative: story", "Modeling: props"], agents="auto", max_agents=8, per_group=5)
    assert out["status"] == "needs_confirm"


# ---- s4-split -----------------------------------------------------------------------------

def _routed(names):
    return sw.normalize_jobs(_jobs(names))


def test_three_jobs_auto_is_flat():
    tree = sw.plan_tree(_routed(["Narrative: story", "Modeling: props", "Texture: props"]), "auto", 8, 5)
    assert [n.get("name") for n in tree] == ["Narrative lead", "Modeling lead", "Texture lead"]
    assert not list(sw.walk_groups(tree))


def test_eight_jobs_nest_into_art_and_code():
    tree = sw.plan_tree(_routed(GAME8), "auto", 8, 5)
    groups = {g["group"]: [s["name"] for s in g["seats"]] for g in sw.walk_groups(tree)}
    assert groups == {"Art: assets": ["Modeling lead", "Texture lead"], "Code: gameplay": ["Verse lead", "UI lead"]}
    top = [n["name"] for n in tree if "group" not in n]
    assert top == ["Narrative lead", "Research lead", "Tester", "Reviewer"]


def test_twelve_jobs_capped_at_eight_and_no_group_over_five():
    tree = sw.plan_tree(_routed(GAME12), "auto", 8, 5)
    seats = list(sw.walk_seats(tree))
    assert len(seats) == 8
    steps = sum(s["sub_plan"]["total"] for s in seats)
    assert steps == 24  # merged, nothing dropped
    assert all(len(g["seats"]) <= 5 for g in sw.walk_groups(tree))
    assert len([n for n in tree if "group" not in n]) <= 5


def test_big_area_splits_and_depth_stays_three():
    names = [f"Modeling: part {i}" for i in range(7)]
    tree = sw.plan_tree(_routed(names), "auto", 8, 3)
    art = tree[0]
    assert art["group"] == "Art: assets" and not art["seats"]
    assert all(len(g["seats"]) <= 3 and not g["groups"] for g in art["groups"])


# ---- preview, edits, mute -----------------------------------------------------------------

def test_preview_builds_nothing_and_marks_nested_groups_muted():
    api = FakeApi()
    out = _create(GAME8, agents="auto", max_agents=8, per_group=5, api=api)
    assert out["status"] == "needs_confirm" and api.calls == []
    preview = out["preview"]
    assert preview["agents"] == 8
    assert preview["muted"] == ["Art: assets", "Code: gameplay"]
    assert preview["lanes"]["Verse lead"] == ["src/verse/**"]
    seat = next(s for s in sw.walk_seats(preview["tree"]) if s["name"] == "Verse lead")
    assert seat["profile"] == "verse-coder" and seat["model"] == "m1"
    json.dumps(out)


def test_flat_swarm_has_nothing_to_mute():
    api = FakeApi()
    out = _create(["Narrative: story", "Modeling: props", "Texture: props"], agents="auto", max_agents=8,
                  per_group=5, edits=[{"drop": "Texture: props"}], confirm=True, api=api)
    assert out["status"] == "done"
    assert [s["name"] for s in sw.walk_seats(out["tree"])] == ["Narrative lead", "Modeling lead"]
    assert not [c for c in api.calls if c[0] == "set_muted"]


def test_edits_show_in_preview_and_in_built_tree():
    edits = [{"rename": "UI: HUD", "to": "UI: shop HUD"}, {"seat": "Tester", "model": "codex:gpt-5-mini"},
             {"unmute": "Art: assets"}]
    out = _create(GAME8, agents="auto", max_agents=8, per_group=5, edits=edits)
    preview = out["preview"]
    seats = {s["name"]: s for s in sw.walk_seats(preview["tree"])}
    assert seats["UI lead"]["job"] == "UI: shop HUD"
    assert seats["Tester"]["model"] == "codex:gpt-5-mini"
    assert preview["muted"] == ["Code: gameplay"]

    api = FakeApi()
    built = _create(GAME8, agents="auto", max_agents=8, per_group=5, edits=edits, confirm=True, api=api)
    assert built["status"] == "done"
    bseats = {s["name"]: s for s in sw.walk_seats(built["tree"])}
    assert set(bseats) == set(seats)
    assert ("plan_add_node", "UI: shop HUD", "", "subplan") in api.calls
    assert any(c[0] == "invite" and c[2] == "Tester" and c[3] == "codex:gpt-5-mini" for c in api.calls)
    groups = {g["group"]: g for g in sw.walk_groups(built["tree"])}
    muted = [c[1] for c in api.calls if c[0] == "set_muted"]
    assert muted == [groups["Code: gameplay"]["group_id"]]
    assert groups["Art: assets"]["muted"] is False


def test_bad_edit_names_the_choices():
    with pytest.raises(ValueError, match="No seat called"):
        _create(GAME8, agents="auto", max_agents=8, per_group=5, edits=[{"seat": "Nobody", "model": "x"}])


# ---- s4-build -----------------------------------------------------------------------------

def test_build_order_plan_first_then_seats_then_mute_then_assign():
    api = FakeApi()
    out = _create(GAME8, agents="auto", max_agents=8, per_group=5, confirm=True, api=api)
    assert out["status"] == "done"
    kinds = [c[0] for c in api.calls]
    assert kinds[:4] == ["group_create", "add_leader", "rename_chat", "ensure_plan"]
    assert api.calls[0] == ("group_create", "Shop island", "")
    assert api.calls[2] == ("rename_chat", "lead", "Lead: Shop island")
    last_plan = max(i for i, k in enumerate(kinds) if k == "plan_add_node")
    first_invite = kinds.index("invite")
    assert last_plan < first_invite < kinds.index("set_muted") < kinds.index("assign")
    assert max(i for i, k in enumerate(kinds) if k == "invite") < kinds.index("set_muted")
    assert kinds.count("plan_add_node") == 8 * 3  # a section + 2 steps per job
    assert kinds.count("assign") == 8 and kinds.count("set_muted") == 2
    # lanes go on at invite; nested groups sit in the root group's folder
    assert ("invite", out["root_group_id"], "Tester", "m1", ["src/tester/**"]) in api.calls
    assert ("group_create", "Art: assets", f"f-{out['root_group_id']}") in api.calls
    # result shape SwarmCard reads
    art = out["tree"][0]
    assert art["group"] == "Art: assets" and art["group_id"] and art["created"] and art["muted"]
    seat = art["seats"][0]
    assert {"name", "conv_id", "profile", "model", "created", "sub_plan"} <= set(seat)
    assert seat["sub_plan"]["title"] == "Modeling: props" and seat["sub_plan"]["total"] == 2
    assigned = {c[2] for c in api.calls if c[0] == "assign"}
    assert assigned == {s["conv_id"] for s in sw.walk_seats(out["tree"])}


def test_build_failure_reports_partial_tree():
    class Broken(FakeApi):
        def invite(self, *a):
            raise ValueError("lane overlaps")

    out = _create(GAME8, agents="auto", max_agents=8, per_group=5, confirm=True, api=Broken())
    assert out["status"] == "error" and "lane overlaps" in out["error"]


# ---- detail level -------------------------------------------------------------------------

SHOP = ["Modeling: props", "Texture: props", "Verse: combat", "Narrative: story"]


def test_no_detail_asks_it_with_agent_counts_per_level():
    out = sw.swarm_create("Shop island", _jobs(SHOP), agents="auto", max_agents=8, per_group=5)
    assert out["status"] == "needs_answers" and [q["id"] for q in out["questions"]] == ["detail"]
    q = out["questions"][0]
    assert q["prompt"] == "How finely should the work be split?"
    assert [o["id"] for o in q["options"]] == ["1", "2", "3", "4"]
    assert q["options"][1]["label"] == "2 Jobs (suggested)"
    assert [o["description"] for o in q["options"]] == [
        "3 agents", "4 agents", "8 agents in 1 sub-group", "8 agents in 3 sub-groups"]


def test_detail_3_previews_parts_and_every_level():
    api = FakeApi()
    out = _create(SHOP, agents="auto", max_agents=8, per_group=5, detail=3, api=api)
    p = out["preview"]
    assert out["status"] == "needs_confirm" and api.calls == []
    assert p["detail"] == 3
    assert [(lv["detail"], lv["agents"], lv["groups"]) for lv in p["levels"]] == [
        (1, 3, 0), (2, 4, 0), (3, 8, 1), (4, 8, 3)]
    seats = {s["name"]: s for s in sw.walk_seats(p["tree"])}
    assert seats["Blockout lead"]["job"] == "Modeling: blockout"
    assert seats["Blockout lead"]["profile"] == "3d-modeler" and seats["Blockout lead"]["paths"] == ["src/modeling/**"]
    blockout = next(s for s in sw.build_preview("g", sw.normalize_jobs(_jobs(SHOP)), "auto", 8, 5, None, 3)["jobs"]
                    .items() if s[0] == "Blockout lead")[1]
    assert [s["content"] for s in blockout["steps"]] == ["blockout: Modeling: props step 1",
                                                        "blockout: Modeling: props step 2"]


def test_detail_change_is_a_new_preview_and_limits_still_cap():
    api = FakeApi()
    one = _create(SHOP, agents="auto", max_agents=8, per_group=5, detail=1, api=api)["preview"]
    assert [s["name"] for s in sw.walk_seats(one["tree"])] == ["Art lead", "Code lead", "Story lead"]
    art = next(s for s in sw.walk_seats(one["tree"]) if s["name"] == "Art lead")
    assert art["sub_plan"]["total"] == 4  # Modeling's and Texture's steps both kept
    four = _create(SHOP, agents="auto", max_agents=8, per_group=5, detail=4, api=api)["preview"]
    assert sorted(g["group"] for g in sw.walk_groups(four["tree"])) == [
        "Modeling: parts", "Texture: parts", "Verse: parts"]
    assert four["muted"] and api.calls == []
    capped = _create(SHOP, agents="auto", max_agents=5, per_group=5, detail=3)["preview"]
    assert capped["agents"] == 5


def test_confirm_builds_the_chosen_level():
    api = FakeApi()
    out = _create(SHOP, agents="auto", max_agents=8, per_group=5, detail=4, confirm=True, api=api)
    assert out["status"] == "done" and out["agents"] == 8
    made = [c[1] for c in api.calls if c[0] == "group_create"]
    assert made == ["Shop island", "Modeling: parts", "Texture: parts", "Verse: parts"]
    assert [c[1] for c in api.calls if c[0] == "plan_add_node" and c[3] == "subplan"][:3] == [
        "Modeling: blockout", "Modeling: hero props", "Modeling: set dressing"]
    assert len([c for c in api.calls if c[0] == "set_muted"]) == 3


# ---- suggest_swarm ------------------------------------------------------------------------

def _section(name, files, n=2):
    return {"id": name, "content": name, "body_markdown": f"Files: {files}",
            "children": [{"id": f"{name}-{i}", "content": f"{name} step {i}"} for i in range(n)]}


def test_five_sections_get_a_suggestion():
    plan = {"title": "Shop island", "nodes": [
        _section("Verse: combat", "Content/Verse/Combat/**"), _section("UI: shop HUD", "Content/UI/**"),
        _section("Modeling: props", "Content/Meshes/**"), _section("Texture: props", "Content/Textures/**"),
        _section("Tester: playtest", "tests/**")]}
    out = sw.suggest_swarm(plan)
    assert out["agents"] == 5 and out["jobs"][0] == "Verse: combat"
    assert out["routes"][0]["profile"] == "verse-coder"
    assert out["call"].startswith("ducky_swarm_create(") and "Run this as a swarm of 5?" == out["ask"]


def test_small_or_overlapping_plans_get_nothing():
    assert sw.suggest_swarm({"nodes": [{"id": str(i), "content": f"s{i}"} for i in range(4)]}) is None
    overlap = {"nodes": [_section("A", "src/**"), _section("B", "src/**"), _section("C", "docs/**")]}
    assert sw.suggest_swarm(overlap) is None
