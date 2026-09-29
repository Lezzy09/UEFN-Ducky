"""Saved copies survive edits, reloads, restores, and deletion in both storage modes."""
from copy import deepcopy

import pytest
from backend.automations import store, versions
from backend.store import db
from frontend.ui_web.panel_api_automations import PanelApiAutomationsMixin


@pytest.fixture(params=[False, True], ids=["files", "database"])
def storage(request, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "use_db", lambda *_: request.param)
    monkeypatch.setattr(store, "_files_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "_announce_graphs_changed", lambda: None)
    monkeypatch.setattr(db, "app_root", lambda: tmp_path)
    yield request.param
    db.close_thread_connections()


def sample():
    return {"name": "Island", "kind": "pipeline", "graph": {
        "nodes": [{"id": "a", "type": "flow.wait", "x": 20, "y": 30, "config": {"seconds": 9}}],
        "edges": [], "groups": [{"id": "g", "name": "Setup", "node_ids": ["a"]}],
    }}


def test_every_save_is_immutable_and_restore_creates_another_version(storage):
    original = store.save_automation(sample())
    first = versions.list_versions(original["id"])[0]
    changed = deepcopy(original)
    changed["graph"]["nodes"][0]["config"]["seconds"] = 100
    changed["graph"]["groups"] = []
    changed["name"] = "Changed"
    store.save_automation(changed)
    store.save_automation(changed)  # Identical explicit saves are still kept.
    assert len(versions.list_versions(original["id"])) == 3
    old = versions.get_version(original["id"], first["id"])
    assert old["graph"] == original["graph"]
    store.append_run(original["id"], {"ok": True, "ended": 42})
    restored = store.save_automation(old)
    assert restored["graph"] == original["graph"]
    assert restored["runs"] == [{"ok": True, "ended": 42}]
    assert len(versions.list_versions(original["id"])) == 4
    assert store.get_automation(original["id"])["graph"] == original["graph"]
    store.delete_automation(original["id"])
    assert versions.get_version(original["id"], first["id"])["name"] == "Island"


def test_archives_preexisting_workflow_before_first_edit(storage):
    baseline = store.empty_workflow(name="Legacy")
    store._put(baseline)
    store.save_automation({"id": baseline["id"], "name": "New"})
    assert [row["name"] for row in versions.list_versions(baseline["id"])] == ["New", "Legacy"]


def test_versions_are_scoped_and_panel_api_returns_missing_errors(storage):
    first = store.save_automation(sample())
    second = store.save_automation({"name": "Other", "kind": "automation"})
    api = PanelApiAutomationsMixin()
    version_id = api.list_workflow_versions(first["id"])["versions"][0]["id"]
    assert api.get_workflow_version(first["id"], version_id)["workflow"]["id"] == first["id"]
    assert api.get_workflow_version(second["id"], version_id)["ok"] is False
    assert api.get_workflow_version(first["id"], "../../outside")["ok"] is False


def test_no_rolling_retention_limit(storage):
    saved = store.save_automation(sample())
    for i in range(25):
        store.save_automation({"id": saved["id"], "name": f"Edit {i}"})
    assert len(versions.list_versions(saved["id"])) == 26


def test_database_save_and_snapshot_roll_back_together(storage, monkeypatch):
    if not storage:
        return
    from backend.store.repos import automations as repo
    saved = store.save_automation(sample())
    archive = repo._archive
    def fail_after_archive(conn, doc):
        archive(conn, doc)
        raise RuntimeError("write failed")
    monkeypatch.setattr(repo, "_archive", fail_after_archive)
    with pytest.raises(RuntimeError, match="write failed"):
        store.save_automation({"id": saved["id"], "name": "Must not commit"})
    assert store.get_automation(saved["id"])["name"] == "Island"
    assert len(versions.list_versions(saved["id"])) == 1


def test_upgrade_from_schema_nine_preserves_existing_workflows(storage):
    if not storage:
        return
    legacy = store.empty_workflow(name="Before versions")
    store._put(legacy)
    conn = db.connect()
    conn.execute("DROP TABLE workflow_versions")
    conn.execute("PRAGMA user_version=9")
    db.reset_for_tests()
    assert store.get_automation(legacy["id"])["name"] == "Before versions"
    store.save_automation({"id": legacy["id"], "name": "After upgrade"})
    assert [row["name"] for row in versions.list_versions(legacy["id"])] == ["After upgrade", "Before versions"]
