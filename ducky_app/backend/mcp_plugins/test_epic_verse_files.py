""".verse deletes and moves go through Epic's VerseToolset while UEFN has the island open.

The fake toolset changes the disk the way UEFN does, so these tests check what ends up
where: the undo trash, the destination, the calls Epic got, and the Lore drop.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import frontend.ui_web.project_files as pf
from backend.mcp_plugins import epic_verse_files as evf
from backend.workspace import runtime
from backend.workspace.writer import ProjectWriter
from frontend import project_kind as pk


class _Journal:
    def record(self, record):
        return {"run_id": "r", "seq": 1}

    def note_read(self, path: str, content_hash: str, project_root: str = "") -> None:
        pass


class FakeVerseToolset:
    """Epic's VerseToolset over a Content folder: Delete / Move change the disk."""

    def __init__(self, content: Path, package: str = "/Isle") -> None:
        self.content = content
        self.package = package
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def __call__(self, tool: str, arguments: dict, timeout: float) -> str:
        self.calls.append((tool, dict(arguments)))
        if tool == "ListFiles":
            rows = [{"name": self.package, "type": "Directory"}, {"name": "/Verse.org (Verse)", "type": "Directory"}]
            return json.dumps({"returnValue": rows}) + "\n\n[Ducky: pressed nothing]"
        if self.fail:
            raise RuntimeError("Nested MCP 'unreal-mcp' tool 'call_tool' timed out")
        if tool == "Delete":
            path = self._disk(arguments["path"])
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        elif tool == "Move":
            self._disk(arguments["sourcePath"]).rename(self._disk(arguments["destPath"]))
        return json.dumps({"returnValue": None})

    def changes(self) -> list[tuple[str, dict]]:
        return [c for c in self.calls if c[0] != "ListFiles"]

    def _disk(self, verse_path: str) -> Path:
        assert verse_path.startswith(self.package + "/")
        return self.content / verse_path[len(self.package) + 1:]


@pytest.fixture
def island(tmp_path: Path, monkeypatch):
    root = tmp_path / "Isle"
    probe = root / "Content" / "Verse" / "Probe"
    (probe / "Sub").mkdir(parents=True)
    (root / "Content" / "Verse" / "Other").mkdir()
    (root / "Isle.uefnproject").write_text("{}", encoding="utf-8")
    (probe / "a.verse").write_text("# a\n", encoding="utf-8")
    (probe / "Sub" / "b.verse").write_text("# b\n", encoding="utf-8")
    (root / "Content" / "notes.md").write_text("# notes\n", encoding="utf-8")
    pk.forget_cached_kind()
    runtime.reset_for_tests(ProjectWriter.for_root(str(root), journal=_Journal()))
    monkeypatch.setattr(pf, "_project_root", lambda: root)
    epic = FakeVerseToolset(root / "Content")
    monkeypatch.setattr(evf, "_call", epic)
    status = {"epic_mcp_online": True}
    monkeypatch.setattr("backend.mcp_plugins.epic.probe_epic_mcp", lambda **_kw: dict(status))
    lore: list[list[str]] = []
    monkeypatch.setattr("frontend.ui_web.verse_editor.urc.lore_host.has_lore", lambda _root: True)
    monkeypatch.setattr(
        "frontend.ui_web.verse_editor.urc.lore_host.drop_missing_orphans",
        lambda _root, prefixes=None: lore.append(list(prefixes or [])) or {"ok": True, "dropped": []},
    )
    yield SimpleNamespace(root=root, content=root / "Content", probe=probe, epic=epic, status=status, lore=lore)
    runtime.reset_for_tests(None)
    pk.forget_cached_kind()


def _files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _spy_moves(monkeypatch) -> list[str]:
    moved: list[str] = []
    real = shutil.move

    def spy(src, dst, *args, **kwargs):
        moved.append(Path(src).name)
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(pf.shutil, "move", spy)
    return moved


# ---------------------------------------------------------------- delete


def test_online_delete_goes_through_the_toolset_and_keeps_an_undo_copy(island) -> None:
    out = pf.delete_project_entry("Content/Verse/Probe")
    assert out["via"] == "uefn"
    assert island.epic.changes() == [("Delete", {"path": "/Isle/Verse/Probe", "bRecursive": True})]
    assert not island.probe.exists()
    trashed = island.root / ".undo-trash" / out["trash_token"] / "Probe"
    assert _files(trashed) == ["Sub/b.verse", "a.verse"]
    assert island.lore == [["Content/Verse/Probe"]]

    pf.restore_trashed_entry(out["trash_token"])
    assert _files(island.probe) == ["Sub/b.verse", "a.verse"]


def test_online_delete_of_one_file(island) -> None:
    out = pf.delete_project_entry("Content/Verse/Probe/a.verse")
    assert out["via"] == "uefn"
    assert island.epic.changes() == [("Delete", {"path": "/Isle/Verse/Probe/a.verse", "bRecursive": False})]
    assert _files(island.probe) == ["Sub/b.verse"]


def test_toolset_failure_still_deletes_file_by_file_and_keeps_the_copy(island, monkeypatch) -> None:
    island.epic.fail = True
    out = pf.delete_project_entry("Content/Verse/Probe")
    assert out["via"] == "disk"
    assert not island.probe.exists()
    assert _files(island.root / ".undo-trash" / out["trash_token"] / "Probe") == ["Sub/b.verse", "a.verse"]


