"""An agent answers the next file picker, so a plugin's import flow can be checked without a person."""

from __future__ import annotations

import time

from frontend.ui_web import picker_queue as q


def test_the_next_pick_returns_the_queued_files_once(tmp_path, monkeypatch) -> None:
    # Oct 12 2026: a panel builder's import step waited on the person to click the Windows picker.
    from frontend.ui_web.panel_api_automations import PanelApiAutomationsMixin

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    assert not q.queue_pick([str(tmp_path / "missing.mp4")])["ok"]
    assert q.queue_pick([str(clip)])["ok"]
    api = PanelApiAutomationsMixin()  # no window: only a queued answer can reach the picker
    picked = api.pick_workflow_files("video", False)
    assert picked["ok"] and [f["path"] for f in picked["files"]] == [str(clip)]
    assert api.pick_workflow_files("video", False)["error"] == "No window to open the picker from"  # used once
    assert q.queue_pick([], cancel=True)["next_pick"] == "cancel"
    assert api.pick_workflow_files("any", True) == {"ok": True, "files": []}  # as when the person cancels


def test_a_queued_answer_expires(tmp_path, monkeypatch) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    q.queue_pick([str(clip)])
    real = time.time()
    monkeypatch.setattr(q.time, "time", lambda: real + q.QUEUE_S + 1)
    assert q.take_queued_pick() is None
