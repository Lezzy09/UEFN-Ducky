"""api.search records (backend/search/records.py) and per-turn skill hints (hints.py)."""

from __future__ import annotations

import pytest

from backend.search import hints, indexer, records
from backend.store.repos import search as repo


@pytest.fixture
def scope(monkeypatch):
    current = {"id": "personal", "account": "_local"}
    monkeypatch.setattr(records, "_scope", lambda plugin_id: (f"{current['account']}~{current['id']}", current["id"]))
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
    assert repo.count_source("record:wiki:_local~personal") == 0
    with pytest.raises(ValueError):  # a thread that outlived the uninstall cannot write back
        api.upsert("p2", "Late", "text")
    indexer.plugin_installed("wiki")
    assert api.upsert("p2", "Again", "text")["ok"]


def test_records_of_one_account_are_never_shown_to_another(monkeypatch) -> None:
    # Every account's Local scope is "personal"; the account is part of the key.
    from backend.uefn_plugins import scopes

    who = {"account": "a_alice"}
    monkeypatch.setattr(scopes, "active_scope", lambda plugin: {"account": who["account"], "id": "personal"})
    api = records.SearchApi("wiki")
    assert api.upsert("p1", "Alice page", "storm circle notes")["scope"] == "personal"
    who["account"] = "a_bob"
    assert api.query("storm circle") == []
    assert api.clear() == 0  # Bob cannot clear Alice's records
    who["account"] = "a_alice"
    assert [r["title"] for r in api.query("storm circle")] == ["Alice page"]


def test_no_scope_no_records(monkeypatch) -> None:
    from backend.uefn_plugins import scopes

    def broken(plugin):
        raise RuntimeError("no account data key")

    monkeypatch.setattr(scopes, "active_scope", broken)
    api = records.SearchApi("wiki")
    assert api.query("anything") == []
    with pytest.raises(RuntimeError):
        api.upsert("p1", "t", "x")  # never a shared fallback bucket


def test_other_plugins_records_never_crowd_out_yours(scope) -> None:
    other = records.SearchApi("cards")
    for i in range(70):
        other.upsert(f"c{i}", f"Storm card {i}", "storm circle storm circle storm circle")
    mine = records.SearchApi("wiki")
    mine.upsert("page", "Storm page", "a note about the storm circle")
    assert [r["id"] for r in mine.query("storm circle")] == ["page"]


def test_a_record_id_comes_back_even_when_meta_has_its_own_id(scope) -> None:
    api = records.SearchApi("wiki")
    api.upsert("p#2", "Spawner", "item spawner device grants weapons", {"id": "p", "section": 2})
    row = api.query("item spawner device")[0]
    assert row["id"] == "p#2" and row["meta"] == {"id": "p", "section": 2}
    assert api.delete(row["id"])


def test_an_unchanged_record_is_not_embedded_again(scope, monkeypatch) -> None:
    from backend.search import embedder

    api = records.SearchApi("wiki")
    api.upsert("p1", "Page", "storm circle settings")
    emb = embedder.get_embedder()
    if emb is None:
        pytest.skip("no meaning model in this checkout")
    calls: list[int] = []
    real = type(emb).encode
    monkeypatch.setattr(type(emb), "encode", lambda self, texts: calls.append(1) or real(self, texts))
    api.upsert("p1", "Page", "storm circle settings")
    assert calls == []


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


def test_hint_follows_the_request_not_the_reply_instructions() -> None:
    # Oct 16 live test: "…stats save between sessions? Read the matching skill guidance
    # first, answer in four short lines and name the skill section you read." hinted
    # UEFN Ducky's own how-to sections, not persistence.
    from frontend.app_paths import resolve_app_data_dir

    _pack()
    root = resolve_app_data_dir() / "skill_packs" / "howto"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: howto\ndescription: How agents read skill guidance and answer\nmetadata:\n  label: How to\n---\n\n"
        "## Reading skill sections\nRead the matching skill guidance first, answer in short lines, "
        "name the skill section you read and do not change any files.\n",
        encoding="utf-8")
    indexer.index_packs(indexer.live_pack_sources())
    text = hints.skill_hint(
        "Make an archer enemy that patrols and shoots arrows at the player. Read the matching skill guidance "
        "first, answer in four short lines and name the skill section you read. Do not change any files.")
    assert 'pack_id="npc"' in text and 'pack_id="howto"' not in text


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


def test_a_reinstalled_plugin_heals_a_leftover_uninstall_mark(scope, monkeypatch) -> None:
    from backend.uefn_plugins import store as plugin_store

    api = records.SearchApi("wiki")
    api.upsert("p1", "Page", "text")
    repo.forget_records("wiki")  # uninstalled; the clear at reinstall did not land
    monkeypatch.setattr(plugin_store, "is_plugin_installed", lambda pid: False)
    with pytest.raises(repo.PluginGone):
        api.upsert("p2", "Late", "text")
    monkeypatch.setattr(plugin_store, "is_plugin_installed", lambda pid: True)
    assert api.upsert("p2", "After reinstall", "text")["ok"]
