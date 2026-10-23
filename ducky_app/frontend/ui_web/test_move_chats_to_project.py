"""Older per-project duckies, groups and folders move into the one Duckies list."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from frontend.ui_web import project_chats as pc


@pytest.fixture(params=["db", "files"])
def backend(request, monkeypatch) -> str:
    monkeypatch.setenv("DUCKY_STORE_BACKEND", request.param)
    pc._one_list_done.clear()
    return request.param


def _island(tmp_path: Path, name: str) -> str:
    root = tmp_path / name
    (root / "Content").mkdir(parents=True)
    return str(root)


def _to_project(slug: str, conv_ids=(), folder_ids=(), archived=()) -> None:
    """Put rows where an older Ducky kept them: in their project, not the one list."""
    if conv_ids or folder_ids:
        pc.move_chats_to_project(list(conv_ids), list(folder_ids), slug, "")
    for cid in archived:
        src = pc._conversation_disk_dir(pc.ONE_LIST_SLUG, cid)
        if src.exists():
            dest = pc._conversation_disk_dir(slug, cid)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        pc._commit_project_move(slug, [], [cid], lambda _cid: pc.ARCHIVE_FOLDER_ID)


def _select(root: str) -> None:
    settings = pc.PanelSettings.load()
    settings.uefn_project_root = root
    settings.save()


def test_new_duckies_go_in_the_one_list_whatever_project_is_named(backend: str, tmp_path: Path) -> None:
    island = _island(tmp_path, "Island")
    _select(island)
    conv = pc.create_conversation(title="Helper", project_root=island)
    folder = pc.create_folder("Team", project_root=island)
    assert pc.conversation_project_slug(conv.id) == pc.ONE_LIST_SLUG
    assert any(f.id == folder.id for f in pc.load_folders(""))
    assert [c.id for c in pc.list_conversations(None, "")] == [conv.id]


def test_every_projects_duckies_move_into_the_one_list(backend: str, tmp_path: Path) -> None:
    a, b = _island(tmp_path, "IslandA"), _island(tmp_path, "IslandB")
    a_slug, b_slug = pc.project_slug(a), pc.project_slug(b)
    kept = pc.create_conversation(title="Global")
    b1 = pc.create_conversation(title="B1")
    a1 = pc.create_conversation(title="A1")
    squad = pc.create_folder("Squad")
    hub = pc.create_conversation(title="Squad", folder_id=squad.id)
    hub.is_group = True
    pc.save_conversation(hub)
    rows = pc.load_folders()
    for row in rows:
        if row.id == squad.id:
            row.group_hub_id = hub.id
    pc.save_folders(rows)
    member = pc.create_conversation(title="Member", folder_id=squad.id)
    member.parent_conv_id = hub.id
    pc.save_conversation(member)
    old = pc.create_conversation(title="Old")
    shot = pc.get_conversations_dir(None, create=True) / member.id / "attachments" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"png")
    _to_project(a_slug, [a1.id], [squad.id], archived=[old.id])
    _to_project(b_slug, [b1.id])
    assert pc.conversation_project_slug(member.id) == a_slug
    assert (pc._conversation_disk_dir(a_slug, member.id) / "attachments" / "shot.png").is_file()
    _select(a)

    assert pc.merge_into_one_list() == 5

    for conv in (kept, a1, b1, hub, member, old):
        assert pc.conversation_project_slug(conv.id) == pc.ONE_LIST_SLUG
    moved = next(f for f in pc.load_folders("") if f.id == squad.id)
    assert moved.group_hub_id == hub.id and moved.parent_id == ""
    assert pc.load_conversation(member.id).folder_id == squad.id
    assert pc.load_conversation(old.id).folder_id == pc.ARCHIVE_FOLDER_ID
    assert (pc._conversation_disk_dir(pc.ONE_LIST_SLUG, member.id) / "attachments" / "shot.png").read_bytes() == b"png"
    # The list's own duckies first, then the open project's, then the others'.
    top = [c.title for c in pc.list_conversations("", "")]
    assert top == ["Global", "A1", "B1"]
    assert pc.merge_into_one_list() == 0


def test_a_project_that_cannot_move_stays_whole(backend: str, tmp_path: Path) -> None:
    a = _island(tmp_path, "IslandA")
    a_slug = pc.project_slug(a)
    folder = pc.create_folder("Squad")
    first = pc.create_conversation(title="One", folder_id=folder.id)
    second = pc.create_conversation(title="Two", folder_id=folder.id)
    for conv in (first, second):
        d = pc._conversation_disk_dir(pc.ONE_LIST_SLUG, conv.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "note.txt").write_text("x", encoding="utf-8")
    _to_project(a_slug, folder_ids=[folder.id])
    # Something already sits where the second chat's folder would go.
    pc._conversation_disk_dir(pc.ONE_LIST_SLUG, second.id).mkdir(parents=True, exist_ok=True)

    assert pc.merge_into_one_list() == 0

    assert pc.conversation_project_slug(first.id) == a_slug
    assert pc.conversation_project_slug(second.id) == a_slug
    assert (pc._conversation_disk_dir(a_slug, first.id) / "note.txt").is_file()
    assert any(f.id == folder.id for f in pc._load_folders_for_slug(a_slug))
