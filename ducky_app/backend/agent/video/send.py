"""Send-time video preparation: extract frames for recipients without native video."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from backend.agent.video.ffmpeg_install import binaries
from backend.agent.video.frames import VideoError, extract_frames
from backend.agent.video.limits import video_limits
from backend.agent.video.routing import needs_frames


def prepare_video_frames(
    stored: list[dict[str, Any]],
    *,
    conv_dir: Path,
    provider: str,
    external: bool,
    push_status: Callable[[str], None] | None = None,
) -> None:
    videos = [r for r in stored if r.get("kind") == "video" and r.get("path")]
    if not videos:
        return
    limits = video_limits()
    todo = [
        r
        for r in videos
        if needs_frames(
            str(r.get("mime") or ""), int(r.get("size_bytes") or 0), provider=provider, external=external
        )
    ]
    images = sum(1 for r in stored if r.get("kind") == "image")
    total = images + len(todo) * limits.frames_per_video
    if total > limits.max_images_per_message:
        raise VideoError(
            f"Too many images for one message ({total} including video frames, limit "
            f"{limits.max_images_per_message}). Lower 'Frames per video' in Settings → Videos "
            "or attach fewer files."
        )
    if todo and binaries() is None and push_status:
        push_status("Downloading ffmpeg for video frames…")
    for r in todo:
        if push_status:
            push_status(f"Extracting frames from {r.get('name') or 'video'}…")
        frames = extract_frames(conv_dir / str(r["path"]), limits.frames_per_video)
        r["frames"] = [{"path": f"attachments/{f.path.name}", "t_s": f.t_s} for f in frames]


def runtime_video_dict(row: dict[str, Any], conv_dir: Path) -> dict[str, Any]:
    return {
        "kind": "video",
        "name": row.get("name") or "video",
        "mime": row.get("mime") or "",
        "abs_path": str(conv_dir / str(row["path"])),
        "frames": [
            {"abs_path": str(conv_dir / str(f["path"])), "t_s": f.get("t_s", 0.0)}
            for f in row.get("frames") or []
            if isinstance(f, dict) and f.get("path")
        ],
    }
