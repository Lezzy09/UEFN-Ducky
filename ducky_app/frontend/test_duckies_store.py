"""Duckies live in their own table and are never removed (migration 0014).

Twice (Sep 28 and Sep 30 2026) every shipped ducky vanished: a hide list in settings
held all 13 ids with the "user chose this" flag, so nothing brought them back. Custom
duckies sat in one settings row that any settings save holding an empty list deleted.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.store.repos import duckies as repo
from backend.store.repos import settings as settings_repo
from frontend import agent_profiles as ap
from frontend.agent_profiles import (
    bundled_profile_ids,
    delete_agent_profile,
    duplicate_agent_profile,
    get_agent_profile,
    list_agent_profiles,
    list_agent_profiles_available,
    list_archived_agent_profiles,
    save_agent_profile,
    save_agent_profile_override,
    unarchive_agent_profile,
)
from frontend.settings import PanelSettings

_DUCKY_APP = Path(__file__).resolve().parents[1]


def _ids(profiles) -> set[str]:
    return {p["id"] for p in profiles}


def _legacy_rows(**values) -> None:
    settings_repo.save_fields(values, PanelSettings().to_json_dict())


def test_a_fresh_install_lists_every_shipped_ducky() -> None:
    assert _ids(list_agent_profiles()) == bundled_profile_ids()
    assert len(bundled_profile_ids()) >= 13


def test_the_old_hide_list_is_ignored_and_the_settings_rows_stay_as_they_were() -> None:
    every = sorted(bundled_profile_ids())
    custom = {"id": "mine-1", "name": "My Ducky", "ducky_style": "artist"}
    _legacy_rows(
        hidden_bundled_agent_profile_ids=every,
        agent_profile_visibility_explicit=True,
        agent_profiles=[custom],
        agent_profile_overrides={"tester": {"name": "QA Duck"}},
        archived_agent_profile_ids=["reviewer"],
    )
    before = settings_repo.load_fields()

    visible = {p["id"]: p for p in list_agent_profiles()}
    assert set(visible) == (bundled_profile_ids() - {"reviewer"}) | {"mine-1"}
    assert visible["tester"]["name"] == "QA Duck"
    assert visible["mine-1"]["name"] == "My Ducky"
    assert _ids(list_archived_agent_profiles()) == {"reviewer"}
    assert settings_repo.load_fields() == before


def test_a_settings_save_cannot_touch_duckies() -> None:
    mine = save_agent_profile({"name": "Builder"})
    save_agent_profile_override("verse-coder", {"name": "Verse Pro"})
    s = PanelSettings.load()
    s.agent_profiles = []
    s.agent_profile_overrides = {}
    s.hidden_bundled_agent_profile_ids = sorted(bundled_profile_ids())
    s.agent_profile_visibility_explicit = True
    s.save()

    listed = {p["id"]: p for p in list_agent_profiles()}
    assert mine["id"] in listed
    assert listed["verse-coder"]["name"] == "Verse Pro"
    assert bundled_profile_ids() <= set(listed)


def test_removing_a_shipped_ducky_moves_it_to_archive_and_it_comes_back() -> None:
    delete_agent_profile("niagara-vfx")
    assert "niagara-vfx" not in _ids(list_agent_profiles())
    assert _ids(list_archived_agent_profiles()) == {"niagara-vfx"}
    unarchive_agent_profile("niagara-vfx")
    assert _ids(list_agent_profiles()) == bundled_profile_ids()


def test_removing_every_shipped_ducky_still_keeps_all_of_them() -> None:
    for pid in sorted(bundled_profile_ids()):
        delete_agent_profile(pid)
    assert _ids(list_archived_agent_profiles()) == bundled_profile_ids()
    assert _ids(list_agent_profiles_available()) == bundled_profile_ids()


def test_a_deleted_custom_ducky_keeps_its_row_and_every_earlier_copy() -> None:
    mine = save_agent_profile({"name": "Draft"})
    save_agent_profile({**mine, "name": "Final"})
    delete_agent_profile(mine["id"])

    assert mine["id"] not in _ids(list_agent_profiles_available())
    row = repo.get(mine["id"])
    assert row is not None and row["deleted"] > 0 and row["data"]["name"] == "Final"
    names = [h["data"].get("name") for h in repo.history(mine["id"])]
    assert names[:2] == ["Final", "Draft"]
    assert repo.set_deleted(mine["id"], False)
    assert mine["id"] in _ids(list_agent_profiles())


def test_editing_a_shipped_ducky_keeps_it_archived_and_duplicates_are_custom() -> None:
    delete_agent_profile("producer")
    save_agent_profile_override("producer", {"name": "Lead Producer"})
    assert _ids(list_archived_agent_profiles()) == {"producer"}
    copy = duplicate_agent_profile("producer")
    assert copy["kind"] == "custom" and copy["name"] == "Lead Producer Copy"
    assert copy["id"] in _ids(list_agent_profiles())


def test_the_import_runs_once_and_never_overwrites() -> None:
    _legacy_rows(agent_profiles=[{"id": "old-1", "name": "Old"}])
    assert "old-1" in _ids(list_agent_profiles())
    _legacy_rows(agent_profiles=[])
    save_agent_profile({"id": "old-1", "name": "Renamed"})
    assert {p["id"]: p["name"] for p in list_agent_profiles()}["old-1"] == "Renamed"


def test_the_library_is_never_empty_when_the_database_cannot_open(monkeypatch) -> None:
    def broken():
        raise OSError("database locked")

    monkeypatch.setattr(ap, "_repo", broken)
    assert _ids(list_agent_profiles()) == bundled_profile_ids()


def test_no_code_deletes_ducky_rows() -> None:
    offenders = []
    for path in _DUCKY_APP.rglob("*.py"):
        if "node_modules" in path.parts or path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"DELETE\s+FROM\s+duckies|DROP\s+TABLE\s+(IF\s+EXISTS\s+)?duckies", text, re.I):
            offenders.append(str(path.relative_to(_DUCKY_APP)))
    for path in (_DUCKY_APP / "backend" / "store" / "migrations").glob("*.sql"):
        if re.search(r"DELETE\s+FROM\s+duckies|DROP\s+TABLE\s+(IF\s+EXISTS\s+)?duckies", path.read_text(encoding="utf-8"), re.I):
            offenders.append(path.name)
    assert offenders == []


def test_deleting_from_archive_removes_a_shipped_ducky_for_good_but_keeps_its_row() -> None:
    delete_agent_profile("material-artist")  # first delete: Archive
    assert _ids(list_archived_agent_profiles()) == {"material-artist"}
    delete_agent_profile("material-artist")  # from Archive: permanent

    assert "material-artist" not in _ids(list_agent_profiles())
    assert "material-artist" not in _ids(list_archived_agent_profiles())
    assert "material-artist" not in _ids(list_agent_profiles_available())
    row = repo.get("material-artist")
    assert row is not None and row["deleted"] > 0
    # Chats that use it still resolve it, and the template stays available.
    assert get_agent_profile("material-artist")["name"]
    assert "material-artist" in {t["id"] for t in ap.list_bundled_agent_profile_templates()}


def test_one_delete_call_per_ducky_never_takes_shipped_duckies_away() -> None:
    # The Sep 30 wipe: one automated delete per shipped ducky, back to back.
    for pid in sorted(bundled_profile_ids()):
        delete_agent_profile(pid)
    assert _ids(list_archived_agent_profiles()) == bundled_profile_ids()
    for pid in sorted(bundled_profile_ids()):
        unarchive_agent_profile(pid)
    assert _ids(list_agent_profiles()) == bundled_profile_ids()


def test_a_deleted_custom_ducky_still_resolves_for_its_chats() -> None:
    mine = save_agent_profile({"name": "Helper"})
    delete_agent_profile(mine["id"])
    assert mine["id"] not in _ids(list_agent_profiles_available())
    assert get_agent_profile(mine["id"])["name"] == "Helper"
