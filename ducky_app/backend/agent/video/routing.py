"""Decide whether a recipient gets the raw video (Gemini) or extracted frames."""

from __future__ import annotations

GEMINI_PROVIDER = "gemini"
GEMINI_INLINE_MAX_BYTES = 20 * 1024 * 1024
_GEMINI_MIME = {
    "video/mp4": "video/mp4",
    "video/webm": "video/webm",
    "video/quicktime": "video/mov",
}


def gemini_inline_mime(mime: str, size_bytes: int) -> str | None:
    if size_bytes > GEMINI_INLINE_MAX_BYTES:
        return None
    return _GEMINI_MIME.get((mime or "").strip().lower())


def needs_frames(mime: str, size_bytes: int, *, provider: str, external: bool) -> bool:
    if external:
        return True
    if (provider or "").strip().lower() != GEMINI_PROVIDER:
        return True
    return gemini_inline_mime(mime, size_bytes) is None
