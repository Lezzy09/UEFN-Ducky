"""Workflows first: the finder matches tasks to saved workflows and templates."""

from backend.automations.finder import find, words
from backend.automations.templates import list_templates


def test_words_fold_synonyms_and_drop_filler():
    assert words("Please make me 3D models of props") == ["3d"]
    assert words("Remove the backgrounds from pictures") == ["remove", "background", "picture"]


def test_templates_found_for_everyday_tasks():
    rows = list_templates()

    def best(task):
        return (find(task, [], rows)["templates"] or [{}])[0].get("id")

    assert best("make a 3D model of a chest and put it in UEFN") == "builtin:pipe-prompt-3d-uefn"
    assert best("prompt to character with animations") == "builtin:pipe-character-prompt"
    assert best("summarize this pdf") == "builtin:pipe-pdf-summary"
    assert best("translate text to spanish") == "builtin:pipe-translate"
    assert best("play test the tycoon income") == "builtin:tycoon-income-loop"


def test_saved_workflows_rank_by_name_first():
    rows = [
        {"id": "a", "name": "Daily backup", "description": "copies the island"},
        {"id": "b", "name": "Island backup", "description": "zips files", "folder": "Ops"},
    ]
    found = find("backup the island", rows, [])
    assert [w["id"] for w in found["workflows"]][0] == "b"
    assert found["workflows"][0]["matched"] == ["backup", "uefn"]
    assert find("", rows, []) == {"workflows": [], "templates": [], "words": []}
