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
    saved = store.save_automation({"name": "Grouped", "kind": kind, "graph": graph()})
    loaded = store.get_automation(saved["id"])
    assert loaded["graph"]["groups"] == graph()["groups"]
    loaded["graph"]["groups"][0]["node_ids"] = ["b"]
    store.save_automation(loaded)
    assert store.get_automation(saved["id"])["graph"]["groups"][0]["node_ids"] == ["b"]
    loaded["graph"]["groups"] = []
    store.save_automation(loaded)
    final = store.get_automation(saved["id"])["graph"]
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
