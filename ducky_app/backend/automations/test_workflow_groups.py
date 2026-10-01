"""Visual grouping survives saving without changing executable nodes or edges."""
import pytest

from backend.automations import store


def graph():
    return {
        "nodes": [{"id": key, "type": "flow.wait", "x": i * 100, "y": 0, "config": {}} for i, key in enumerate(["a", "b", "c"])],
        "edges": [{"source": "a", "target": "b", "kind": "main"}],
        "groups": [{"id": "g", "name": "Island setup", "node_ids": ["a", "b"]}],
    }


@pytest.mark.parametrize("kind", ["pipeline", "automation"])
def test_group_save_reload_and_ungroup(kind, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "use_db", lambda *_: False)
    monkeypatch.setattr(store, "_files_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "_announce_graphs_changed", lambda: None)
    saved = store.save_workflow({"name": "Grouped", "kind": kind, "graph": graph()})
    loaded = store.get_workflow(saved["id"])
    assert loaded["graph"]["groups"] == graph()["groups"]
    loaded["graph"]["groups"][0]["node_ids"] = ["b"]
    store.save_workflow(loaded)
    assert store.get_workflow(saved["id"])["graph"]["groups"][0]["node_ids"] == ["b"]
    loaded["graph"]["groups"] = []
    store.save_workflow(loaded)
    final = store.get_workflow(saved["id"])["graph"]
    assert final["groups"] == []
    assert final["nodes"] == loaded["graph"]["nodes"]
    assert final["edges"] == graph()["edges"]


def test_normalization_removes_missing_duplicate_and_empty_memberships():
    raw = graph()
    raw["groups"] = [
        {"id": "g", "name": "  Setup  ", "node_ids": ["a", "a", "missing", {}]},
        {"id": "g", "name": "Duplicate", "node_ids": ["b"]},
        {"id": "g2", "node_ids": ["a", "b"]},
        {"id": "empty", "node_ids": []},
        {"id": "bad", "node_ids": "c"}, None,
    ]
    assert store.normalize_graph(raw)["groups"] == [
        {"id": "g", "name": "Setup", "node_ids": ["a"]},
        {"id": "g2", "name": "Group", "node_ids": ["b"]},
    ]
    raw["nodes"] = []
    assert store.normalize_graph(raw)["groups"] == []


def test_legacy_graphs_and_invalid_group_containers():
    raw = graph()
    del raw["groups"]
    assert "groups" not in store.normalize_graph(raw)
    raw["groups"] = {"bad": True}
    assert store.normalize_graph(raw)["groups"] == []


def test_nested_groups_keep_parents_and_drop_loops_and_empty_boxes():
    raw = graph()
    raw["groups"] = [
        {"id": "outer", "name": "Outer", "node_ids": []},
        {"id": "inner", "name": "Inner", "node_ids": ["a"], "parent_id": "outer"},
        {"id": "side", "name": "Side", "node_ids": ["b"], "parent_id": "missing"},
        {"id": "loop1", "name": "L1", "node_ids": ["c"], "parent_id": "loop2"},
        {"id": "loop2", "name": "L2", "node_ids": [], "parent_id": "loop1"},
        {"id": "hollow", "name": "Only an empty child", "node_ids": []},
        {"id": "empty", "name": "Empty", "node_ids": [], "parent_id": "hollow"},
    ]
    groups = store.normalize_graph(raw)["groups"]
    assert {"id": "outer", "name": "Outer", "node_ids": []} in groups  # holds a group, no nodes of its own
    assert {"id": "inner", "name": "Inner", "node_ids": ["a"], "parent_id": "outer"} in groups
    assert {"id": "side", "name": "Side", "node_ids": ["b"]} in groups
    assert {"id": "loop1", "name": "L1", "node_ids": ["c"]} in groups  # the loop is broken at its first box
    assert [g["id"] for g in groups] == ["outer", "inner", "side", "loop1"]  # loop2, hollow, empty had nothing inside
    raw["nodes"] = [n for n in raw["nodes"] if n["id"] != "a"]
    assert [g["id"] for g in store.normalize_graph(raw)["groups"]] == ["side", "loop1"]


def test_group_colors_keep_known_names_only():
    raw = graph()
    raw["groups"] = [
        {"id": "g", "name": "Setup", "node_ids": ["a"], "color": "amber"},
        {"id": "h", "name": "Tests", "node_ids": ["b"], "color": "#ff0000"},
    ]
    assert store.normalize_graph(raw)["groups"] == [
        {"id": "g", "name": "Setup", "node_ids": ["a"], "color": "amber"},
        {"id": "h", "name": "Tests", "node_ids": ["b"]},
    ]


def test_node_colors_keep_known_names_only():
    raw = graph()
    raw["nodes"][0]["color"] = "purple"
    raw["nodes"][1]["color"] = "chartreuse"
    nodes = store.normalize_graph(raw)["nodes"]
    assert nodes[0]["color"] == "purple"
    assert "color" not in nodes[1] and "color" not in nodes[2]


def test_locks_survive_saving_and_only_true_counts():
    raw = graph()
    raw["nodes"][0]["locked"] = True
    raw["nodes"][1]["locked"] = "yes"
    raw["groups"][0]["locked"] = True
    out = store.normalize_graph(raw)
    assert [n.get("locked") for n in out["nodes"]] == [True, None, None]
    assert out["groups"][0]["locked"] is True


def test_icons_keep_one_short_symbol_only():
    raw = graph()
    raw["nodes"][0]["icon"] = " 🎯 "
    raw["nodes"][1]["icon"] = "not an icon"
    raw["nodes"][2]["icon"] = 7
    raw["groups"][0]["icon"] = "👨‍👩‍👧"
    out = store.normalize_graph(raw)
    assert [n.get("icon") for n in out["nodes"]] == ["🎯", None, None]
    assert out["groups"][0]["icon"] == "👨‍👩‍👧"


def test_locked_changes_names_what_a_save_would_break():
    from backend.automations.locks import changed_nodes, group_members, locked_changes

    old = graph()
    old["nodes"][0]["locked"] = True
    for node, label in zip(old["nodes"], ["Start", "Middle", "Last"]):
        node["label"] = label
    old["groups"] = [
        {"id": "g", "name": "Outer", "node_ids": ["b"], "locked": True},
        {"id": "h", "name": "Inner", "node_ids": ["c"], "parent_id": "g"},
    ]
    assert group_members(old["groups"], "g") == ["b", "c"]
    assert locked_changes(old, old) == []
    moved = store.normalize_graph(old)
    moved["nodes"][0]["x"] = 5  # locked itself
    moved["nodes"][2]["label"] = "Renamed"  # inside a group inside a locked group
    assert locked_changes(old, moved) == ["Start", "Last"]
    rewired = store.normalize_graph(old)
    rewired["edges"] = []
    assert locked_changes(old, rewired) == ["Start", "Middle"]  # both ends of the wire are locked
    unlocked = store.normalize_graph(old)
    unlocked["groups"][0].pop("locked")
    assert locked_changes(old, unlocked) == ["group Outer"]
    gone = store.normalize_graph(old)
    gone["nodes"] = gone["nodes"][1:]
    assert locked_changes(old, gone) == ["Start", "Middle"]  # removed, and its wire to Middle with it
    assert changed_nodes(old, moved) == ["a", "c"]
    assert changed_nodes(None, old) == ["a", "b", "c"]
