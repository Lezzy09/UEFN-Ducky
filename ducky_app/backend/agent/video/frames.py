"""Extract evenly spaced JPEG frames from a video with ffmpeg (cached next to it)."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from backend.agent.video.ffmpeg_install import FfmpegInstallError, ensure_installed

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class VideoError(ValueError):
    """User-facing video failure (shown in the chat as an error)."""


@dataclass(frozen=True)
class Frame:
    path: Path
    t_s: float


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
    )


_runner = _run


def frame_times(duration_s: float, n: int) -> list[float]:
    if n <= 0:
        return []
    if duration_s <= 0:
        return [0.0]
    return [round(duration_s * (k + 0.5) / n, 3) for k in range(n)]


def frame_paths(video: Path, n: int) -> list[Path]:
    return [video.with_name(f"{video.name}.f{n:02d}-{k + 1:02d}.jpg") for k in range(n)]


def probe_duration(ffprobe: Path, video: Path, timeout_s: float = 15) -> float:
    args = [
        str(ffprobe), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(video),
    ]
    try:
        proc = _runner(args, timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise VideoError(f"Cannot read video {video.name!r}.") from exc
    try:
        if proc.returncode != 0:
            raise ValueError
        return float((proc.stdout or "").strip())
    except ValueError as exc:
        raise VideoError(f"Cannot read video {video.name!r}.") from exc


def extract_frames(
    video: Path, n: int, *, max_width: int = 1280, timeout_s: float = 60.0
) -> list[Frame]:
    try:
        ffmpeg, ffprobe = ensure_installed()
    except FfmpegInstallError as exc:
        raise VideoError(str(exc)) from exc
    deadline = time.monotonic() + timeout_s
    too_slow = f"Extracting frames from {video.name!r} took longer than {int(timeout_s)}s."
    times = frame_times(probe_duration(ffprobe, video), n)
    out: list[Frame] = []
    for t, path in zip(times, frame_paths(video, len(times))):
        if not path.is_file():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoError(too_slow)
            args = [
                str(ffmpeg), "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                "-frames:v", "1", "-vf", f"scale='min({max_width},iw)':-2", "-q:v", "3",
                "-y", str(path),
            ]
            try:
                proc = _runner(args, remaining)
            except subprocess.TimeoutExpired as exc:
                path.unlink(missing_ok=True)
                raise VideoError(too_slow) from exc
            if proc.returncode != 0 or not path.is_file():
                path.unlink(missing_ok=True)
                raise VideoError(f"Cannot read video {video.name!r}.")
        out.append(Frame(path=path, t_s=t))
    return out
