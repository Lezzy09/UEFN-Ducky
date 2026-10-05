from __future__ import annotations

import base64
import os
import time

import pytest

from backend.agent.video import staging
from backend.agent.video.frames import VideoError
from backend.agent.video.routing import gemini_inline_mime, needs_frames

MB = 1024 * 1024


def test_gemini_inline_only_small_supported_types():
    assert gemini_inline_mime("video/mp4", 5 * MB) == "video/mp4"
    assert gemini_inline_mime("video/quicktime", 5 * MB) == "video/mov"
    assert gemini_inline_mime("video/x-matroska", 5 * MB) is None
    assert gemini_inline_mime("video/mp4", 21 * MB) is None


def test_needs_frames_rules():
    assert needs_frames("video/mp4", MB, provider="gemini", external=False) is False
    assert needs_frames("video/mp4", MB, provider="GEMINI", external=False) is False
    assert needs_frames("video/mp4", MB, provider="anthropic", external=False) is True
    assert needs_frames("video/mp4", MB, provider="gemini", external=True) is True
    assert needs_frames("video/mp4", 30 * MB, provider="gemini", external=False) is True


def test_normalize_mime_falls_back_to_extension():
    assert staging.normalize_video_mime("", "clip.MKV") == "video/x-matroska"
    assert staging.normalize_video_mime("video/mp4", "x") == "video/mp4"
    assert staging.normalize_video_mime("video/avi", "x.avi") is None


def test_stage_and_resolve_roundtrip():
    data = b"\x00" * 1024
    out = staging.stage_video("bug.mp4", "video/mp4", "data:video/mp4;base64," + base64.b64encode(data).decode())
    assert out["size_bytes"] == 1024 and out["mime"] == "video/mp4"
    path = staging.resolve_staged(out["staged_id"])
    assert path.read_bytes() == data and path.suffix == ".mp4"


def test_stage_rejects_unsupported_and_too_big(monkeypatch):
    with pytest.raises(VideoError, match="Unsupported video format"):
        staging.stage_video("a.avi", "video/avi", base64.b64encode(b"x").decode())
    from backend.agent.video import limits

    monkeypatch.setattr(staging, "video_limits", lambda: limits.VideoLimits(10, 20, 40))
    with pytest.raises(VideoError, match="exceeds the 0MB video limit|exceeds"):
        staging.stage_video("a.mp4", "video/mp4", base64.b64encode(b"x" * 11).decode())


def test_resolve_rejects_bad_ids():
    for bad in ["../x.mp4", "abc.mp4", "0" * 32 + ".exe", ""]:
        with pytest.raises(VideoError):
            staging.resolve_staged(bad)


def test_old_staged_files_are_swept():
    old = staging.staging_dir(create=True) / ("a" * 32 + ".mp4")
    old.write_bytes(b"x")
    past = time.time() - 2 * 24 * 3600
    os.utime(old, (past, past))
    staging.stage_video("b.mp4", "video/mp4", base64.b64encode(b"y").decode())
    assert not old.exists()


def test_is_inside_app_data(tmp_path):
    inside = staging.staging_dir(create=True) / "x.mp4"
    inside.write_bytes(b"x")
    assert staging.is_inside_app_data(inside) == inside.resolve()
    outside = tmp_path.parent / "elsewhere.mp4"
    assert staging.is_inside_app_data(outside) is None
