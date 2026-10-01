"""The editor's grid / snap / panel settings live on disk and survive a reload."""

from backend.automations import editor_prefs


def test_saves_known_settings_and_merges(monkeypatch, tmp_path):
    monkeypatch.setattr(editor_prefs, "_path", lambda: tmp_path / "workflow_editor.json")
    assert editor_prefs.load() == {}
    editor_prefs.save({"grid": "dots", "snap": False, "junk": 1})
    editor_prefs.save({"panelZoom": {"list": 1.2}})
    assert editor_prefs.load() == {"grid": "dots", "snap": False, "panelZoom": {"list": 1.2}}
    (tmp_path / "workflow_editor.json").write_text("not json", encoding="utf-8")
    assert editor_prefs.load() == {}
