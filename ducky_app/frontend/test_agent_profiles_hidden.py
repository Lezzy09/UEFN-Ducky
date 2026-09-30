"""Empty hide-list is 'show all' — never expand it to every bundled id."""

from __future__ import annotations

from frontend.agent_profiles import (
    _heal_hidden_if_poisoned,
    _is_empty_or_poison,
    _stored_hidden_list,
    archive_agent_profile,
    bundled_profile_ids,
    delete_agent_profile,
    list_agent_profiles,
    list_archived_agent_profiles,
    save_agent_profile,
    save_agent_profile_override,
    unarchive_agent_profile,
)
from frontend.settings import PanelSettings


def test_empty_hidden_list_stays_empty() -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=[])
    assert _stored_hidden_list(s) == []


def test_unset_hide_list_shows_every_builtin() -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=None)
    assert _stored_hidden_list(s) == []


def test_poison_matches_save_one_then_hide_siblings() -> None:
    bundled = bundled_profile_ids()
    hidden = bundled - {"niagara-vfx"}
    assert _is_empty_or_poison(hidden, frozenset({"niagara-vfx"}), bundled)
    assert not _is_empty_or_poison(frozenset({"verse-coder"}), frozenset(), bundled)


def test_heal_restores_library_without_writing() -> None:
    bundled = bundled_profile_ids()
    s = PanelSettings(
        hidden_bundled_agent_profile_ids=sorted(bundled - {"niagara-vfx"}),
        agent_profile_overrides={"niagara-vfx": {"name": "Niagara VFX"}},
    )
    _heal_hidden_if_poisoned(s, persist=False)
    assert s.hidden_bundled_agent_profile_ids == []
    ids = {p["id"] for p in list_agent_profiles(s)}
    assert bundled <= ids


def test_saving_one_bundled_does_not_hide_the_rest(monkeypatch) -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=[], agent_profile_overrides={})
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    save_agent_profile_override("niagara-vfx", {"name": "Niagara VFX"})
    assert s.hidden_bundled_agent_profile_ids == []
    ids = {p["id"] for p in list_agent_profiles(s)}
    assert "niagara-vfx" in ids
    assert "verse-coder" in ids
    assert "level-designer" in ids


def test_deleting_one_bundled_hides_only_that_one(monkeypatch) -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=[], agent_profile_overrides={})
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    delete_agent_profile("verse-coder")
    assert s.hidden_bundled_agent_profile_ids == ["verse-coder"]
    ids = {p["id"] for p in list_agent_profiles(s)}
    assert "verse-coder" not in ids
    assert "niagara-vfx" in ids
    assert "level-designer" in ids


def test_hiding_one_sticks_and_hiding_every_template_stays_hidden(monkeypatch) -> None:
    """A partial removal stays removed. Deleting the last built-in stays deleted too."""
    stored = PanelSettings(hidden_bundled_agent_profile_ids=[]).to_json_dict()
    bundled = sorted(bundled_profile_ids())

    def save(settings):
        stored.clear()
        stored.update(settings.to_json_dict())

    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: cls._finish_load(stored)))
    monkeypatch.setattr(PanelSettings, "save", save)
    removed = set()
    for pid in bundled:
        delete_agent_profile(pid)
        removed.add(pid)
        visible = {profile["id"] for profile in list_agent_profiles()}
        assert not removed & visible
    assert not bundled_profile_ids() & {profile["id"] for profile in list_agent_profiles()}


def test_deleting_siblings_of_renamed_profile_stays_deleted(monkeypatch) -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=[])
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    save_agent_profile_override("niagara-vfx", {"name": "My VFX"})
    for pid in bundled_profile_ids() - {"niagara-vfx"}:
        delete_agent_profile(pid)
    profiles = list_agent_profiles(s)
    assert [(p["id"], p["name"]) for p in profiles] == [("niagara-vfx", "My VFX")]


def test_explicit_hide_all_stays_hidden_except_the_profile_just_saved(monkeypatch) -> None:
    wiped = PanelSettings(
        hidden_bundled_agent_profile_ids=sorted(bundled_profile_ids()),
        agent_profile_visibility_explicit=True,
    )
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: wiped))
    monkeypatch.setattr(wiped, "save", lambda: None)
    save_agent_profile_override("verse-coder", {"name": "My Coder"})
    names = {p["id"]: p["name"] for p in list_agent_profiles(wiped)}
    assert names == {"verse-coder": "My Coder"}

    partial = PanelSettings(
        hidden_bundled_agent_profile_ids=["verse-coder", "tester"],
        agent_profile_visibility_explicit=True,
    )
    assert {p["id"] for p in list_agent_profiles(partial)} == bundled_profile_ids() - {"verse-coder", "tester"}


def test_deleting_from_legacy_poisoned_library_repairs_then_removes(monkeypatch) -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=sorted(bundled_profile_ids()))
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    delete_agent_profile("verse-coder")
    assert {p["id"] for p in list_agent_profiles(s)} == bundled_profile_ids() - {"verse-coder"}


def test_archive_restore_and_permanent_delete(monkeypatch) -> None:
    s = PanelSettings(hidden_bundled_agent_profile_ids=[], archived_agent_profile_ids=[])
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    archive_agent_profile("verse-coder")
    assert "verse-coder" not in {p["id"] for p in list_agent_profiles(s)}
    assert "verse-coder" in {p["id"] for p in list_archived_agent_profiles(s)}
    unarchive_agent_profile("verse-coder")
    assert "verse-coder" in {p["id"] for p in list_agent_profiles(s)}
    assert list_archived_agent_profiles(s) == []
    archive_agent_profile("verse-coder")
    delete_agent_profile("verse-coder")
    assert "verse-coder" not in {p["id"] for p in list_agent_profiles(s)}
    assert "verse-coder" not in {p["id"] for p in list_archived_agent_profiles(s)}
    assert "verse-coder" in (s.hidden_bundled_agent_profile_ids or [])
    custom = save_agent_profile({"id": "my-agent", "name": "My Agent", "ducky_personality": "Be helpful"})
    archive_agent_profile(custom["id"])
    assert custom["id"] not in {p["id"] for p in list_agent_profiles(s)}
    delete_agent_profile(custom["id"])
    assert custom["id"] not in {p["id"] for p in list_archived_agent_profiles(s)}
    assert custom["id"] not in {p["id"] for p in list_agent_profiles(s)}


def test_rename_and_delete_custom_profile_preserve_other_agents(monkeypatch) -> None:
    from frontend.agent_profiles import save_agent_profile

    s = PanelSettings(hidden_bundled_agent_profile_ids=[])
    monkeypatch.setattr(PanelSettings, "load", classmethod(lambda cls: s))
    monkeypatch.setattr(s, "save", lambda: None)
    profile = save_agent_profile({"id": "my-agent", "name": "My Agent", "ducky_personality": "Be helpful"})
    renamed = save_agent_profile({**profile, "name": "My Helper"})
    assert renamed["id"] == profile["id"]
    assert renamed["ducky_personality"] == profile["ducky_personality"]
    assert "My Helper" in {p["name"] for p in list_agent_profiles(s)}
    delete_agent_profile(profile["id"])
    assert {p["id"] for p in list_agent_profiles(s)} == bundled_profile_ids()
