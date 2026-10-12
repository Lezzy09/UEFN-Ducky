"""Plugin draft files are read in parts and edited in place, not moved whole through context."""

from __future__ import annotations

import pytest

from backend.tools.panel import panel_ai_plugins as p


@pytest.fixture
def draft(tmp_path, monkeypatch):
    root = tmp_path / "imk"
    (root / "ui").mkdir(parents=True)
    monkeypatch.setattr(p, "_draft_root", lambda pid: root)
    return root


def test_a_big_file_comes_back_as_an_outline_and_its_first_lines(draft) -> None:
    # Oct 12 2026: a team read 4.7 MB of plugin files in 50 minutes, logic.js six times.
    body = ["// logic"] + [f"export function step{n}(a) {{ return a + {n}; }}" + " " * 400 for n in range(400)]
    (draft / "ui" / "logic.js").write_text("\n".join(body), encoding="utf-8")
    out = p.read_ai_plugin_file("imk", "ui/logic.js")
    assert out["partial"] and out["total_lines"] == 401
    assert out["outline"][0].startswith("2: export function step0")
    assert out["content"].count("\n") == p._HEAD_LINES and "start_line/end_line" in out["hint"]
    part = p.read_ai_plugin_file("imk", "ui/logic.js", start_line=101, end_line=102)
    assert part["content"].startswith("export function step99(") and part["content"].count("\n") == 2
    assert not p.read_ai_plugin_file("imk", "ui/logic.js", start_line=500)["ok"]


def test_a_small_file_still_reads_whole(draft) -> None:
    (draft / "ui" / "x.js").write_text("const a = 1;\n", encoding="utf-8")
    out = p.read_ai_plugin_file("imk", "ui/x.js")
    assert out["content"] == "const a = 1;\n" and "partial" not in out


def test_editing_part_of_a_file_replaces_one_exact_snippet(draft) -> None:
    (draft / "ui" / "x.js").write_text("a = 1;\nb = 1;\nb = 1;\n", encoding="utf-8")
    assert "not found" in p.edit_ai_plugin_file("imk", "ui/x.js", "c = 1;", "c = 2;")["error"]
    assert "2 times" in p.edit_ai_plugin_file("imk", "ui/x.js", "b = 1;", "b = 2;")["error"]
    done = p.edit_ai_plugin_file("imk", "ui/x.js", "a = 1;", "a = 2;")
    assert done["ok"] and done["replacements"] == 1
    assert p.edit_ai_plugin_file("imk", "ui/x.js", "b = 1;", "b = 3;", replace_all=True)["replacements"] == 2
    assert (draft / "ui" / "x.js").read_text(encoding="utf-8") == "a = 2;\nb = 3;\nb = 3;\n"
    assert not p.edit_ai_plugin_file("imk", "../escape.js", "a", "b")["ok"]  # still path-jailed
