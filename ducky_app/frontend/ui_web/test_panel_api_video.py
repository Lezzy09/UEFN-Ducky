from __future__ import annotations

import base64

from frontend.ui_web.panel_api import PanelApi


def test_video_settings_roundtrip_and_clamp(monkeypatch):
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.status", lambda: {"state": "missing"})
    api = PanelApi()
    out = api.set_video_settings({"video_max_mb": 500, "video_frames_per_video": "12", "max_images_per_message": 0})
    assert (out["video_max_mb"], out["video_frames_per_video"], out["max_images_per_message"]) == (200, 12, 0)
    assert api.get_video_settings()["video_frames_per_video"] == 12
    assert out["ffmpeg"] == {"state": "missing"}


def test_stage_unknown_conv_starts_ffmpeg(monkeypatch):
    started = []
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.start_install", lambda: started.append(1) or {"state": "installing"})
    res = PanelApi().stage_video_attachment("nope", "a.mp4", "video/mp4", base64.b64encode(b"x").decode())
    assert res["ok"] and res["needs_ffmpeg"] and started == [1]
    assert res["ffmpeg"] == {"state": "installing"}


def test_stage_gemini_conv_skips_ffmpeg(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "frontend.ui_web.project_chats.load_conversation",
        lambda cid, project_root=None: SimpleNamespace(is_group=False, coding_agent="ducky", provider="gemini"),
    )
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.start_install", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.status", lambda: {"state": "missing"})
    res = PanelApi().stage_video_attachment("c1", "a.mp4", "video/mp4", base64.b64encode(b"x").decode())
    assert res["ok"] and res["needs_ffmpeg"] is False


def test_stage_error_is_returned_not_raised():
    res = PanelApi().stage_video_attachment("c", "a.avi", "video/avi", "eA==")
    assert res == {"ok": False, "error": "Unsupported video format for 'a.avi' — use MP4, WebM, MOV or MKV."}


def test_video_settings_accept_auto(monkeypatch):
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.status", lambda: {"state": "missing"})
    api = PanelApi()
    api.set_video_settings({"video_frames_per_video": 12, "max_images_per_message": 60})
    out = api.set_video_settings({"video_frames_per_video": 0, "max_images_per_message": 0})
    assert out["video_frames_per_video"] == 0 and out["max_images_per_message"] == 0
    assert out["auto"] == {"frames_per_video": 20, "max_images_per_message": 20}
    assert api.get_video_settings()["video_frames_per_video"] == 0
