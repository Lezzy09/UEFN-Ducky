"""view_image: agents look at attachments and screenshots with Ducky's tool, not their own Read."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.tools.core import workspace_code

# A 1x1 transparent PNG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def chats(tmp_path: Path, monkeypatch) -> Path:
    import frontend.settings as settings

    monkeypatch.setattr(settings, "default_app_data_dir", lambda: tmp_path / "appdata")
    folder = tmp_path / "appdata" / "chats" / "projects" / "p" / "conversations" / "c1" / "attachments"
    folder.mkdir(parents=True)
    return folder


def test_an_attachment_comes_back_as_a_picture(chats: Path) -> None:
    shot = chats / "shot.png"
    shot.write_bytes(_PNG)
    out = workspace_code.view_image(str(shot))
    assert isinstance(out, list) and len(out) == 2
    assert '"bytes":70' in out[0].replace(" ", "")
    from mcp.server.fastmcp import Image

    assert isinstance(out[1], Image)
    # The chat's tool card shows it: an attachment links to itself, nothing is copied.
    assert '"media_url":"http://127.0.0.1:' in out[0].replace(" ", "") and "/chat-attachments/c1/shot.png" in out[0]


def test_a_picture_outside_the_chat_is_copied_in_for_the_card(monkeypatch) -> None:
    saved: list[bytes] = []

    def fake_save(raw, *, prefix="capture", conv_id=""):
        saved.append(raw)
        return {"ok": True, "media_url": f"http://x/chat-attachments/c9/{prefix}_1.png"}

    monkeypatch.setattr("frontend.ui_web.conversation_attachments.save_chat_screenshot", fake_save)
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        icon = Path(folder) / "icon.png"
        icon.write_bytes(_PNG)
        assert workspace_code._picture_url(str(icon)) == "http://x/chat-attachments/c9/viewed_icon_1.png"
        gif = Path(folder) / "a.gif"
        gif.write_bytes(b"GIF89a")
        assert workspace_code._picture_url(str(gif)) == ""  # the panel serves no gif: the card shows the path
    assert saved == [_PNG]


def test_only_pictures_and_only_allowed_places(chats: Path, tmp_path: Path) -> None:
    notes = chats / "notes.txt"
    notes.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="Not a picture"):
        workspace_code.view_image(str(notes))
    stray = tmp_path / "elsewhere" / "x.png"
    stray.parent.mkdir()
    stray.write_bytes(_PNG)
    with pytest.raises(ValueError):
        workspace_code.view_image(str(stray))
    with pytest.raises(ValueError, match="No such picture"):
        workspace_code.view_image(str(chats / "missing.png"))
