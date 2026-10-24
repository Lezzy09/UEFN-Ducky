"""ducky_generate_image: a chat makes a picture on the person's default maker and sees it."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from backend.automations import media
from backend.tools.core import workspace_code
from frontend.ui_web import generated_images as gen

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def maker(tmp_path: Path, monkeypatch) -> list[dict[str, Any]]:
    (tmp_path / "gen").mkdir()
    monkeypatch.setattr(gen, "generated_images_dir", lambda for_write=False: tmp_path / "gen")
    monkeypatch.setattr(gen, "_chat_of_caller", lambda: "c1")
    monkeypatch.setattr(media, "default_provider", lambda ntype: "")
    calls: list[dict[str, Any]] = []

    def draw(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        out = Path(kwargs["output_dir"]) / "duck.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_PNG)
        return {"downloaded": [str(out)]}

    rows = [{"id": "ducky_ai_image", "label": "Ducky AI · Image", "plugin": "Ducky AI", "plugin_id": "account",
             "tool": "ducky_ai_image", "credits": 0, "cost": "Ducky AI credit", "paid": True,
             "args": lambda i, c: {"prompt": i["prompt"]}}]
    monkeypatch.setattr(media, "table", lambda ntype: rows)
    monkeypatch.setattr(media, "tool_fn", lambda name: draw)
    return calls


def test_it_asks_before_spending_then_keeps_the_picture_for_the_chat_once(maker) -> None:
    with pytest.raises(ValueError, match="confirm_spend=true"):
        workspace_code.ducky_generate_image("a duck")
    assert maker == []
    out = workspace_code.ducky_generate_image("a duck", confirm_spend=True)
    from mcp.server.fastmcp import Image

    assert isinstance(out[1], Image) and json.loads(out[0])["backend"] == "Ducky AI · Image"
    assert maker[0]["prompt"] == "a duck" and maker[0]["confirm_spend"] is True
    kept = [r for r in gen.list_generated_images() if r.get("conv_id") == "c1"]
    assert len(kept) == 1 and Path(kept[0]["path"]).read_bytes() == _PNG


def test_a_picture_the_plugin_already_kept_is_not_kept_again(maker, monkeypatch) -> None:
    real = media.tool_fn("ducky_ai_image")

    def kept_by_plugin(**kwargs: Any) -> dict[str, Any]:
        data = real(**kwargs)
        gen.save_generated_image(_PNG, conv_id="c1", filename="from_plugin.png")
        return data

    monkeypatch.setattr(media, "tool_fn", lambda name: kept_by_plugin)
    workspace_code.ducky_generate_image("a duck", confirm_spend=True)
    assert [r["name"] for r in gen.list_generated_images()] == ["from_plugin.png"]
