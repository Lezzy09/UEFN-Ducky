from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest

from backend.agent.video import audio, frames, prep


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    prep._jobs.clear()
    monkeypatch.setattr(prep, "resolve_staged", lambda sid: tmp_path / sid)
    yield
    prep._jobs.clear()


def _wait(sid, states=("ready", "error"), timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        st = prep.prep_status(sid)
        if st["state"] in states:
            return st
        time.sleep(0.01)
    raise AssertionError(prep.prep_status(sid))


def test_progress_ready_and_transcript(monkeypatch, tmp_path):
    gate, seen = threading.Event(), threading.Event()
    vid = tmp_path / ("a" * 32 + ".mp4")

    def fake_extract(video, n, **kw):
        paths = frames.frame_paths(video, n)
        for p in paths[:3]:
            p.write_bytes(b"j")
        seen.set()
        gate.wait(5)
        for p in paths[3:]:
            p.write_bytes(b"j")
        return [frames.Frame(p, 0.0) for p in paths]

    monkeypatch.setattr(frames, "extract_frames", fake_extract)
    monkeypatch.setattr(audio, "transcribe_video", lambda v: audio.TranscriptResult("hi", ""))
    st = prep.start_prep(vid.name, frames=5, transcribe=True)
    assert st["state"] in ("queued", "extracting")
    assert seen.wait(5)
    mid = prep.prep_status(vid.name)
    assert (mid["state"], mid["frames_done"], mid["frames_total"]) == ("extracting", 3, 5)
    gate.set()
    done = _wait(vid.name)
    assert done == {"state": "ready", "frames_done": 5, "frames_total": 5,
                    "transcript": "ok", "transcript_note": "", "error": ""}


def test_transcript_note_and_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(frames, "extract_frames", lambda v, n, **k: [])
    monkeypatch.setattr(audio, "transcribe_video", lambda v: audio.TranscriptResult("", "No audio track"))
    prep.start_prep("n1.mp4", frames=2, transcribe=True)
    st = _wait("n1.mp4")
    assert (st["transcript"], st["transcript_note"]) == ("none", "No audio track")
    monkeypatch.setattr(audio, "transcribe_video", lambda v: (_ for _ in ()).throw(AssertionError))
    prep.start_prep("n2.mp4", frames=2, transcribe=False)
    assert _wait("n2.mp4")["transcript"] == "skipped"


def test_error_then_retry(monkeypatch):
    calls = []

    def boom(v, n, **k):
        calls.append(n)
        if len(calls) == 1:
            raise frames.VideoError("Cannot read video 'x'.")
        return []

    monkeypatch.setattr(frames, "extract_frames", boom)
    monkeypatch.setattr(audio, "transcribe_video", lambda v: audio.TranscriptResult("", ""))
    prep.start_prep("e.mp4", frames=4, transcribe=True)
    st = _wait("e.mp4")
    assert st["state"] == "error" and st["error"] == "Cannot read video 'x'."
    prep.retry_prep("e.mp4")
    assert _wait("e.mp4")["state"] == "ready"
    assert calls == [4, 4]


def test_idempotent_start(monkeypatch):
    gate, calls = threading.Event(), []

    def slow(v, n, **k):
        calls.append(1)
        gate.wait(5)
        return []

    monkeypatch.setattr(frames, "extract_frames", slow)
    monkeypatch.setattr(audio, "transcribe_video", lambda v: audio.TranscriptResult("", ""))
    prep.start_prep("i.mp4", frames=2, transcribe=True)
    prep.start_prep("i.mp4", frames=2, transcribe=True)
    gate.set()
    _wait("i.mp4")
    prep.start_prep("i.mp4", frames=2, transcribe=True)
    time.sleep(0.05)
    assert calls == [1]


def test_concurrency_cap(monkeypatch):
    gate, lock, active, peak = threading.Event(), threading.Lock(), [0], [0]

    def slow(v, n, **k):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        gate.wait(5)
        with lock:
            active[0] -= 1
        return []

    monkeypatch.setattr(frames, "extract_frames", slow)
    monkeypatch.setattr(audio, "transcribe_video", lambda v: audio.TranscriptResult("", ""))
    ids = [f"c{i}.mp4" for i in range(4)]
    for i in ids:
        prep.start_prep(i, frames=1, transcribe=True)
    time.sleep(0.3)
    assert peak[0] == 2
    assert sum(prep.prep_status(i)["state"] == "queued" for i in ids) == 2
    gate.set()
    for i in ids:
        _wait(i)
    assert peak[0] == 2


def test_unknown_id_is_ready():
    assert prep.prep_status("zzz.mp4")["state"] == "ready"


def test_expired_staged_id_errors(monkeypatch):
    def gone(sid):
        raise frames.VideoError("The video upload expired — attach the video again.")

    monkeypatch.setattr(prep, "resolve_staged", gone)
    st = prep.start_prep("g.mp4", frames=2, transcribe=True)
    assert st["state"] == "error"


def test_prep_files_satisfy_send_path_with_no_ffmpeg(monkeypatch, tmp_path):
    """Frames + transcript from prep survive persist's sibling rename; extract_frames then runs no ffmpeg."""
    from frontend.ui_web.conversation_attachments import persist_message_attachments
    from backend.agent.message_attachment import MessageAttachment

    staged = tmp_path / ("b" * 32 + ".mp4")
    staged.write_bytes(b"vid")
    ffmpeg, ffprobe = tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe"
    monkeypatch.setattr(frames, "ensure_installed", lambda: (ffmpeg, ffprobe))
    monkeypatch.setattr(audio, "ensure_installed", lambda: (ffmpeg, ffprobe))
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        if Path(args[0]) == ffprobe:
            out = "1\n"
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        Path(args[-1]).write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(frames, "_runner", runner)
    monkeypatch.setattr("backend.voice.transcription.transcribe_audio", lambda b, m: {"ok": True, "text": "hello"})
    prep.start_prep(staged.name, frames=3, transcribe=True)
    assert _wait(staged.name)["state"] == "ready"
    calls.clear()

    att = MessageAttachment(kind="video", name="clip.mp4", mime="video/mp4", file_path=str(staged), size_bytes=3)
    rows = persist_message_attachments("conv1", 1.5, [att], tmp_path / "convs")
    persisted = (tmp_path / "convs" / "conv1" / rows[0]["path"])
    assert persisted.is_file()
    got = frames.extract_frames(persisted, 3)
    assert len(got) == 3
    assert audio.transcribe_video(persisted) == audio.TranscriptResult("hello", "")
    assert [c for c in calls if Path(c[0]) == ffmpeg] == []  # cheap ffprobe duration read only
