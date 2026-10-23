"""Group folders: legacy hubs migrate; deleting a group takes its whole subtree."""

from __future__ import annotations

import tempfile
from pathlib import Path

from frontend.archive_folder import ARCHIVE_FOLDER_ID
from frontend.settings import PanelSettings
from frontend.ui_web.project_chats import (
    create_conversation,
    create_folder,
    delete_conversation,
    delete_folder,
    ensure_group_folder_hubs,
    list_conversations,
    load_conversation,
    load_folders,
    move_conversation,
    save_conversation,
    save_folders,
)


def test_ensure_group_folder_hubs_wraps_legacy_group():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        conv = create_conversation(settings, "", title="Squad", project_root=root)
        conv.is_group = True
        conv.group_members = []
        save_conversation(conv, root)

        assert ensure_group_folder_hubs(root) == 1
        folders = load_folders(root)
        hubs = [f for f in folders if (getattr(f, "group_hub_id", "") or "") == conv.id]
        assert len(hubs) == 1
        assert hubs[0].name == "Squad"
        fresh = load_conversation(conv.id, project_root=root)
        assert fresh is not None
        assert fresh.folder_id == hubs[0].id
        assert ensure_group_folder_hubs(root) == 0


def test_ensure_group_folder_hubs_leaves_archived_hubs_alone():
    """A deleted group's hub must not come back as a root folder on the next load."""
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        conv = create_conversation(settings, ARCHIVE_FOLDER_ID, title="Squad", project_root=root)
        conv.is_group = True
        conv.folder_id = ARCHIVE_FOLDER_ID
        save_conversation(conv, root)

        assert ensure_group_folder_hubs(root) == 0
        assert all((getattr(f, "group_hub_id", "") or "") != conv.id for f in load_folders(root))
        fresh = load_conversation(conv.id, project_root=root)
        assert fresh is not None
        assert fresh.folder_id == ARCHIVE_FOLDER_ID


def _make_group(settings, name: str, parent_id: str, root: str):
    folder = create_folder(name, parent_id, root)
    hub = create_conversation(settings, folder.id, title=name, project_root=root)
    hub.is_group = True
    hub.group_members = []
    save_conversation(hub, root)
    folders = load_folders(root)
    for f in folders:
        if f.id == folder.id:
            f.group_hub_id = hub.id
            break
    save_folders(folders, root)
    return folder, hub


def test_delete_group_keeps_duckies_and_archives_the_group():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        folder, hub = _make_group(settings, "Squad", "", root)
        member = create_conversation(
            settings,
            folder.id,
            title="Verse Coder",
            parent_conv_id=hub.id,
            project_root=root,
        )
        nested, nested_hub = _make_group(settings, "Inner", folder.id, root)

        assert delete_folder(folder.id, root) == [hub.id]

        archived_hub = load_conversation(hub.id, project_root=root)
        assert archived_hub is not None
        assert archived_hub.folder_id == ARCHIVE_FOLDER_ID
        assert archived_hub.is_group
        kept = load_conversation(member.id, project_root=root)
        assert kept is not None
        assert kept.folder_id == ""
        assert kept.parent_conv_id == ""
        folders = load_folders(root)
        assert all(f.id != folder.id for f in folders)
        moved = next(f for f in folders if f.id == nested.id)
        assert moved.parent_id == ""
        assert load_conversation(nested_hub.id, project_root=root) is not None
        assert ensure_group_folder_hubs(root) == 0


def test_delete_group_can_archive_duckies_too():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        folder, hub = _make_group(settings, "Squad", "", root)
        member = create_conversation(
            settings,
            folder.id,
            title="Verse Coder",
            parent_conv_id=hub.id,
            project_root=root,
        )

        assert delete_folder(folder.id, root, archive_members=True) == [hub.id]

        archived_hub = load_conversation(hub.id, project_root=root)
        assert archived_hub is not None
        assert archived_hub.folder_id == ARCHIVE_FOLDER_ID
        archived_member = load_conversation(member.id, project_root=root)
        assert archived_member is not None
        assert archived_member.folder_id == ARCHIVE_FOLDER_ID
        # Still the group's ducky in Archive, so it shows and comes back with the group.
        assert archived_member.parent_conv_id == hub.id
        assert all(f.id != folder.id for f in load_folders(root))


