"""Durable generated_images store — not the screenshot prune bucket."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01"
    b"\xdd\x8d\xb4\x1c\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def gi(tmp_path, monkeypatch):
    from frontend.ui_web import generated_images as gi

    store = tmp_path / "generated"
    store.mkdir()
    monkeypatch.setattr(gi, "generated_images_dir", lambda for_write=False: store)
    monkeypatch.setattr("backend.uefn_plugins.host.image_generator_tools", lambda: {"ducky_ai_image", "studio3d_image_gemini3pro"})
    return gi


def test_save_list_and_attach(gi):
    row = gi.save_generated_image(_PNG, prompt="a waffle", gateway="openai", model="gpt-image-1")
    assert row["ok"] is True
    assert Path(row["path"]).is_file()
    listed = gi.list_generated_images()
    assert listed and listed[0]["prompt"] == "a waffle"
    att = gi.attachment_from_path(row["path"])
    assert att and att["kind"] == "image" and att["data_base64"]


def test_a_picture_an_image_tool_makes_in_a_chat_shows_in_that_turns_reply(gi, tmp_path):
    # Oct 11 2026: plugin image tools return JSON text with "downloaded" paths; the old code
    # only looked for "path", and only for the built-in agent, so no picture ever showed.
    made = tmp_path / "ducky-ai-gpt-image-1-1.png"
    made.write_bytes(_PNG)
    started = time.time() - 1
    result = json.dumps({"downloaded": [str(made)], "model": "gpt-image-1", "cost_usd": 0.04})
    assert gi.note_tool_images("spawn_actor", result, conv_id="chat-1") == []  # not an image tool
    assert gi.note_tool_images("ducky_ai_image", result) == []  # no chat: a workflow keeps its own
    saved = gi.note_tool_images("ducky_ai_image", result, conv_id="chat-1")
    assert len(saved) == 1 and saved[0]["gateway"] == "ducky_ai_image" and saved[0]["model"] == "gpt-image-1"
    gi.note_tool_images("studio3d_image_gemini3pro", {"data": {"downloaded": [{"path": str(made)}]}}, conv_id="other")

    pictures = gi.turn_attachments("chat-1", started)
    assert pictures == [{"kind": "image", "name": made.name, "mime": "image/png", "generated": made.name}]
    assert len(gi.turn_attachments("other", started)) == 1  # same file name, its own copy and chat
    assert gi.turn_attachments("chat-1", time.time() + 5) == []  # made before this turn
    drawn = gi.hydrate_generated(pictures[0])
    assert drawn["data_base64"]


def test_a_picture_codex_made_itself_is_kept_for_its_chat(gi, tmp_path):
    made = tmp_path / "exec-1234.png"
    made.write_bytes(_PNG)
    assert gi.note_image_file(made, conv_id="", gateway="codex") is None
    assert gi.note_image_file(made, conv_id="chat-2", gateway="codex")["conv_id"] == "chat-2"
    assert [p["name"] for p in gi.turn_attachments("chat-2", 0)] == ["exec-1234.png"]


def test_a_reply_with_a_picture_loads_with_it(gi, tmp_path):
    from frontend.ui_web.panel_api import _messages_to_ui

    made = tmp_path / "pic.png"
    made.write_bytes(_PNG)
    gi.note_image_file(made, conv_id="chat-3", gateway="codex")
    picture = gi.turn_attachments("chat-3", 0)[0]
    conv = SimpleNamespace(id="chat-3", messages=[
        {"role": "user", "content": "draw a duck"},
        {"role": "assistant", "content": "", "attachments": [picture]},  # a reply that is only the picture
    ])
    rows = _messages_to_ui(conv, str(tmp_path))
    assert rows[-1]["role"] == "assistant"
    assert rows[-1]["attachments"][0]["data_base64"]
