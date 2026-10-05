from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from backend.agent.video import frames as fr
from backend.agent.video import ffmpeg_install as fi


def test_frame_times_are_centered_in_equal_slices():
    assert fr.frame_times(10.0, 4) == [1.25, 3.75, 6.25, 8.75]
    assert fr.frame_times(0.0, 5) == [0.0]
    assert fr.frame_times(3.0, 0) == []


def test_frame_paths_sit_next_to_video_and_encode_count(tmp_path):
    v = tmp_path / "1_0_bug.mp4"
    assert [p.name for p in fr.frame_paths(v, 2)] == ["1_0_bug.mp4.f02-01.jpg", "1_0_bug.mp4.f02-02.jpg"]


def _fake_tools(monkeypatch, tmp_path, *, probe_out="4.0", probe_rc=0, ff_rc=0, write=True, slow=False):
    ffmpeg, ffprobe = tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe"
    monkeypatch.setattr(fr, "ensure_installed", lambda: (ffmpeg, ffprobe))
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        if slow and Path(args[0]) == ffmpeg:
            raise subprocess.TimeoutExpired(args, timeout)
        if Path(args[0]) == ffprobe:
            return subprocess.CompletedProcess(args, probe_rc, stdout=probe_out, stderr="")
        if write and ff_rc == 0:
            Path(args[-1]).write_bytes(b"jpg")
        return subprocess.CompletedProcess(args, ff_rc, stdout="", stderr="boom")

    monkeypatch.setattr(fr, "_runner", runner)
    return calls


def test_extract_frames_runs_one_seek_per_frame(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    out = fr.extract_frames(video, 2)
    assert [f.t_s for f in out] == [1.0, 3.0]
    assert all(f.path.is_file() for f in out)
    ff_calls = [c for c in calls if Path(c[0]).name == "ffmpeg.exe"]
    assert len(ff_calls) == 2
    assert ff_calls[0][ff_calls[0].index("-ss") + 1] == "1.000"
    assert "scale='min(1280,iw)':-2" in ff_calls[0]


def test_existing_frames_are_reused(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    fr.extract_frames(video, 2)
    calls.clear()
    fr.extract_frames(video, 2)
    assert [Path(c[0]).name for c in calls] == ["ffprobe.exe"]


def test_unreadable_video(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, probe_rc=1, probe_out="")
    video = tmp_path / "broken.mp4"
    video.write_bytes(b"x")
    with pytest.raises(fr.VideoError, match="Cannot read video 'broken.mp4'"):
        fr.extract_frames(video, 3)


def test_timeout(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, slow=True)
    video = tmp_path / "long.mp4"
    video.write_bytes(b"x")
    with pytest.raises(fr.VideoError, match="took longer than 60s"):
        fr.extract_frames(video, 3)


def test_install_failure_becomes_video_error(monkeypatch, tmp_path):
    def boom():
        raise fi.FfmpegInstallError("ffmpeg download failed — check your internet connection.")

    monkeypatch.setattr(fr, "ensure_installed", boom)
    with pytest.raises(fr.VideoError, match="internet"):
        fr.extract_frames(tmp_path / "x.mp4", 2)


_REAL = os.environ.get("DUCKY_FFMPEG_DIR", "")


@pytest.mark.skipif(not _REAL, reason="set DUCKY_FFMPEG_DIR to a folder with ffmpeg.exe + ffprobe.exe")
def test_real_ffmpeg_extracts_frames(monkeypatch, tmp_path):
    ffmpeg, ffprobe = Path(_REAL) / "ffmpeg.exe", Path(_REAL) / "ffprobe.exe"
    monkeypatch.setattr(fr, "ensure_installed", lambda: (ffmpeg, ffprobe))
    video = tmp_path / "test.mp4"
    subprocess.run(
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10", "-y", str(video)],
        check=True,
    )
    out = fr.extract_frames(video, 4)
    assert [f.t_s for f in out] == [0.375, 1.125, 1.875, 2.625]
    assert all(f.path.stat().st_size > 0 for f in out)