def test_delete_group_and_duckies_archives_nested_groups():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        outer, outer_hub = _make_group(settings, "Outer", "", root)
        _inner, inner_hub = _make_group(settings, "Inner", outer.id, root)

        assert delete_folder(outer.id, root, archive_members=True) == sorted(
            [outer_hub.id, inner_hub.id]
        )

        assert all(f.id not in {outer.id, _inner.id} for f in load_folders(root))
        for hub_id in (outer_hub.id, inner_hub.id):
            archived = load_conversation(hub_id, project_root=root)
            assert archived is not None
            assert archived.folder_id == ARCHIVE_FOLDER_ID
        # The nested group points at the group around it.
        assert load_conversation(inner_hub.id, project_root=root).parent_conv_id == outer_hub.id
        assert load_conversation(outer_hub.id, project_root=root).parent_conv_id == ""
        assert ensure_group_folder_hubs(root) == 0


def test_delete_plain_folder_still_moves_chats_to_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        folder = create_folder("Notes", "", root)
        chat = create_conversation(settings, folder.id, title="Scratch", project_root=root)

        assert delete_folder(folder.id, root) == []

        moved = load_conversation(chat.id, project_root=root)
        assert moved is not None
        assert moved.folder_id == ""


def _archived_squad(settings, root: str):
    outer, outer_hub = _make_group(settings, "Squad", "", root)
    member = create_conversation(settings, outer.id, title="Builder", parent_conv_id=outer_hub.id, project_root=root)
    loose = create_conversation(settings, outer.id, title="Loose", project_root=root)
    inner, inner_hub = _make_group(settings, "Inner", outer.id, root)
    inner_member = create_conversation(settings, inner.id, title="Verifier", parent_conv_id=inner_hub.id, project_root=root)
    delete_folder(outer.id, root, archive_members=True)
    return outer_hub, member, loose, inner_hub, inner_member


def test_a_ducky_in_the_group_folder_belongs_to_the_group_in_archive():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        outer_hub, _member, loose, _inner_hub, _inner_member = _archived_squad(PanelSettings.load(), root)
        assert load_conversation(loose.id, project_root=root).parent_conv_id == outer_hub.id


def test_return_to_active_brings_the_whole_group_back():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        outer_hub, member, loose, inner_hub, inner_member = _archived_squad(PanelSettings.load(), root)

        move_conversation(outer_hub.id, "", root)

        folders = {f.id: f for f in load_folders(root)}
        outer_folder = next(f for f in folders.values() if f.group_hub_id == outer_hub.id)
        inner_folder = next(f for f in folders.values() if f.group_hub_id == inner_hub.id)
        assert outer_folder.parent_id == "" and inner_folder.parent_id == outer_folder.id
        for conv_id, folder_id, parent in (
            (outer_hub.id, outer_folder.id, ""),
            (member.id, outer_folder.id, outer_hub.id),
            (loose.id, outer_folder.id, outer_hub.id),
            (inner_hub.id, inner_folder.id, ""),
            (inner_member.id, inner_folder.id, inner_hub.id),
        ):
            conv = load_conversation(conv_id, project_root=root)
            assert (conv.folder_id, conv.parent_conv_id) == (folder_id, parent)
        assert ensure_group_folder_hubs(root) == 0


def test_one_ducky_out_of_an_archived_group_comes_back_on_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        outer_hub, member, _loose, _inner_hub, _inner_member = _archived_squad(PanelSettings.load(), root)

        move_conversation(member.id, "", root)

        back = load_conversation(member.id, project_root=root)
        assert (back.folder_id, back.parent_conv_id) == ("", "")
        assert load_conversation(outer_hub.id, project_root=root).folder_id == ARCHIVE_FOLDER_ID


def test_deleting_an_archived_group_for_good_takes_everything_in_it():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        outer_hub, member, loose, inner_hub, inner_member = _archived_squad(PanelSettings.load(), root)

        delete_conversation(outer_hub.id, root)

        for conv_id in (outer_hub.id, member.id, loose.id, inner_hub.id, inner_member.id):
            assert load_conversation(conv_id, project_root=root) is None