def test_offline_delete_moves_the_folder_to_the_trash_file_by_file(island, monkeypatch) -> None:
    island.status["epic_mcp_online"] = False
    moved = _spy_moves(monkeypatch)
    out = pf.delete_project_entry("Content/Verse/Probe")
    assert out["via"] == "disk"
    assert island.epic.calls == []
    # One move per file: a folder moved in one step leaves its files on UEFN's build list.
    assert sorted(moved) == ["a.verse", "b.verse"]
    assert not island.probe.exists()
    assert _files(island.root / ".undo-trash" / out["trash_token"] / "Probe") == ["Sub/b.verse", "a.verse"]
    pf.restore_trashed_entry(out["trash_token"])
    assert _files(island.probe) == ["Sub/b.verse", "a.verse"]


def test_a_folder_the_toolset_refuses_is_a_disk_delete(island, monkeypatch) -> None:
    (island.probe / "readme.md").write_text("x\n", encoding="utf-8")  # Delete takes .verse-only trees
    moved = _spy_moves(monkeypatch)
    out = pf.delete_project_entry("Content/Verse/Probe")
    assert out["via"] == "disk"
    assert island.epic.calls == []
    assert sorted(moved) == ["a.verse", "b.verse", "readme.md"]


def test_another_island_open_in_uefn_is_a_disk_delete(island) -> None:
    island.epic.package = "/SomeOtherIsland"
    out = pf.delete_project_entry("Content/Verse/Probe")
    assert out["via"] == "disk"
    assert island.epic.changes() == []
    assert not island.probe.exists()


def test_non_verse_entries_are_unchanged(island, monkeypatch) -> None:
    moved = _spy_moves(monkeypatch)
    out = pf.delete_project_entry("Content/notes.md")
    assert "via" not in out
    assert moved == ["notes.md"]
    assert island.epic.calls == [] and island.lore == []


# ---------------------------------------------------------------- move / rename


def test_online_move_goes_through_the_toolset(island) -> None:
    out = pf.move_project_entry("Content/Verse/Probe", "Content/Verse/Other")
    assert out == {"path": "Content/Verse/Other/Probe", "via": "uefn"}
    assert island.epic.changes() == [
        ("Move", {"sourcePath": "/Isle/Verse/Probe", "destPath": "/Isle/Verse/Other/Probe"})
    ]
    assert _files(island.content / "Verse" / "Other" / "Probe") == ["Sub/b.verse", "a.verse"]
    assert island.lore == [["Content/Verse/Probe"]]


def test_offline_move_goes_file_by_file(island, monkeypatch) -> None:
    island.status["epic_mcp_online"] = False
    moved = _spy_moves(monkeypatch)
    out = pf.move_project_entry("Content/Verse/Probe", "Content/Verse/Other")
    assert out == {"path": "Content/Verse/Other/Probe", "via": "disk"}
    assert sorted(moved) == ["a.verse", "b.verse"]
    assert not island.probe.exists()
    assert _files(island.content / "Verse" / "Other" / "Probe") == ["Sub/b.verse", "a.verse"]


def test_online_rename_of_a_verse_file_and_folder(island) -> None:
    assert pf.rename_project_entry("Content/Verse/Probe/a.verse", "c.verse")["via"] == "uefn"
    assert pf.rename_project_entry("Content/Verse/Probe", "Renamed")["via"] == "uefn"
    assert island.epic.changes() == [
        ("Move", {"sourcePath": "/Isle/Verse/Probe/a.verse", "destPath": "/Isle/Verse/Probe/c.verse"}),
        ("Move", {"sourcePath": "/Isle/Verse/Probe", "destPath": "/Isle/Verse/Renamed"}),
    ]
    assert _files(island.content / "Verse" / "Renamed") == ["Sub/b.verse", "c.verse"]


def test_renaming_verse_to_another_type_is_a_disk_rename(island) -> None:
    out = pf.rename_project_entry("Content/Verse/Probe/a.verse", "a.txt")
    assert out == {"path": "Content/Verse/Probe/a.txt", "via": "disk"}
    assert island.epic.calls == []
    assert (island.probe / "a.txt").is_file()


def test_toolset_move_failure_falls_back_to_the_disk(island) -> None:
    island.epic.fail = True
    out = pf.rename_project_entry("Content/Verse/Probe", "Renamed")
    assert out["via"] == "disk"
    assert _files(island.content / "Verse" / "Renamed") == ["Sub/b.verse", "a.verse"]


# ---------------------------------------------------------------- the helper itself


def test_island_package_needs_epic_online_and_this_island(island) -> None:
    assert evf.island_package(island.root) == "/Isle"
    island.status["epic_mcp_online"] = False
    assert evf.island_package(island.root) == ""
    island.status["epic_mcp_online"] = True
    island.epic.package = "/Elsewhere"
    assert evf.island_package(island.root) == ""


def test_island_package_is_empty_for_a_folder_project_or_a_dead_session(island, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "repo"
    (folder / "Content").mkdir(parents=True)
    assert evf.island_package(folder) == ""
    assert island.epic.calls == []

    def dead(*_a, **_k):
        raise RuntimeError("session unavailable")

    monkeypatch.setattr(evf, "_call", dead)
    assert evf.island_package(island.root) == ""


def test_verse_paths_are_content_relative_under_the_package(island) -> None:
    assert evf.verse_path("/Isle", island.root, island.probe / "Sub" / "b.verse") == "/Isle/Verse/Probe/Sub/b.verse"


def test_a_half_finished_toolset_move_is_reported(island, monkeypatch) -> None:
    def half(tool, arguments, timeout):
        if tool == "ListFiles":
            return json.dumps({"returnValue": [{"name": "/Isle", "type": "Directory"}]})
        (island.content / "Verse" / "Renamed").mkdir()
        return "{}"

    monkeypatch.setattr(evf, "_call", half)
    with pytest.raises(ValueError, match="partway"):
        evf.move(island.root, island.probe, island.content / "Verse" / "Renamed")
