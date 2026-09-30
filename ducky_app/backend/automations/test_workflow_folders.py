"""Folders in the Workflows list: a path per workflow inside its owner."""

from __future__ import annotations

import pytest

from backend.automations import store, versions


@pytest.fixture(autouse=True)
def files_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "use_db", lambda *_: False)
    monkeypatch.setattr(store, "_files_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "_announce_graphs_changed", lambda: None)


def folders() -> dict[str, str]:
    return {w["name"]: w["folder"] for w in store.list_workflows()}


def test_folder_paths_are_tidied():
    assert store.normalize_folder("  Play tests / / Tycoon  ") == "Play tests/Tycoon"
    assert store.normalize_folder("a\\b") == "a/b"
    assert store.normalize_folder(None) == "" and store.normalize_folder("///") == ""
    assert store.normalize_folder("x" * 100) == "x" * 64
    saved = store.save_workflow({"name": "Tycoon test", "folder": " Tests /Tycoon ", "graph": {"nodes": [], "edges": []}})
    assert saved["folder"] == "Tests/Tycoon"
    assert store.save_workflow({"id": saved["id"], "name": "Renamed"})["folder"] == "Tests/Tycoon"


def test_filing_a_workflow_keeps_its_place_and_history():
    wf = store.save_workflow({"name": "Start game", "graph": {"nodes": [], "edges": []}})
    before = store.get_workflow(wf["id"])["updated"]
    count = len(versions.list_versions(wf["id"]))
    assert store.set_folder(wf["id"], "Play tests")["folder"] == "Play tests"
    assert store.get_workflow(wf["id"])["updated"] == before
    assert len(versions.list_versions(wf["id"])) == count
    assert store.set_folder("missing", "x") is None


def test_rename_move_and_delete_folders_keep_the_workflows():
    for name, folder in (("A", "Play tests"), ("B", "Play tests/Tycoon"), ("C", "Play testsX"), ("D", "")):
        store.save_workflow({"name": name, "folder": folder, "graph": {"nodes": [], "edges": []}})
    assert store.move_folder("local", "Play tests", "QA/Play") == 2
    assert folders() == {"A": "QA/Play", "B": "QA/Play/Tycoon", "C": "Play testsX", "D": ""}
    assert store.move_folder("local", "QA/Play/Tycoon", "QA/Play") == 1  # delete: into its parent
    assert store.move_folder("local", "QA", "") == 2  # delete a top folder: contents go to the top
    assert folders() == {"A": "Play", "B": "Play", "C": "Play testsX", "D": ""}
    assert store.move_folder("teamT", "Play", "Elsewhere") == 0  # another owner's folder
    with pytest.raises(ValueError):
        store.move_folder("local", "Play", "Play/Inner")
    with pytest.raises(ValueError):
        store.move_folder("local", "", "Anything")
