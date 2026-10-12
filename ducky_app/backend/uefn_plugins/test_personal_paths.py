"""Personal paths never ship in a plugin; drafts can move and delete files."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.uefn_plugins.personal_paths import find_personal_paths, personal_paths_in


@pytest.mark.parametrize("text,found", [
    ("C:/Users/sam/AppData/x", ["C:/Users/sam"]),
    (r"C:\Users\sam\x", [r"C:\Users\sam"]),
    (r'"C:\\Users\\alex\\x"', [r"C:\\Users\\alex"]),
    ("/home/bob/x and /Users/alice/Library", ["/home/bob", "/Users/alice"]),
    ("C:/Users/<name>/x C:/Users/Public/x %USERPROFILE% C:/Users/%USERNAME%/x", []),
    ("https://example.com/users/123", []),
])
def test_personal_paths_are_found_and_placeholders_are_not(text, found):
    assert personal_paths_in(text) == found


def test_only_shipped_text_files_outside_vendor_folders_are_checked(tmp_path: Path):
    (tmp_path / "ui" / "vendor").mkdir(parents=True)
    (tmp_path / "ui" / "check.py").write_text("ROOT = 'C:/Users/sam/plugin'\n", encoding="utf-8")
    (tmp_path / "ui" / "vendor" / "lib.js").write_text("FS.mkdir('/home/web_user')\n", encoding="utf-8")
    (tmp_path / "ui" / "pic.png").write_bytes(b"C:/Users/sam")
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert find_personal_paths(tmp_path, files) == [{"path": "ui/check.py", "line": 1, "found": "C:/Users/sam"}]


def test_the_build_leaves_tests_behind_and_names_personal_paths(tmp_path: Path):
    from backend.uefn_plugins.compile import shipped_personal_paths

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "evidence.json").write_text('{"p": "C:/Users/sam/x"}', encoding="utf-8")
    assert shipped_personal_paths(tmp_path) == []
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "coverage.json").write_text('{\n"p": "C:/Users/sam/x"}', encoding="utf-8")
    assert [f["path"] for f in shipped_personal_paths(tmp_path)] == ["assets/coverage.json"]


@pytest.fixture()
def draft(tmp_path, monkeypatch):
    from backend.tools.panel import panel_ai_plugins as pap

    root = tmp_path / "demo"
    (root / "backend" / "render" / "evidence").mkdir(parents=True)
    (root / "plugin.json").write_text('{"id": "demo"}', encoding="utf-8")
    (root / "backend" / "render" / "evidence" / "a.json").write_text("{}", encoding="utf-8")
    (root / "backend" / "render" / "check_x.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(pap, "_draft_root", lambda pid: root)
    return pap, root


def test_a_draft_moves_development_files_under_tests(draft):
    pap, root = draft
    moved = pap.move_ai_plugin_file("demo", "backend/render/evidence", "tests/evidence/render")
    assert moved["ok"] and moved["to"] == "tests/evidence/render"
    assert (root / "tests" / "evidence" / "render" / "a.json").is_file()
    assert not (root / "backend" / "render" / "evidence").exists()
    assert not pap.move_ai_plugin_file("demo", "backend/render/check_x.py", "plugin.json")["ok"]
    assert not pap.move_ai_plugin_file("demo", "backend/render/check_x.py", "../outside.py")["ok"]
    assert not pap.move_ai_plugin_file("demo", "tests", "tests/inner")["ok"]


def test_a_draft_deletes_files_and_folders_only_when_asked(draft):
    pap, root = draft
    assert pap.delete_ai_plugin_file("demo", "backend/render/check_x.py")["files"] == 1
    refused = pap.delete_ai_plugin_file("demo", "backend/render/evidence")
    assert not refused["ok"] and "recursive=true" in refused["error"]
    assert pap.delete_ai_plugin_file("demo", "backend/render/evidence", recursive=True)["files"] == 1
    assert not pap.delete_ai_plugin_file("demo", "plugin.json")["ok"]
    assert not pap.delete_ai_plugin_file("demo", ".")["ok"]
    assert (root / "plugin.json").is_file()
