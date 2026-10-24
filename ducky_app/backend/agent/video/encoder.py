"""Pick the fastest H.264 encoder this PC's ffmpeg offers (hardware first, software last)."""

from __future__ import annotations

import re
import subprocess
import threading

from backend.agent.video import ffmpeg_install

PREFERRED = ("h264_nvenc", "h264_amf", "h264_qsv")
FALLBACK = "libx264"

_lock = threading.Lock()
_cached: str | None = None


def parse_encoders(output: str) -> set[str]:
    """Encoder names from ``ffmpeg -encoders`` text (flag column, name, description)."""
    names: set[str] = set()
    for line in output.splitlines():
        m = re.match(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def _probe() -> str:
    ffmpeg, _ = ffmpeg_install.ensure_installed()
    try:
        out = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return FALLBACK
    have = parse_encoders(out)
    return next((e for e in PREFERRED if e in have), FALLBACK)


def pick_encoder() -> str:
    """Best available H.264 encoder; ffmpeg is probed once and the answer cached."""
    global _cached
    with _lock:
        if _cached is None:
            _cached = _probe()
        return _cached


def reset_cache() -> None:
    global _cached
    with _lock:
        _cached = None
