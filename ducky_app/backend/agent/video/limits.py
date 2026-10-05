"""User-tunable video limits (Settings → Videos), clamped to safe ranges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VIDEO_MAX_MB_RANGE = (10, 200)
FRAMES_PER_VIDEO_RANGE = (1, 40)
MAX_IMAGES_PER_MESSAGE_RANGE = (1, 100)
DEFAULT_VIDEO_MAX_MB = 100
DEFAULT_FRAMES_PER_VIDEO = 20
DEFAULT_MAX_IMAGES_PER_MESSAGE = 40


def clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int
    frames_per_video: int
    max_images_per_message: int


def video_limits() -> VideoLimits:
    from frontend.settings import PanelSettings

    s = PanelSettings.load()
    mb = clamp(getattr(s, "video_max_mb", None), *VIDEO_MAX_MB_RANGE, DEFAULT_VIDEO_MAX_MB)
    frames = clamp(
        getattr(s, "video_frames_per_video", None), *FRAMES_PER_VIDEO_RANGE, DEFAULT_FRAMES_PER_VIDEO
    )
    images = clamp(
        getattr(s, "max_images_per_message", None),
        *MAX_IMAGES_PER_MESSAGE_RANGE,
        DEFAULT_MAX_IMAGES_PER_MESSAGE,
    )
    return VideoLimits(max_bytes=mb * 1024 * 1024, frames_per_video=frames, max_images_per_message=images)
