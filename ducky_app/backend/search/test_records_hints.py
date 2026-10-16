"""api.search records (backend/search/records.py) and per-turn skill hints (hints.py)."""

from __future__ import annotations

import pytest

from backend.search import hints, indexer, records
from backend.store.repos import search as repo


@pytest.fixture
def scope(monkeypatch):
    current = {"id": "personal"}
    monkeypatch.setattr(records, "_scope", lambda plugin_id: current["id"])
    return current


def test_records_are_found_by_their_own_plugin_only(scope) -> None:
    wiki = records.SearchApi("wiki")
    other = records.SearchApi("cards")
    assert wiki.upsert("spawner", "Item spawner", "How the item spawner device grants weapons.", {"url": "/x"})["ok"]
    other.upsert("c1", "Healing card", "Heals the whole family.")
    rows = wiki.query("item spawner device")
    assert [r["id"] for r in rows] == ["spawner"] and rows[0]["meta"] == {"url": "/x"}
    assert "read" not in rows[0]
    assert all(r["id"] != "spawner" for r in other.query("item spawner device"))


def test_records_live_in_the_active_scope(scope) -> None:
    api = records.SearchApi("wiki")
    api.upsert("p1", "Local page", "storm circle settings")
    scope["id"] = "team-1"
    assert api.query("storm circle") == []
    api.upsert("p1", "Team page", "storm circle settings")
    assert [r["title"] for r in api.query("storm circle")] == ["Team page"]
    assert api.clear() == 1
    scope["id"] = "personal"
    assert [r["title"] for r in api.query("storm circle")] == ["Local page"]


def test_record_ids_and_caps(scope, monkeypatch) -> None:
    api = records.SearchApi("wiki")
    for bad in ("", "   ", "a:b", "x" * 201):
        with pytest.raises(ValueError):
            api.upsert(bad, "t", "x")
    monkeypatch.setattr(records, "MAX_RECORDS", 2)
    api.upsert("a", "A", "x")
    api.upsert("b", "B", "x")
    api.upsert("a", "A2", "y")  # replacing one is fine at the cap
    with pytest.raises(ValueError):
        api.upsert("c", "C", "x")
    assert api.delete("a") and not api.delete("a")


def test_uninstall_drops_the_plugins_records(scope) -> None:
    api = records.SearchApi("wiki")
    api.upsert("p1", "Page", "text")
    indexer.forget_plugin("wiki")
    assert repo.count_source("record:wiki:personal") == 0


# --------------------------------------------------------------------------- hints


def _pack() -> None:
    from frontend.app_paths import resolve_app_data_dir

    root = resolve_app_data_dir() / "skill_packs" / "npc"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: npc\ndescription: NPC enemies that patrol and shoot\nmetadata:\n  label: NPC\n---\n\n# NPC\n",
        encoding="utf-8")
    (root / "references" / "ranged.md").write_text(
        "---\ndescription: Ranged enemies\nmetadata:\n  label: Ranged\n---\n\n"
        "## Archer behavior\nThe archer enemy patrols, keeps away and shoots arrows at the nearest player.\n",
        encoding="utf-8")
    indexer.index_packs(indexer.live_pack_sources())


def test_hint_names_the_best_section_for_a_clear_request() -> None:
    _pack()
    text = hints.skill_hint("make an archer enemy that patrols and shoots arrows at the player")
    assert text.startswith("Relevant skills for this request")
    assert 'skill_read_subskill(pack_id="npc", subskill_id="ranged", section="Archer behavior")' in text
    assert len(text) <= len("Relevant skills for this request (read before acting): ") + hints.MAX_CHARS + 120


@pytest.mark.parametrize("chat", ["continue", "ok", "finish did you finish", "why is the plan not finished"])
def test_no_hint_for_chit_chat(chat: str) -> None:
    _pack()
    assert hints.skill_hint(chat) == ""


def test_hint_respects_the_chats_denied_packs() -> None:
    _pack()

    class Conv:
        disabled_packs = ["npc"]
        enabled_subskills: dict = {}

    assert hints.skill_hint("make an archer enemy that patrols and shoots arrows", conv=Conv()) == ""
