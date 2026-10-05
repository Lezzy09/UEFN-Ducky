from __future__ import annotations

from frontend.ui_web import panel_httpd as h


def test_regex_accepts_videos_and_frames():
    assert h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/1_0_bug.mp4")
    assert h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/1_0_bug.mp4.f20-01.jpg")
    assert not h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/evil.exe")


def test_read_file_range(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0123456789")
    assert h._read_file_range(f, None) == (200, b"0123456789", {"Accept-Ranges": "bytes"})
    status, body, headers = h._read_file_range(f, "bytes=2-4")
    assert (status, body) == (206, b"234")
    assert headers == {"Accept-Ranges": "bytes", "Content-Range": "bytes 2-4/10"}
    status, body, headers = h._read_file_range(f, "bytes=50-60")
    assert (status, body, headers["Content-Range"]) == (416, b"", "bytes */10")
