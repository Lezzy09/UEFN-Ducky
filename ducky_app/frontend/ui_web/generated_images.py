"""Durable generated images — AppData only, never the UEFN project, never tool_captures.

tool_captures is a 40-file screenshot prune. This folder is user data.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from frontend.app_paths import resolve_app_data_dir
from frontend.settings import PANEL_LISTENER_PORT

_PANEL_UI_HTTP_PORT = PANEL_LISTENER_PORT - 1
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.(?:png|jpe?g|webp)$", re.IGNORECASE)
_INDEX = "index.json"
# Image tools that predate plugin-declared generators; the rest come from what the
# plugins turned on here declare (contributes.automations.image_generators).
_IMAGE_TOOLS = frozenset(
    {
        "meshy_text_to_image",
        "photoshop_generate_image",
        "openai.image",
        "google.image",
    }
)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def generated_images_dir(*, for_write: bool = False) -> Path:
    path = resolve_app_data_dir(for_write=for_write) / "generated_images"
    if for_write:
        path.mkdir(parents=True, exist_ok=True)
    return path


def build_generated_image_url(filename: str) -> str:
    return f"http://127.0.0.1:{_PANEL_UI_HTTP_PORT}/generated-images/{Path(filename).name}"


def resolve_generated_image_path(filename: str) -> Path:
    name = Path(filename or "").name
    if not _NAME_RE.match(name):
        raise ValueError("Invalid generated image name")
    target = (generated_images_dir() / name).resolve()
    root = generated_images_dir().resolve()
    target.relative_to(root)
    if not target.is_file():
        raise ValueError("Not a file")
    return target


def _index_path() -> Path:
    return generated_images_dir(for_write=True) / _INDEX


def _load_index() -> list[dict[str, Any]]:
    path = generated_images_dir() / _INDEX
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _save_index(rows: list[dict[str, Any]]) -> None:
    _index_path().write_text(json.dumps(rows, indent=2), encoding="utf-8")


def save_generated_image(
    raw: bytes,
    *,
    prompt: str = "",
    gateway: str = "",
    model: str = "",
    filename: str = "",
    mime: str = "image/png",
    conv_id: str = "",
) -> dict[str, Any]:
    if not raw:
        return {"ok": False, "error": "empty image"}
    dest_dir = generated_images_dir(for_write=True)
    ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".webp" if "webp" in mime else ".png"
    name = Path(filename).name if filename else f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    if not _NAME_RE.match(name):
        name = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    if (dest_dir / name).exists():
        # Another picture (maybe another chat's) has this name: never take over its row.
        name = f"{Path(name).stem}_{uuid.uuid4().hex[:8]}{Path(name).suffix}"
    dest = dest_dir / name
    dest.write_bytes(raw)
    row = {
        "ok": True,
        "name": name,
        "path": str(dest),
        "filename": name,
        "media_url": build_generated_image_url(name),
        "prompt": prompt,
        "gateway": gateway,
        "model": model,
        "created": time.time(),
        "bytes": len(raw),
        "mime": mime,
        "conv_id": conv_id,
    }
    rows = [r for r in _load_index() if r.get("name") != name]
    rows.insert(0, {k: v for k, v in row.items() if k != "ok"})
    _save_index(rows)
    return row


def list_generated_images() -> list[dict[str, Any]]:
    rows = _load_index()
    root = generated_images_dir()
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or row.get("filename") or "")
        path = root / name
        if name and path.is_file():
            item = dict(row)
            item["path"] = str(path)
            item["media_url"] = build_generated_image_url(name)
            out.append(item)
    return out


def attachment_from_path(path: str | Path) -> dict[str, Any] | None:
    src = Path(path)
    if not src.is_file() or src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    mime = "image/jpeg" if src.suffix.lower() in {".jpg", ".jpeg"} else "image/webp" if src.suffix.lower() == ".webp" else "image/png"
    return {
        "kind": "image",
        "name": src.name,
        "mime": mime,
        "data_base64": base64.b64encode(src.read_bytes()).decode("ascii"),
        "path": str(src),
    }


def image_tool_names() -> set[str]:
    names = set(_IMAGE_TOOLS)
    try:
        from backend.uefn_plugins.host import image_generator_tools

        names |= image_generator_tools()
    except Exception:
        pass
    return names


def is_image_tool(tool_name: str) -> bool:
    name = str(tool_name or "")
    return name in image_tool_names() or name.endswith(".image") or "_to_image" in name or "generate_image" in name


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png"


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return {}
    if not isinstance(result, dict):
        return {}
    if isinstance(result.get("data"), dict):
        return {**result["data"], **{k: v for k, v in result.items() if k != "data"}}
    return result


def _images_in(result: Any) -> list[tuple[str, bytes, str]]:
    """(file name, bytes, mime) for each picture a tool result names or carries.

    Plugin image tools return JSON text with ``downloaded: [path, …]``; others a ``path``
    or base64 bytes, sometimes under ``data``.
    """
    data = _as_dict(result)
    paths: list[str] = []
    for item in data.get("downloaded") or []:
        if isinstance(item, dict):
            item = item.get("path") or item.get("file") or ""
        paths.append(str(item or ""))
    paths += [str(data.get(key) or "") for key in ("path", "output_path", "file", "saved_path")]
    out: list[tuple[str, bytes, str]] = []
    seen: set[str] = set()
    for raw_path in paths:
        if not raw_path or raw_path in seen:
            continue
        seen.add(raw_path)
        path = Path(raw_path)
        if path.suffix.lower() in _IMAGE_SUFFIXES and path.is_file():
            out.append((path.name, path.read_bytes(), _mime_for(path)))
    b64 = str(data.get("data_base64") or data.get("b64_json") or data.get("image_base64") or "")
    if b64 and not out:
        try:
            out.append(("", base64.b64decode(b64), str(data.get("mime") or "image/png")))
        except ValueError:
            pass
    return out


def _chat_of_caller() -> str:
    try:
        from backend.workspace.identity import resolve_context

        ctx = resolve_context()
    except Exception:
        return ""
    return str(getattr(ctx, "conv_id", "") or "") if ctx is not None else ""


def note_tool_images(tool_name: str, result: Any, *, conv_id: str = "") -> list[dict[str, Any]]:
    """Keep the pictures an image tool made in a chat, so that turn's reply shows them.

    Runs for every plugin tool and every agent (Ducky, Codex, Claude Code, Cursor). Only
    image tools called from a chat save anything: a workflow keeps its own outputs.
    """
    if not is_image_tool(tool_name):
        return []
    chat = conv_id or _chat_of_caller()
    if not chat:
        return []
    meta = _as_dict(result)
    return [
        save_generated_image(
            raw,
            prompt=str(meta.get("prompt") or meta.get("revised_prompt") or ""),
            gateway=str(tool_name),
            model=str(meta.get("model") or ""),
            filename=name,
            mime=mime,
            conv_id=chat,
        )
        for name, raw, mime in _images_in(result)
    ]


def note_image_file(path: str | Path, *, conv_id: str, gateway: str, prompt: str = "") -> dict[str, Any] | None:
    """Keep a picture an agent made by itself (Codex image generation) for its chat."""
    src = Path(path)
    if not conv_id or src.suffix.lower() not in _IMAGE_SUFFIXES or not src.is_file():
        return None
    return save_generated_image(src.read_bytes(), prompt=prompt, gateway=gateway, filename=src.name,
                                mime=_mime_for(src), conv_id=conv_id)


def turn_attachments(conv_id: str, since: float) -> list[dict[str, Any]]:
    """The pictures made for this chat since its turn started, oldest first.

    Stored on the reply as references (``generated``: the file name here); the chat adds
    the bytes when it loads, like the person's own attachments, so chats stay small.
    """
    if not conv_id:
        return []
    rows = [r for r in _load_index() if r.get("conv_id") == conv_id and float(r.get("created") or 0) >= since]
    root = generated_images_dir()
    out = []
    for row in sorted(rows, key=lambda r: float(r.get("created") or 0)):
        name = str(row.get("name") or "")
        if name and (root / name).is_file():
            out.append({"kind": "image", "name": name, "mime": str(row.get("mime") or "image/png"), "generated": name})
    return out


def hydrate_generated(raw: dict[str, Any]) -> dict[str, Any]:
    """A reply's picture reference with its bytes, for the chat to draw."""
    try:
        path = resolve_generated_image_path(str(raw.get("generated") or ""))
    except (ValueError, OSError):
        return raw
    return {**raw, "data_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
