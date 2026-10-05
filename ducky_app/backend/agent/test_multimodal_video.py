from __future__ import annotations

import base64
import sys
import types as pytypes

from backend.agent.message_attachment import MessageAttachment
from backend.agent.multimodal_content import (
    build_anthropic_user_content,
    build_gemini_user_parts,
    build_openai_user_content,
)


def _video(tmp_path, *, frames=2, mime="video/mp4", size=10):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"VIDEO")
    fr = []
    for k in range(frames):
        p = tmp_path / f"f{k}.jpg"
        p.write_bytes(f"J{k}".encode())
        fr.append((str(p), 65.0 * k))
    return MessageAttachment(kind="video", name="bug.mp4", mime=mime, file_path=str(v), size_bytes=size, frames=fr)


def test_anthropic_gets_labelled_frames(tmp_path):
    blocks = build_anthropic_user_content("look", [_video(tmp_path)])
    assert blocks[0] == {"type": "text", "text": "look"}
    assert blocks[1] == {"type": "text", "text": 'Video "bug.mp4" — frame 1/2 at 00:00'}
    assert blocks[2]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"J0").decode()}
    assert blocks[3]["text"] == 'Video "bug.mp4" — frame 2/2 at 01:05'


def test_openai_gets_labelled_frames(tmp_path):
    parts = build_openai_user_content("", [_video(tmp_path, frames=1)])
    assert parts[0] == {"type": "text", "text": 'Video "bug.mp4" — frame 1/1 at 00:00'}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(b"J0").decode()


def test_video_without_frames_becomes_a_note(tmp_path):
    blocks = build_anthropic_user_content("x", [_video(tmp_path, frames=0)])
    assert blocks[-1] == {"type": "text", "text": '[Video "bug.mp4" attached but could not be analyzed]'}


def _fake_genai(monkeypatch):
    class Part:
        def __init__(self, **kw):
            self.kw = kw

        @staticmethod
        def from_text(text):
            return Part(text=text)

        @staticmethod
        def from_bytes(data, mime_type):
            return Part(data=data, mime_type=mime_type)

    types_mod = pytypes.SimpleNamespace(Part=Part)
    genai = pytypes.ModuleType("google.genai")
    genai.types = types_mod
    google = pytypes.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


def test_gemini_small_video_goes_native(tmp_path, monkeypatch):
    _fake_genai(monkeypatch)
    parts = build_gemini_user_parts("q", [_video(tmp_path, mime="video/quicktime")])
    assert parts[1].kw == {"data": b"VIDEO", "mime_type": "video/mov"}
    assert len(parts) == 2


def test_gemini_big_video_falls_back_to_frames(tmp_path, monkeypatch):
    _fake_genai(monkeypatch)
    parts = build_gemini_user_parts("q", [_video(tmp_path, size=50 * 1024 * 1024)])
    assert parts[1].kw == {"text": 'Video "bug.mp4" — frame 1/2 at 00:00'}
    assert parts[2].kw == {"data": b"J0", "mime_type": "image/jpeg"}
