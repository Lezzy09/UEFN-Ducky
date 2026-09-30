"""Opening another project's chat must not steal it onto the active island."""

from __future__ import annotations

import tempfile
from pathlib import Path

from frontend.settings import PanelSettings
from frontend.ui_web.project_chats import (
    _use_db,
    adopt_group_project,
    conversation_path,
    create_conversation,
    load_conversation,
    project_slug,
    save_conversation,
)


def test_load_and_save_keep_home_project():
    with tempfile.TemporaryDirectory() as tmp:
        home = str(Path(tmp) / "HomeIsland")
        other = str(Path(tmp) / "OtherIsland")
        Path(home).mkdir()
        Path(other).mkdir()
        conv = create_conversation(PanelSettings.load(), "", title="Away", project_root=home)
        conv.messages = [{"role": "user", "text": "hi", "content": "hi", "ts": 1}]
        save_conversation(conv, home)

        loaded = load_conversation(conv.id, project_root=other)
        assert loaded is not None
        assert loaded.title == "Away"
        loaded.title = "Still away"
        save_conversation(loaded, other)

        home_again = load_conversation(conv.id, project_root=home)
        assert home_again is not None
        assert home_again.title == "Still away"
        if _use_db():
            from frontend.ui_web.project_chats import _repo

            assert _repo().conv_project_id(conv.id) == project_slug(home)
        else:
            assert conversation_path(conv.id, home).is_file()
            assert not conversation_path(conv.id, other).is_file()


def test_adopt_group_project_moves_member_onto_the_group_island():
    if not _use_db():
        return
    with tempfile.TemporaryDirectory() as tmp:
        home = str(Path(tmp) / "HomeIsland")
        other = str(Path(tmp) / "OtherIsland")
        Path(home).mkdir()
        Path(other).mkdir()
        group = create_conversation(PanelSettings.load(), "", title="Group", project_root=home)
        group.is_group = True
        save_conversation(group, home)
        member = create_conversation(PanelSettings.load(), "", title="Coder", project_root=other)
        adopt_group_project(member, group.id)
        from frontend.ui_web.project_chats import _repo

        assert _repo().conv_project_id(member.id) == project_slug(home)


def test_sync_rehomes_a_member_invited_from_another_island():
    if not _use_db():
        return
    from frontend.ui_web.group_orchestrator import sync_group_members_from_folder
    from frontend.ui_web.project_chats import _repo, create_folder, load_folders, save_folders

    with tempfile.TemporaryDirectory() as tmp:
        home = str(Path(tmp) / "HomeIsland")
        other = str(Path(tmp) / "OtherIsland")
        Path(home).mkdir()
        Path(other).mkdir()
        group = create_conversation(PanelSettings.load(), "", title="Group", project_root=home)
        group.is_group = True
        folder = create_folder("Group1", project_root=home)
        folders = load_folders(home)
        for item in folders:
            if item.id == folder.id:
                item.group_hub_id = group.id
        save_folders(folders, home)
        group.folder_id = folder.id
        member = create_conversation(PanelSettings.load(), "", title="Coder", project_root=other)
        member.folder_id = folder.id
        member.parent_conv_id = group.id
        save_conversation(member, other)
        group.group_members = [{"member_conv_id": member.id, "name": "Coder"}]
        save_conversation(group, home)

        rows = sync_group_members_from_folder(group)

        assert any(row.get("member_conv_id") == member.id for row in rows)
        assert _repo().conv_project_id(member.id) == project_slug(home)
