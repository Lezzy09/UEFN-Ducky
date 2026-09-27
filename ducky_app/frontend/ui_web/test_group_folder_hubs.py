"""Group folders: legacy hubs migrate; deleting a group takes its whole subtree."""

from __future__ import annotations

import tempfile
from pathlib import Path

from frontend.archive_folder import ARCHIVE_FOLDER_ID
from frontend.settings import PanelSettings
from frontend.ui_web.project_chats import (
    create_conversation,
    create_folder,
    delete_folder,
    ensure_group_folder_hubs,
    list_conversations,
    load_conversation,
    load_folders,
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
        assert archived_member.parent_conv_id == ""
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
