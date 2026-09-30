"""Persist and hydrate per-conversation message attachments on disk."""

from __future__ import annotations

import base64
import re
import time
import uuid
from pathlib import Path
from typing import Any

from backend.agent.message_attachment import MessageAttachment

_UNSAFE_CHARS = re.compile(r"[^\w.\-]+")
_CONV_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_CHAT_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+\.(?:png|jpe?g|webp)$", re.IGNORECASE)
NO_CHAT_CAPTURE_ERROR = "Screenshot was not saved: no active chat."


def _safe_attachment_filename(name: str) -> str:
    base = Path(name).name or "attachment"
    safe = _UNSAFE_CHARS.sub("_", base).strip("._")
    return (safe or "attachment")[:120]


def conversation_dir(conv_id: str, project_root: str | None, conversations_dir: Path) -> Path:
    return conversations_dir / conv_id


def conversation_attachments_dir(conv_id: str, project_root: str | None, conversations_dir: Path) -> Path:
    return conversation_dir(conv_id, project_root, conversations_dir) / "attachments"


def conversation_meta_path(conv_id: str, conversations_dir: Path) -> Path:
    return conversations_dir / conv_id / "conversation.json"


def persist_message_attachments(
    conv_id: str,
    message_ts: float,
    attachments: list[MessageAttachment],
    conversations_dir: Path,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    """Write attachment bytes/text under conversations/{conv_id}/attachments/."""
    del project_root  # reserved for future multi-root layouts
    if not attachments:
        return []
    conv_path = conversation_dir(conv_id, None, conversations_dir)
    att_dir = conversation_attachments_dir(conv_id, None, conversations_dir)
    att_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    ts_tag = int(message_ts * 1000)
    for i, att in enumerate(attachments):
        safe = _safe_attachment_filename(att.name)
        filename = f"{ts_tag}_{i}_{safe}"
        rel = f"attachments/{filename}"
        full = conv_path / rel
        if att.kind == "image" and att.data_base64:
            try:
                full.write_bytes(base64.b64decode(att.data_base64, validate=True))
            except Exception:
                continue
            out.append({"kind": "image", "name": att.name, "mime": att.mime or "image/png", "path": rel})
        elif att.kind == "file":
            full.write_text(att.text or "", encoding="utf-8")
            out.append(
                {
                    "kind": "file",
                    "name": att.name,
                    "mime": att.mime or "text/plain",
                    "path": rel,
                }
            )
    return out


def hydrate_attachment_dict(
    raw: dict[str, Any],
    conv_id: str,
    conversations_dir: Path,
    project_root: str | None = None,
) -> dict[str, Any]:
    del project_root
    if not isinstance(raw, dict):
        return raw
    kind = str(raw.get("kind") or "").strip().lower()
    path = str(raw.get("path") or "").strip()
    if not path:
        return raw
    full = conversation_dir(conv_id, None, conversations_dir) / path
    if not full.is_file():
        return raw
    if kind == "image":
        data = base64.b64encode(full.read_bytes()).decode("ascii")
        return {**raw, "data_base64": data}
    if kind == "file":
        return {**raw, "text": full.read_text(encoding="utf-8")}
    return raw


def active_chat_id() -> str:
    """Conversation bound on this tool call, else DUCKY_CONV_ID on a dedicated bridge, or empty."""
    try:
        from backend.workspace.identity import resolve_context

        ctx = resolve_context()
    except Exception:
        return ""
    return str(getattr(ctx, "conv_id", "") or "").strip()


def chat_attachments_dir(conv_id: str, *, create: bool = False) -> Path | None:
    """`…/chats/projects/<project>/conversations/<chat>/attachments`, or None."""
    cid = (conv_id or "").strip()
    if not _CONV_ID_RE.fullmatch(cid):
        return None
    from frontend.ui_web.project_chats import get_conversations_dir

    path = get_conversations_dir(create=create) / cid / "attachments"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def build_chat_attachment_url(conv_id: str, filename: str) -> str:
    from frontend.settings import PANEL_LISTENER_PORT

    name = Path(filename).name
    port = PANEL_LISTENER_PORT - 1
    return f"http://127.0.0.1:{port}/chat-attachments/{conv_id}/{name}"


def resolve_chat_attachment_path(conv_id: str, filename: str) -> Path:
    cid = Path(conv_id or "").name
    name = Path(filename or "").name
    if cid != (conv_id or "") or not _CONV_ID_RE.fullmatch(cid) or not _CHAT_FILE_RE.fullmatch(name):
        raise ValueError("Invalid attachment")
    root = chat_attachments_dir(cid)
    if root is None:
        raise ValueError("Invalid attachment")
    target = (root / name).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path escapes chat attachments") from exc
    if not target.is_file():
        raise ValueError("Not a file")
    return target


def save_chat_screenshot(raw: bytes, *, prefix: str = "capture", conv_id: str = "") -> dict[str, Any]:
    """Write one PNG under the active chat's attachments folder. Nowhere else."""
    if not raw:
        return {"ok": False, "error": "Screenshot was empty."}
    cid = (conv_id or active_chat_id()).strip()
    dest_dir = chat_attachments_dir(cid, create=True) if cid else None
    if dest_dir is None:
        return {"ok": False, "error": NO_CHAT_CAPTURE_ERROR}
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", (prefix or "capture").strip())[:40] or "capture"
    name = f"{safe}_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    path = dest_dir / name
    path.write_bytes(raw)
    return {
        "ok": True,
        "path": str(path),
        "filename": name,
        "conv_id": cid,
        "media_url": build_chat_attachment_url(cid, name),
        "bytes": len(raw),
        "format": "png",
        "capture_path": str(path),
    }


def hydrate_attachment_dicts(
    raw_list: list[Any] | None,
    conv_id: str,
    conversations_dir: Path,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    if not raw_list:
        return []
    return [
        hydrate_attachment_dict(raw if isinstance(raw, dict) else {}, conv_id, conversations_dir, project_root)
        for raw in raw_list
    ]
