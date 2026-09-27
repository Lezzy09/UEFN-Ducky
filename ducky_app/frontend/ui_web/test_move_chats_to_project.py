"""Moving duckies and group folders between islands."""

from __future__ import annotations

from pathlib import Path

import pytest

from frontend.ui_web import project_chats as pc


@pytest.fixture(params=["db", "files"])
def backend(request, monkeypatch) -> str:
    monkeypatch.setenv("DUCKY_STORE_BACKEND", request.param)
    return request.param


def _island(tmp_path: Path, name: str) -> str:
    root = tmp_path / name
    (root / "Content").mkdir(parents=True)
    return str(root)


def test_move_one_chat_updates_project_folder_and_directory(backend: str, tmp_path: Path) -> None:
    src = _island(tmp_path, "Src")
    dest = _island(tmp_path, "Dest")
    dest_folder = pc.create_folder("Inbox", project_root=dest)
    conv = pc.create_conversation(title="Moved", project_root=src)
    shot = pc.get_conversations_dir(src, create=True) / conv.id / "attachments" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"png")

    pc.move_chats_to_project([conv.id], [], pc.project_slug(dest), dest_folder.id)

    assert pc.conversation_project_slug(conv.id) == pc.project_slug(dest)
    loaded = pc.load_conversation(conv.id, dest)
    assert loaded is not None and loaded.folder_id == dest_folder.id
    assert not shot.exists()
    moved = pc.get_conversations_dir(dest) / conv.id / "attachments" / "shot.png"
    assert moved.is_file() and moved.read_bytes() == b"png"
    assert pc.load_conversation(conv.id, src) is not None


def test_move_group_folder_moves_hub_member_and_attachment(backend: str, tmp_path: Path) -> None:
    src = _island(tmp_path, "Src")
    dest = _island(tmp_path, "Dest")
    folder = pc.create_folder("Squad", project_root=src)
    hub = pc.create_conversation(title="Squad", folder_id=folder.id, project_root=src)
    hub.is_group = True
    pc.save_conversation(hub, src)
    rows = pc.load_folders(src)
    for row in rows:
        if row.id == folder.id:
            row.group_hub_id = hub.id
    pc.save_folders(rows, src)
    member = pc.create_conversation(title="Member", folder_id=folder.id, project_root=src)
    member.parent_conv_id = hub.id
    pc.save_conversation(member, src)
    shot = pc.get_conversations_dir(src, create=True) / member.id / "attachments" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"png")

    pc.move_chats_to_project([], [folder.id], pc.project_slug(dest), "")

    dest_slug = pc.project_slug(dest)
    assert pc.conversation_project_slug(hub.id) == dest_slug
    assert pc.conversation_project_slug(member.id) == dest_slug
    moved_folder = next(row for row in pc.load_folders(dest) if row.id == folder.id)
    assert moved_folder.group_hub_id == hub.id
    assert moved_folder.parent_id == ""
    assert all(row.id != folder.id for row in pc.load_folders(src))
    assert (pc.get_conversations_dir(dest) / member.id / "attachments" / "shot.png").is_file()
    assert not shot.exists()


def test_failed_move_leaves_the_source_group_intact(backend: str, tmp_path: Path) -> None:
    src = _island(tmp_path, "Src")
    dest = _island(tmp_path, "Dest")
    folder = pc.create_folder("Squad", project_root=src)
    first = pc.create_conversation(title="One", folder_id=folder.id, project_root=src)
    second = pc.create_conversation(title="Two", folder_id=folder.id, project_root=src)
    src_dir = pc.get_conversations_dir(src, create=True)
    (src_dir / first.id).mkdir(parents=True, exist_ok=True)
    (src_dir / first.id / "conversation.json").write_text("{}", encoding="utf-8")
    (src_dir / second.id).mkdir(parents=True, exist_ok=True)
    blocking = pc.get_conversations_dir(dest, create=True) / second.id
    blocking.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="already exists"):
        pc.move_chats_to_project([], [folder.id], pc.project_slug(dest), "")

    src_slug = pc.project_slug(src)
    assert pc.conversation_project_slug(first.id) == src_slug
    assert pc.conversation_project_slug(second.id) == src_slug
    assert (src_dir / first.id).is_dir()
    assert not (pc.get_conversations_dir(dest) / first.id).exists()
    assert any(row.id == folder.id for row in pc.load_folders(src))
    assert all(row.id != folder.id for row in pc.load_folders(dest))
