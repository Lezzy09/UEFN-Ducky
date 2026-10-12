"""Opening a plugin's source never asks to replace a local draft (one Yes wiped unpublished work)."""

from __future__ import annotations

import json


def test_an_existing_draft_is_returned_without_asking(tmp_path, monkeypatch):
    from backend.tools.panel import panel_plugin_publish as pub
    from backend.uefn_plugins import publishing, store

    (tmp_path / "demo").mkdir()
    monkeypatch.setattr(store, "appdata_ai_plugins_dir", lambda: tmp_path)
    asked: list[str] = []
    monkeypatch.setattr(pub, "_confirm", lambda prompt, title="Confirm": asked.append(prompt) or True)
    opened: list[str] = []
    monkeypatch.setattr(publishing, "open_for_edit", lambda pid, team_id="": opened.append(pid) or {"ok": True})
    result = json.loads(pub.ducky_plugin_open_source("demo"))
    assert result["ok"] and result["status"] == "draft_exists" and result["path"] == str(tmp_path / "demo")
    assert asked == [] and opened == []
    # No draft yet: the published source is opened as before.
    assert json.loads(pub.ducky_plugin_open_source("other"))["ok"] and opened == ["other"]
