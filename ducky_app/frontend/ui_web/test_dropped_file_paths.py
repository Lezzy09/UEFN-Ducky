"""A plugin panel can link a file dropped from Explorer without the native picker."""

from __future__ import annotations

from frontend.ui_web.panel_api_automations import PanelApiAutomationsMixin


def test_dropped_paths_are_handed_out_once_by_name(tmp_path, monkeypatch) -> None:
    # Oct 13 2026: a video dropped on the Island Media Kit bin opened the picker for the same file.
    import webview.dom as dom

    clip = tmp_path / "capture.mp4"
    clip.write_bytes(b"x")
    other = tmp_path / "notes.txt"
    other.write_bytes(b"y")
    monkeypatch.setattr(dom, "_dnd_state", {"num_listeners": 1, "paths": [("capture.mp4", str(clip)), ("notes.txt", str(other))]})
    api = PanelApiAutomationsMixin()
    got = api.consume_dropped_file_paths(["capture.mp4"])
    assert got["ok"] and [f["path"] for f in got["files"]] == [str(clip)]
    assert got["files"][0]["kind"] == "video" and got["files"][0]["name"] == "capture.mp4"
    assert dom._dnd_state["paths"] == [("notes.txt", str(other))]  # the other drop stays for its own zone
    assert api.consume_dropped_file_paths(["capture.mp4"])["files"] == []  # handed out once
    assert [f["path"] for f in api.consume_dropped_file_paths([])["files"]] == [str(other)]  # no names: take all