def test_archiving_a_group_chat_archives_its_folder_and_everything_in_it():
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp))
        settings = PanelSettings.load()
        folder, hub = _make_group(settings, "Squad", "", root)
        member = create_conversation(settings, folder.id, title="Builder", parent_conv_id=hub.id, project_root=root)

        move_conversation(hub.id, ARCHIVE_FOLDER_ID, root)

        assert all(f.id != folder.id for f in load_folders(root))
        for conv_id in (hub.id, member.id):
            assert load_conversation(conv_id, project_root=root).folder_id == ARCHIVE_FOLDER_ID


def test_a_lead_stays_on_top_of_its_own_group_when_it_leads_a_subgroup():
    from types import SimpleNamespace as NS

    from frontend.ui_web.group_orchestrator import stays_with_outer_group

    folders = [
        NS(id="main", parent_id="", group_hub_id="hub-main"),
        NS(id="qa", parent_id="main", group_hub_id="hub-qa"),
        NS(id="plain", parent_id="", group_hub_id=""),
    ]
    lead = NS(id="lead", folder_id="main")
    by_id = {"hub-main": NS(id="hub-main", leader_conv_id="lead"), "hub-qa": NS(id="hub-qa", leader_conv_id="lead")}
    assert stays_with_outer_group(lead, "qa", folders, by_id)
    # Not the outer group's lead, filed in a plain folder, or the subgroup is not nested: it moves.
    assert not stays_with_outer_group(NS(id="other", folder_id="main"), "qa", folders, by_id)
    assert not stays_with_outer_group(NS(id="lead", folder_id="plain"), "qa", folders, by_id)
    assert not stays_with_outer_group(NS(id="lead", folder_id="qa"), "main", folders, by_id)


def test_a_group_made_inside_another_sits_in_it_and_is_deleted_with_it(monkeypatch, tmp_path):
    # Oct 15 2026: a lead made its team's groups with ducky_group_create(parent_folder_id=...);
    # the nested hubs had no parent_conv_id, so deleting the team kept them and their members.
    import frontend.ui_web.panel_api as pa
    from frontend.ui_web.panel_api_chats import PanelApiChatsMixin

    settings = PanelSettings.load()
    settings.uefn_project_root = str(tmp_path)
    monkeypatch.setattr(pa.PanelSettings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(pa, "notify_chats_changed", lambda *a, **k: None)
    api = PanelApiChatsMixin()
    outer = api.group_create("Ledger Team", "", False)
    inner = api.group_create("Core", outer["folder_id"], False)
    member = create_conversation(settings, inner["folder_id"], title="Builder", parent_conv_id=inner["id"],
                                 project_root=str(tmp_path))
    assert load_conversation(inner["id"], project_root=str(tmp_path)).parent_conv_id == outer["id"]
    assert load_conversation(outer["id"], project_root=str(tmp_path)).parent_conv_id == ""

    api.delete_conversation(outer["id"])
    for cid in (outer["id"], inner["id"], member.id):
        assert load_conversation(cid, project_root=str(tmp_path)) is None, cid


def test_a_lead_added_to_a_new_group_stays_in_its_old_group(monkeypatch, tmp_path):
    # Oct 22 2026: as_leader moved the lead into the new group's folder, leaving its old group empty.
    import frontend.ui_web.panel_api as pa
    from frontend.ui_web.panel_api_chats import PanelApiChatsMixin

    root = str(tmp_path)
    settings = PanelSettings.load()
    settings.uefn_project_root = root
    monkeypatch.setattr(pa.PanelSettings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(pa, "notify_chats_changed", lambda *a, **k: None)
    api = PanelApiChatsMixin()
    old = api.group_create("Old Team", "", False)
    new = api.group_create("New Team", "", False)
    lead = create_conversation(settings, old["folder_id"], title="Lead", parent_conv_id=old["id"], project_root=root)

    out = api.group_add_member(new["id"], lead.id, as_leader=True)

    assert out["ok"] and out["leader_conv_id"] == lead.id
    assert lead.id in [m["member_conv_id"] for m in out["group_members"]]
    fresh = load_conversation(lead.id, project_root=root)
    assert fresh.folder_id == old["folder_id"] and fresh.parent_conv_id == old["id"]
