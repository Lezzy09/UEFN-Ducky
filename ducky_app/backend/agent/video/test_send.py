from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent.video import send
from backend.agent.video.frames import Frame, VideoError


def _setup(tmp_path, monkeypatch):
    conv_dir = tmp_path / "conv1"
    (conv_dir / "attachments").mkdir(parents=True)
    video = conv_dir / "attachments" / "1_0_bug.mp4"
    video.write_bytes(b"v")
    calls = []

    def fake_extract(path, n):
        calls.append((path, n))
        out = []
        for k in range(n):
            p = path.with_name(f"{path.name}.f{n:02d}-{k + 1:02d}.jpg")
            p.write_bytes(b"j")
            out.append(Frame(p, float(k)))
        return out

    monkeypatch.setattr(send, "extract_frames", fake_extract)
    row = {"kind": "video", "name": "bug.mp4", "mime": "video/mp4", "path": "attachments/1_0_bug.mp4", "size_bytes": 1}
    return conv_dir, row, calls


def test_frames_added_for_non_gemini(tmp_path, monkeypatch):
    conv_dir, row, calls = _setup(tmp_path, monkeypatch)
    statuses = []
    send.prepare_video_frames([row], conv_dir=conv_dir, provider="anthropic", external=False, push_status=statuses.append)
    assert calls and calls[0][1] == 20
    assert row["frames"][0] == {"path": "attachments/1_0_bug.mp4.f20-01.jpg", "t_s": 0.0}
    assert any("Extracting frames" in s for s in statuses)


def test_gemini_small_mp4_gets_no_frames(tmp_path, monkeypatch):
    conv_dir, row, calls = _setup(tmp_path, monkeypatch)
    send.prepare_video_frames([row], conv_dir=conv_dir, provider="gemini", external=False)
    assert calls == [] and "frames" not in row


def test_image_cap_counts_frames(tmp_path, monkeypatch):
    conv_dir, row, _ = _setup(tmp_path, monkeypatch)
    images = [{"kind": "image", "path": "attachments/x.png"}] * 25
    with pytest.raises(VideoError, match="Too many images"):
        send.prepare_video_frames([row, *images], conv_dir=conv_dir, provider="openai", external=False)


def test_runtime_dict_uses_absolute_paths(tmp_path, monkeypatch):
    conv_dir, row, _ = _setup(tmp_path, monkeypatch)
    row["frames"] = [{"path": "attachments/f.jpg", "t_s": 1.5}]
    out = send.runtime_video_dict(row, conv_dir)
    assert out == {
        "kind": "video", "name": "bug.mp4", "mime": "video/mp4",
        "abs_path": str(conv_dir / "attachments/1_0_bug.mp4"),
        "frames": [{"abs_path": str(conv_dir / "attachments/f.jpg"), "t_s": 1.5}],
    }


def test_collect_image_paths_includes_video_frames(tmp_path, monkeypatch):
    from backend.agent.coding_agents import runner as ca

    conv_dir = tmp_path / "convs" / "c1"
    (conv_dir / "attachments").mkdir(parents=True)
    (conv_dir / "attachments" / "f1.jpg").write_bytes(b"j")
    monkeypatch.setattr("frontend.ui_web.project_chats.get_conversations_dir", lambda root=None: tmp_path / "convs")
    conv = SimpleNamespace(id="c1", messages=[{"role": "user", "attachments": [
        {"kind": "video", "path": "attachments/v.mp4", "frames": [{"path": "attachments/f1.jpg", "t_s": 0.5}]},
    ]}])
    assert ca.collect_image_paths(conv) == [str((conv_dir / "attachments" / "f1.jpg").resolve())]
