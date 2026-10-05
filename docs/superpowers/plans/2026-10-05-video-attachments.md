# Video Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach videos to chat prompts; Gemini gets the video natively, every other model (and coding agents) gets timestamped frames extracted with an auto-downloaded ffmpeg.

**Architecture:** A new backend package `backend/agent/video/` owns limits, ffmpeg install, frame extraction, provider routing, staging and send-time preparation. The composer uploads a video once to a staging dir and keeps only a `staged_id`; at send time the video is copied into the conversation's `attachments/` folder and, if the recipient needs it, frames are extracted next to it. The shared builders in `backend/agent/multimodal_content.py` (used by every provider plugin) learn the `video` kind, so no plugin changes.

**Tech Stack:** Python 3 (pytest), ffmpeg/ffprobe (BtbN LGPL shared build, downloaded at runtime), React + TypeScript (vitest), existing `__panel_api` bridge and `panel_httpd` file routes.

**Spec:** `docs/superpowers/specs/2026-10-05-video-attachments-design.md`

## Global Constraints

- Settings defaults/ranges: `video_max_mb` 100 (10–200), `video_frames_per_video` 20 (1–40), `max_images_per_message` 40 (1–100); out-of-range values are clamped.
- Accepted video types: `video/mp4` (.mp4), `video/webm` (.webm), `video/quicktime` (.mov), `video/x-matroska` (.mkv).
- Gemini native only for mp4/webm/mov ≤ 20 MiB (`20 * 1024 * 1024`); `video/quicktime` is sent to Gemini as `video/mov`.
- Frames: evenly spaced at `duration * (k + 0.5) / n`, JPEG, max width 1280 px, 60 s total extraction timeout.
- ffmpeg pin: tag `autobuild-2026-08-31-13-27`, zip root `ffmpeg-n9.0.1-11-ge47273f4d9-win64-lgpl-shared-9.0`, SHA-256 `83a824f0729a69d143c9865125bb86988a11dd388325f0033711045522068aa0`. LGPL only; run as a separate process.
- ffmpeg lives in `%LOCALAPPDATA%\UEFN-Ducky\tools\ffmpeg\<version>\`; staging in `%LOCALAPPDATA%\UEFN-Ducky\video_staging\` (files > 24 h swept).
- No audio/transcription in this plan.
- Never silently drop a video: every failure surfaces an error to the user.
- UI copy in English (matches the app). Error strings from the backend in English.
- Commits: no `Co-Authored-By` trailer. Work on a dedicated branch `feat/video-attachments` (not `fix/listener-reload-loop`).
- Python tests: run from `UEFN-Ducky/` with `.venv/Scripts/python -m pytest <path> -q`. Frontend tests: from `UEFN-Ducky/ducky_app/frontend/ui_web/web/` with `npm test -- <file>`.

---

## File Structure

Create (backend, all under `UEFN-Ducky/ducky_app/backend/agent/video/`):
- `__init__.py` — package docstring only.
- `limits.py` — `VideoLimits`, `video_limits()`, clamp ranges/defaults.
- `ffmpeg_install.py` — pinned constants, download + SHA-256 verify + extract, status, background install, remove.
- `frames.py` — `Frame`, `VideoError`, `frame_times`, `frame_paths`, `probe_duration`, `extract_frames`.
- `routing.py` — `gemini_inline_mime`, `needs_frames`.
- `staging.py` — `normalize_video_mime`, `stage_video`, `resolve_staged`, `is_inside_app_data`.
- `send.py` — `prepare_video_frames`, `runtime_video_dict`.
- Tests next to them: `test_limits.py`, `test_ffmpeg_install.py`, `test_frames.py`, `test_routing_staging.py`, `test_send.py`.

Create (frontend):
- `ducky_app/frontend/ui_web/panel_api_video.py` — `PanelApiVideoMixin`.
- `ducky_app/frontend/ui_web/test_panel_api_video.py`.
- `ducky_app/frontend/ui_web/web/src/views/settings/VideosTab.tsx`.

Modify:
- `ducky_app/frontend/settings.py`, `ducky_app/frontend/settings_schema.py`
- `ducky_app/backend/agent/message_attachment.py`, `attachments.py`, `multimodal_content.py`, `runner.py`, `coding_agents/runner.py`
- `ducky_app/frontend/ui_web/conversation_attachments.py`, `panel_httpd.py`, `agent_modes.py`, `panel_api.py`
- `ducky_app/frontend/ui_web/web/src/types/panel.ts`, `hooks/useComposerAttachments.ts` (+ test), `components/ComposerAttachmentChips.tsx`, `components/AttachmentPreviewModal.tsx`, `components/ChatPane.tsx`, `components/EditableUserMessage.tsx`, `views/SettingsView.tsx`, the composer CSS file that defines `.composer-attachment-chip`
- `UEFN-Ducky/THIRD_PARTY_NOTICES.md`

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch from the current upstream base**

The working tree is on `fix/listener-reload-loop` with unrelated changes. Ask the user which base to branch from before running anything; default is `main`:

```bash
cd "C:/Users/PC/Documents/UEFN DUCKY APP et Plugin/UEFN-Ducky"
git stash push -u -m "wip listener-reload-loop"   # only if the user agrees
git switch -c feat/video-attachments main
```

---

### Task 1: Video settings + limits helper

**Files:**
- Create: `ducky_app/backend/agent/video/__init__.py`, `ducky_app/backend/agent/video/limits.py`
- Modify: `ducky_app/frontend/settings.py` (fields after `chat_title_model`, ~line 199; `_has_overrides`, ~line 456)
- Modify: `ducky_app/frontend/settings_schema.py` (new `FIELD_META` entries)
- Test: `ducky_app/backend/agent/video/test_limits.py`

**Interfaces:**
- Produces: `PanelSettings.video_max_mb: int = 100`, `PanelSettings.video_frames_per_video: int = 20`, `PanelSettings.max_images_per_message: int = 40`
- Produces: `limits.VideoLimits(max_bytes: int, frames_per_video: int, max_images_per_message: int)`, `limits.video_limits() -> VideoLimits`, `limits.clamp(value, lo: int, hi: int, default: int) -> int`, constants `VIDEO_MAX_MB_RANGE=(10, 200)`, `FRAMES_PER_VIDEO_RANGE=(1, 40)`, `MAX_IMAGES_PER_MESSAGE_RANGE=(1, 100)`, `DEFAULT_VIDEO_MAX_MB=100`, `DEFAULT_FRAMES_PER_VIDEO=20`, `DEFAULT_MAX_IMAGES_PER_MESSAGE=40`

- [ ] **Step 1: Write the failing test**

`ducky_app/backend/agent/video/test_limits.py`:

```python
from __future__ import annotations

from backend.agent.video.limits import clamp, video_limits
from frontend.settings import PanelSettings


def test_defaults_when_unset():
    lim = video_limits()
    assert lim.max_bytes == 100 * 1024 * 1024
    assert lim.frames_per_video == 20
    assert lim.max_images_per_message == 40


def test_values_are_read_from_settings_and_clamped():
    s = PanelSettings.load()
    s.video_max_mb = 999
    s.video_frames_per_video = 0
    s.max_images_per_message = 60
    s.save()
    lim = video_limits()
    assert lim.max_bytes == 200 * 1024 * 1024
    assert lim.frames_per_video == 1
    assert lim.max_images_per_message == 60


def test_clamp_bad_input_falls_back_to_default():
    assert clamp("nope", 1, 40, 20) == 20
    assert clamp(None, 1, 40, 20) == 20
    assert clamp("7", 1, 40, 20) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_limits.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.agent.video'`

- [ ] **Step 3: Implement**

`ducky_app/backend/agent/video/__init__.py`:

```python
"""Video chat attachments: limits, ffmpeg install, frame extraction, provider routing."""
```

`ducky_app/backend/agent/video/limits.py`:

```python
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
```

In `ducky_app/frontend/settings.py`, add after the `chat_title_model` field:

```python
    video_max_mb: int = 100
    """Largest video a chat message may carry (Settings → Videos, 10–200)."""

    video_frames_per_video: int = 20
    """Frames extracted per video for non-Gemini models (1–40)."""

    max_images_per_message: int = 40
    """Images per message, video frames included (1–100)."""
```

In `_has_overrides`, next to `or self.memory_index_max_chars != 2_500`, add:

```python
            or self.video_max_mb != 100
            or self.video_frames_per_video != 20
            or self.max_images_per_message != 40
```

In `ducky_app/frontend/settings_schema.py` `FIELD_META`, add:

```python
    "video_max_mb": FieldMeta(
        "Max video size (MB)", "Videos", settable=True,
        description="Largest video a chat message may carry (10–200).",
    ),
    "video_frames_per_video": FieldMeta(
        "Frames per video", "Videos", settable=True,
        description="Frames extracted per video for models without native video (1–40).",
    ),
    "max_images_per_message": FieldMeta(
        "Max images per message", "Videos", settable=True,
        description="Images per chat message, video frames included (1–100).",
    ),
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_limits.py ducky_app/frontend/test_settings_schema.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/video ducky_app/frontend/settings.py ducky_app/frontend/settings_schema.py
git commit -m "feat(video): add video limit settings"
```

---

### Task 2: ffmpeg auto-install

**Files:**
- Create: `ducky_app/backend/agent/video/ffmpeg_install.py`
- Test: `ducky_app/backend/agent/video/test_ffmpeg_install.py`

**Interfaces:**
- Produces: `FfmpegInstallError(RuntimeError)`; `binaries() -> tuple[Path, Path] | None` (ffmpeg, ffprobe); `status() -> dict` with keys `state` (`"missing"|"installing"|"ready"|"error"`), `progress` (float 0–1), `error` (str), `version` (str); `ensure_installed() -> tuple[Path, Path]` (blocking, raises `FfmpegInstallError`); `start_install() -> dict` (non-blocking, returns `status()`); `remove() -> dict`; module attribute `_urlopen` (monkeypatch hook); constants `FFMPEG_VERSION`, `FFMPEG_ZIP_ROOT`, `FFMPEG_URL`, `FFMPEG_SHA256`.

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/video/test_ffmpeg_install.py`:

```python
from __future__ import annotations

import hashlib
import io
import urllib.error
import zipfile

import pytest

from backend.agent.video import ffmpeg_install as fi


def _fake_zip(*, with_probe: bool = True) -> bytes:
    root = fi.FFMPEG_ZIP_ROOT
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{root}/bin/ffmpeg.exe", b"ffmpeg")
        if with_probe:
            zf.writestr(f"{root}/bin/ffprobe.exe", b"ffprobe")
        zf.writestr(f"{root}/bin/avcodec-63.dll", b"dll")
        zf.writestr(f"{root}/bin/ffplay.exe", b"skip me")
        zf.writestr(f"{root}/LICENSE.txt", b"LGPL")
        zf.writestr(f"{root}/doc/readme.html", b"skip me")
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _serve(monkeypatch, data: bytes, *, sha: str | None = None):
    monkeypatch.setattr(fi, "FFMPEG_SHA256", sha or hashlib.sha256(data).hexdigest())
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        return _Resp(data)

    monkeypatch.setattr(fi, "_urlopen", fake_urlopen)
    return calls


@pytest.fixture(autouse=True)
def _reset_state():
    fi._set(state="missing", progress=0.0, error="")
    yield


def test_install_extracts_only_needed_files(monkeypatch):
    _serve(monkeypatch, _fake_zip())
    ffmpeg, ffprobe = fi.ensure_installed()
    d = fi.install_dir()
    assert ffmpeg == d / "ffmpeg.exe" and ffprobe == d / "ffprobe.exe"
    assert sorted(p.name for p in d.iterdir()) == [
        ".installed", "LICENSE.txt", "avcodec-63.dll", "ffmpeg.exe", "ffprobe.exe",
    ]
    assert fi.status()["state"] == "ready"
    assert not list(fi.tools_root().glob("*.part"))


def test_second_call_does_not_download_again(monkeypatch):
    calls = _serve(monkeypatch, _fake_zip())
    fi.ensure_installed()
    fi.ensure_installed()
    assert len(calls) == 1


def test_checksum_mismatch_never_installs(monkeypatch):
    _serve(monkeypatch, _fake_zip(), sha="0" * 64)
    with pytest.raises(fi.FfmpegInstallError, match="corrupted"):
        fi.ensure_installed()
    assert fi.binaries() is None
    assert not fi.install_dir().exists()
    assert not list(fi.tools_root().glob("*.part"))
    st = fi.status()
    assert st["state"] == "error" and "corrupted" in st["error"]


def test_archive_without_ffprobe_is_rejected(monkeypatch):
    _serve(monkeypatch, _fake_zip(with_probe=False))
    with pytest.raises(fi.FfmpegInstallError, match="missing"):
        fi.ensure_installed()
    assert fi.binaries() is None


def test_404_says_update_the_app(monkeypatch):
    def gone(req, timeout=0):
        raise urllib.error.HTTPError(fi.FFMPEG_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr(fi, "_urlopen", gone)
    with pytest.raises(fi.FfmpegInstallError, match="update UEFN-Ducky"):
        fi.ensure_installed()


def test_offline_says_check_connection(monkeypatch):
    def offline(req, timeout=0):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(fi, "_urlopen", offline)
    with pytest.raises(fi.FfmpegInstallError, match="internet"):
        fi.ensure_installed()


def test_remove_deletes_install(monkeypatch):
    _serve(monkeypatch, _fake_zip())
    fi.ensure_installed()
    assert fi.remove()["state"] == "missing"
    assert fi.binaries() is None


def test_start_install_runs_in_background(monkeypatch):
    _serve(monkeypatch, _fake_zip())
    first = fi.start_install()
    assert first["state"] in ("installing", "ready")
    fi._thread.join(timeout=10)
    assert fi.status()["state"] == "ready"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_ffmpeg_install.py -q`
Expected: FAIL — `ImportError: cannot import name 'ffmpeg_install'`

- [ ] **Step 3: Implement**

`ducky_app/backend/agent/video/ffmpeg_install.py`:

```python
"""Download a pinned LGPL ffmpeg build into AppData on first need.

The archive is checked against a pinned SHA-256 before anything is extracted;
a mismatching or partial download is deleted and never executed. BtbN keeps
month-end autobuilds for ~2 years — bump the four constants together to update.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from frontend.app_paths import resolve_app_data_dir

FFMPEG_RELEASE_TAG = "autobuild-2026-08-31-13-27"
FFMPEG_VERSION = "n9.0.1-11-ge47273f4d9"
FFMPEG_ZIP_ROOT = "ffmpeg-n9.0.1-11-ge47273f4d9-win64-lgpl-shared-9.0"
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    f"{FFMPEG_RELEASE_TAG}/{FFMPEG_ZIP_ROOT}.zip"
)
FFMPEG_SHA256 = "83a824f0729a69d143c9865125bb86988a11dd388325f0033711045522068aa0"

_MARKER = ".installed"
_urlopen = urllib.request.urlopen

_lock = threading.Lock()  # guards _state / _thread
_install_lock = threading.Lock()  # one download at a time
_state: dict[str, Any] = {"state": "missing", "progress": 0.0, "error": ""}
_thread: threading.Thread | None = None


class FfmpegInstallError(RuntimeError):
    """User-facing install failure."""


def tools_root() -> Path:
    return resolve_app_data_dir() / "tools" / "ffmpeg"


def install_dir() -> Path:
    return tools_root() / FFMPEG_VERSION


def binaries() -> tuple[Path, Path] | None:
    d = install_dir()
    ffmpeg, ffprobe = d / "ffmpeg.exe", d / "ffprobe.exe"
    if (d / _MARKER).is_file() and ffmpeg.is_file() and ffprobe.is_file():
        return ffmpeg, ffprobe
    return None


def _set(**fields: Any) -> None:
    with _lock:
        _state.update(fields)


def status() -> dict[str, Any]:
    if binaries() is not None:
        return {"state": "ready", "progress": 1.0, "error": "", "version": FFMPEG_VERSION}
    with _lock:
        snap = dict(_state)
    if snap["state"] == "ready":  # removed from disk underneath us
        snap = {"state": "missing", "progress": 0.0, "error": ""}
    return {**snap, "version": FFMPEG_VERSION}


def _wanted_member(name: str) -> str | None:
    if name == f"{FFMPEG_ZIP_ROOT}/LICENSE.txt":
        return "LICENSE.txt"
    prefix = f"{FFMPEG_ZIP_ROOT}/bin/"
    if not name.startswith(prefix):
        return None
    leaf = name[len(prefix):]
    if not leaf or "/" in leaf:
        return None
    low = leaf.lower()
    if low in ("ffmpeg.exe", "ffprobe.exe") or low.endswith(".dll"):
        return leaf
    return None


def _download(dest: Path) -> None:
    req = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "UEFN-Ducky"})
    try:
        resp = _urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FfmpegInstallError(
                "The ffmpeg download is no longer available — update UEFN-Ducky."
            ) from exc
        raise FfmpegInstallError(f"ffmpeg download failed (HTTP {exc.code}).") from exc
    except OSError as exc:
        raise FfmpegInstallError("ffmpeg download failed — check your internet connection.") from exc
    sha = hashlib.sha256()
    with resp, dest.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if total:
                _set(progress=min(0.99, done / total))
    if sha.hexdigest() != FFMPEG_SHA256:
        dest.unlink(missing_ok=True)
        raise FfmpegInstallError("The ffmpeg download was corrupted (checksum mismatch).")


def _install_now() -> None:
    root = tools_root()
    root.mkdir(parents=True, exist_ok=True)
    part = root / f"{FFMPEG_VERSION}.zip.part"
    staging = root / f"{FFMPEG_VERSION}.tmp"
    try:
        _download(part)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        found: set[str] = set()
        try:
            with zipfile.ZipFile(part) as zf:
                for name in zf.namelist():
                    leaf = _wanted_member(name)
                    if leaf:
                        (staging / leaf).write_bytes(zf.read(name))
                        found.add(leaf.lower())
        except zipfile.BadZipFile as exc:
            raise FfmpegInstallError("The ffmpeg download was corrupted.") from exc
        if not {"ffmpeg.exe", "ffprobe.exe"} <= found:
            raise FfmpegInstallError("The ffmpeg archive is missing ffmpeg.exe or ffprobe.exe.")
        (staging / _MARKER).write_text(FFMPEG_VERSION, encoding="utf-8")
        final = install_dir()
        shutil.rmtree(final, ignore_errors=True)
        os.replace(staging, final)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def ensure_installed() -> tuple[Path, Path]:
    """Return (ffmpeg, ffprobe), downloading first if needed. Blocks."""
    found = binaries()
    if found:
        return found
    with _install_lock:
        found = binaries()
        if found:
            return found
        _set(state="installing", progress=0.0, error="")
        try:
            _install_now()
        except FfmpegInstallError as exc:
            _set(state="error", error=str(exc))
            raise
        except Exception as exc:
            msg = f"ffmpeg install failed: {exc}"
            _set(state="error", error=msg)
            raise FfmpegInstallError(msg) from exc
        _set(state="ready", progress=1.0, error="")
    found = binaries()
    if not found:
        raise FfmpegInstallError("ffmpeg install did not complete.")
    return found


def _background() -> None:
    try:
        ensure_installed()
    except FfmpegInstallError:
        pass  # surfaced through status()


def start_install() -> dict[str, Any]:
    """Kick off a background install if needed; return the current status."""
    global _thread
    if binaries() is not None:
        return status()
    with _lock:
        if _thread is None or not _thread.is_alive():
            _state.update(state="installing", progress=0.0, error="")
            _thread = threading.Thread(target=_background, name="ffmpeg-install", daemon=True)
            _thread.start()
    return status()


def remove() -> dict[str, Any]:
    with _install_lock:
        shutil.rmtree(tools_root(), ignore_errors=True)
        _set(state="missing", progress=0.0, error="")
    return status()
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_ffmpeg_install.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/video/ffmpeg_install.py ducky_app/backend/agent/video/test_ffmpeg_install.py
git commit -m "feat(video): download pinned LGPL ffmpeg on demand"
```

---

### Task 3: Frame extraction

**Files:**
- Create: `ducky_app/backend/agent/video/frames.py`
- Test: `ducky_app/backend/agent/video/test_frames.py`

**Interfaces:**
- Consumes: `ffmpeg_install.ensure_installed() -> (ffmpeg, ffprobe)`, `ffmpeg_install.FfmpegInstallError`
- Produces: `VideoError(ValueError)` (user-facing message); `Frame(path: Path, t_s: float)`; `frame_times(duration_s: float, n: int) -> list[float]`; `frame_paths(video: Path, n: int) -> list[Path]` (names `<video.name>.f<NN>-<KK>.jpg`); `probe_duration(ffprobe: Path, video: Path, timeout_s: float = 15) -> float`; `extract_frames(video: Path, n: int, *, max_width: int = 1280, timeout_s: float = 60.0) -> list[Frame]`; module attribute `_runner(args: list[str], timeout: float) -> subprocess.CompletedProcess` (monkeypatch hook).

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/video/test_frames.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from backend.agent.video import frames as fr
from backend.agent.video import ffmpeg_install as fi


def test_frame_times_are_centered_in_equal_slices():
    assert fr.frame_times(10.0, 4) == [1.25, 3.75, 6.25, 8.75]
    assert fr.frame_times(0.0, 5) == [0.0]
    assert fr.frame_times(3.0, 0) == []


def test_frame_paths_sit_next_to_video_and_encode_count(tmp_path):
    v = tmp_path / "1_0_bug.mp4"
    assert [p.name for p in fr.frame_paths(v, 2)] == ["1_0_bug.mp4.f02-01.jpg", "1_0_bug.mp4.f02-02.jpg"]


def _fake_tools(monkeypatch, tmp_path, *, probe_out="4.0", probe_rc=0, ff_rc=0, write=True, slow=False):
    ffmpeg, ffprobe = tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe"
    monkeypatch.setattr(fr, "ensure_installed", lambda: (ffmpeg, ffprobe))
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        if slow:
            raise subprocess.TimeoutExpired(args, timeout)
        if Path(args[0]) == ffprobe:
            return subprocess.CompletedProcess(args, probe_rc, stdout=probe_out, stderr="")
        if write and ff_rc == 0:
            Path(args[-1]).write_bytes(b"jpg")
        return subprocess.CompletedProcess(args, ff_rc, stdout="", stderr="boom")

    monkeypatch.setattr(fr, "_runner", runner)
    return calls


def test_extract_frames_runs_one_seek_per_frame(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    out = fr.extract_frames(video, 2)
    assert [f.t_s for f in out] == [1.0, 3.0]
    assert all(f.path.is_file() for f in out)
    ff_calls = [c for c in calls if Path(c[0]).name == "ffmpeg.exe"]
    assert len(ff_calls) == 2
    assert ff_calls[0][ff_calls[0].index("-ss") + 1] == "1.000"
    assert "scale='min(1280,iw)':-2" in ff_calls[0]


def test_existing_frames_are_reused(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    fr.extract_frames(video, 2)
    calls.clear()
    fr.extract_frames(video, 2)
    assert [Path(c[0]).name for c in calls] == ["ffprobe.exe"]


def test_unreadable_video(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, probe_rc=1, probe_out="")
    video = tmp_path / "broken.mp4"
    video.write_bytes(b"x")
    with pytest.raises(fr.VideoError, match="Cannot read video 'broken.mp4'"):
        fr.extract_frames(video, 3)


def test_timeout(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, slow=True)
    video = tmp_path / "long.mp4"
    video.write_bytes(b"x")
    with pytest.raises(fr.VideoError, match="took longer than 60s"):
        fr.extract_frames(video, 3)


def test_install_failure_becomes_video_error(monkeypatch, tmp_path):
    def boom():
        raise fi.FfmpegInstallError("ffmpeg download failed — check your internet connection.")

    monkeypatch.setattr(fr, "ensure_installed", boom)
    with pytest.raises(fr.VideoError, match="internet"):
        fr.extract_frames(tmp_path / "x.mp4", 2)


_REAL = os.environ.get("DUCKY_FFMPEG_DIR", "")


@pytest.mark.skipif(not _REAL, reason="set DUCKY_FFMPEG_DIR to a folder with ffmpeg.exe + ffprobe.exe")
def test_real_ffmpeg_extracts_frames(monkeypatch, tmp_path):
    ffmpeg, ffprobe = Path(_REAL) / "ffmpeg.exe", Path(_REAL) / "ffprobe.exe"
    monkeypatch.setattr(fr, "ensure_installed", lambda: (ffmpeg, ffprobe))
    video = tmp_path / "test.mp4"
    subprocess.run(
        [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10", "-y", str(video)],
        check=True,
    )
    out = fr.extract_frames(video, 4)
    assert [f.t_s for f in out] == [0.375, 1.125, 1.875, 2.625]
    assert all(f.path.stat().st_size > 0 for f in out)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_frames.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement**

`ducky_app/backend/agent/video/frames.py`:

```python
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
```

- [ ] **Step 4: Run tests (plus the real-ffmpeg check)**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_frames.py -q`
Expected: PASS (real test skipped)

Then with a real ffmpeg (download once into a scratch folder using the pinned URL, extract `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `bin/*.dll`):
Run: `DUCKY_FFMPEG_DIR=<that folder> .venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_frames.py -q -k real`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/video/frames.py ducky_app/backend/agent/video/test_frames.py
git commit -m "feat(video): extract timestamped frames with ffmpeg"
```

---

### Task 4: Routing + staging

**Files:**
- Create: `ducky_app/backend/agent/video/routing.py`, `ducky_app/backend/agent/video/staging.py`
- Test: `ducky_app/backend/agent/video/test_routing_staging.py`

**Interfaces:**
- Consumes: `limits.video_limits()`, `frames.VideoError`
- Produces (routing): `GEMINI_PROVIDER = "gemini"`, `GEMINI_INLINE_MAX_BYTES = 20 * 1024 * 1024`, `gemini_inline_mime(mime: str, size_bytes: int) -> str | None`, `needs_frames(mime: str, size_bytes: int, *, provider: str, external: bool) -> bool`
- Produces (staging): `VIDEO_MIME_EXT: dict[str, str]`, `normalize_video_mime(mime: str, name: str) -> str | None`, `staging_dir(create: bool = False) -> Path`, `stage_video(name: str, mime: str, data_base64: str) -> dict` (keys `staged_id`, `size_bytes`, `mime`), `resolve_staged(staged_id: str) -> Path`, `is_inside_app_data(path: str | Path) -> Path | None`

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/video/test_routing_staging.py`:

```python
from __future__ import annotations

import base64
import os
import time

import pytest

from backend.agent.video import staging
from backend.agent.video.frames import VideoError
from backend.agent.video.routing import gemini_inline_mime, needs_frames

MB = 1024 * 1024


def test_gemini_inline_only_small_supported_types():
    assert gemini_inline_mime("video/mp4", 5 * MB) == "video/mp4"
    assert gemini_inline_mime("video/quicktime", 5 * MB) == "video/mov"
    assert gemini_inline_mime("video/x-matroska", 5 * MB) is None
    assert gemini_inline_mime("video/mp4", 21 * MB) is None


def test_needs_frames_rules():
    assert needs_frames("video/mp4", MB, provider="gemini", external=False) is False
    assert needs_frames("video/mp4", MB, provider="GEMINI", external=False) is False
    assert needs_frames("video/mp4", MB, provider="anthropic", external=False) is True
    assert needs_frames("video/mp4", MB, provider="gemini", external=True) is True
    assert needs_frames("video/mp4", 30 * MB, provider="gemini", external=False) is True


def test_normalize_mime_falls_back_to_extension():
    assert staging.normalize_video_mime("", "clip.MKV") == "video/x-matroska"
    assert staging.normalize_video_mime("video/mp4", "x") == "video/mp4"
    assert staging.normalize_video_mime("video/avi", "x.avi") is None


def test_stage_and_resolve_roundtrip():
    data = b"\x00" * 1024
    out = staging.stage_video("bug.mp4", "video/mp4", "data:video/mp4;base64," + base64.b64encode(data).decode())
    assert out["size_bytes"] == 1024 and out["mime"] == "video/mp4"
    path = staging.resolve_staged(out["staged_id"])
    assert path.read_bytes() == data and path.suffix == ".mp4"


def test_stage_rejects_unsupported_and_too_big(monkeypatch):
    with pytest.raises(VideoError, match="Unsupported video format"):
        staging.stage_video("a.avi", "video/avi", base64.b64encode(b"x").decode())
    from backend.agent.video import limits

    monkeypatch.setattr(staging, "video_limits", lambda: limits.VideoLimits(10, 20, 40))
    with pytest.raises(VideoError, match="exceeds the 0MB video limit|exceeds"):
        staging.stage_video("a.mp4", "video/mp4", base64.b64encode(b"x" * 11).decode())


def test_resolve_rejects_bad_ids():
    for bad in ["../x.mp4", "abc.mp4", "0" * 32 + ".exe", ""]:
        with pytest.raises(VideoError):
            staging.resolve_staged(bad)


def test_old_staged_files_are_swept():
    old = staging.staging_dir(create=True) / ("a" * 32 + ".mp4")
    old.write_bytes(b"x")
    past = time.time() - 2 * 24 * 3600
    os.utime(old, (past, past))
    staging.stage_video("b.mp4", "video/mp4", base64.b64encode(b"y").decode())
    assert not old.exists()


def test_is_inside_app_data(tmp_path):
    inside = staging.staging_dir(create=True) / "x.mp4"
    inside.write_bytes(b"x")
    assert staging.is_inside_app_data(inside) == inside.resolve()
    outside = tmp_path.parent / "elsewhere.mp4"
    assert staging.is_inside_app_data(outside) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_routing_staging.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement**

`ducky_app/backend/agent/video/routing.py`:

```python
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
```

`ducky_app/backend/agent/video/staging.py`:

```python
"""Composer uploads land here once; the composer keeps only the staged id."""

from __future__ import annotations

import base64
import re
import time
import uuid
from pathlib import Path
from typing import Any

from backend.agent.video.frames import VideoError
from backend.agent.video.limits import video_limits
from frontend.app_paths import resolve_app_data_dir

VIDEO_MIME_EXT = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}
_EXT_MIME = {ext: mime for mime, ext in VIDEO_MIME_EXT.items()}
_STAGED_RE = re.compile(r"^[0-9a-f]{32}\.(?:mp4|webm|mov|mkv)$")
_DATA_URL_RE = re.compile(r"^data:[^;]*;base64,")
_MAX_AGE_S = 24 * 3600


def normalize_video_mime(mime: str, name: str) -> str | None:
    m = (mime or "").strip().lower()
    if m in VIDEO_MIME_EXT:
        return m
    return _EXT_MIME.get(Path(name or "").suffix.lower())


def staging_dir(create: bool = False) -> Path:
    path = resolve_app_data_dir(for_write=create) / "video_staging"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _sweep(root: Path) -> None:
    cutoff = time.time() - _MAX_AGE_S
    for p in root.glob("*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def stage_video(name: str, mime: str, data_base64: str) -> dict[str, Any]:
    norm = normalize_video_mime(mime, name)
    if norm is None:
        raise VideoError(f"Unsupported video format for {name!r} — use MP4, WebM, MOV or MKV.")
    try:
        raw = base64.b64decode(_DATA_URL_RE.sub("", (data_base64 or "").strip()), validate=True)
    except Exception as exc:
        raise VideoError(f"Could not read video {name!r}.") from exc
    limit = video_limits().max_bytes
    if len(raw) > limit:
        raise VideoError(f"Video {name!r} exceeds the {limit // (1024 * 1024)}MB video limit.")
    root = staging_dir(create=True)
    _sweep(root)
    staged_id = uuid.uuid4().hex + VIDEO_MIME_EXT[norm]
    (root / staged_id).write_bytes(raw)
    return {"staged_id": staged_id, "size_bytes": len(raw), "mime": norm}


def resolve_staged(staged_id: str) -> Path:
    sid = (staged_id or "").strip()
    path = staging_dir() / sid
    if not _STAGED_RE.fullmatch(sid) or not path.is_file():
        raise VideoError("The video upload expired — attach the video again.")
    return path


def is_inside_app_data(path: str | Path) -> Path | None:
    try:
        target = Path(path).resolve()
        target.relative_to(resolve_app_data_dir().resolve())
    except (OSError, ValueError):
        return None
    return target
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_routing_staging.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/video/routing.py ducky_app/backend/agent/video/staging.py ducky_app/backend/agent/video/test_routing_staging.py
git commit -m "feat(video): stage composer uploads and route per provider"
```

---

### Task 5: `video` attachment kind (parse, persist, hydrate)

**Files:**
- Modify: `ducky_app/backend/agent/message_attachment.py`
- Modify: `ducky_app/backend/agent/attachments.py` (`parse_attachment_dict`, `parse_attachment_dicts`, `prepare_outgoing_user_message`)
- Modify: `ducky_app/backend/agent/multimodal_content.py` (add `media_attachments` only — builders change in Task 7)
- Modify: `ducky_app/frontend/ui_web/conversation_attachments.py` (`_CHAT_FILE_RE`, `persist_message_attachments`, `hydrate_attachment_dict`)
- Test: `ducky_app/backend/agent/test_video_attachments.py`

**Interfaces:**
- Consumes: `staging.resolve_staged`, `staging.is_inside_app_data`, `staging.normalize_video_mime`, `staging.VIDEO_MIME_EXT`, `limits.video_limits`
- Produces: `MessageAttachment` gains `file_path: str = ""`, `size_bytes: int = 0`, `frames: list[tuple[str, float]]` (abs path, seconds). Raw video dicts accepted by `parse_attachment_dict`: `{"kind": "video", "name", "mime", "staged_id"}` **or** `{"kind": "video", "name", "mime", "abs_path", "frames": [{"abs_path", "t_s"}]}`. Persisted row: `{"kind": "video", "name", "mime", "path": "attachments/<file>", "size_bytes"}` (+ `"frames": [{"path", "t_s"}]` added later by Task 6). Hydrated row adds `abs_path`, `media_url`, and per frame `abs_path` + `media_url`. `multimodal_content.media_attachments(atts) -> list[MessageAttachment]`.

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/test_video_attachments.py`:

```python
from __future__ import annotations

import base64

import pytest

from backend.agent.attachments import parse_attachment_dict, parse_attachment_dicts
from backend.agent.multimodal_content import media_attachments
from backend.agent.video import staging
from frontend.ui_web.conversation_attachments import (
    hydrate_attachment_dict,
    persist_message_attachments,
)

_PNG = base64.b64encode(b"\x89PNG\r\n").decode()


def _staged(data: bytes = b"vid", name: str = "bug.mp4") -> dict:
    out = staging.stage_video(name, "video/mp4", base64.b64encode(data).decode())
    return {"kind": "video", "name": name, "mime": "video/mp4", "staged_id": out["staged_id"]}


def test_parse_staged_video():
    att = parse_attachment_dict(_staged())
    assert att.kind == "video" and att.size_bytes == 3
    assert att.file_path.endswith(".mp4")
    assert media_attachments([att]) == [att]


def test_parse_rejects_path_outside_app_data(tmp_path):
    outside = tmp_path.parent / "secret.mp4"
    outside.write_bytes(b"x")
    assert parse_attachment_dict({"kind": "video", "name": "s.mp4", "abs_path": str(outside)}) is None


def test_expired_stage_is_an_error():
    with pytest.raises(ValueError, match="expired"):
        parse_attachment_dict({"kind": "video", "name": "x.mp4", "staged_id": "f" * 32 + ".mp4"})


def test_image_cap_comes_from_settings():
    from frontend.settings import PanelSettings

    s = PanelSettings.load()
    s.max_images_per_message = 2
    s.save()
    imgs = [{"kind": "image", "name": f"{i}.png", "data_base64": _PNG} for i in range(3)]
    with pytest.raises(ValueError, match="At most 2 images"):
        parse_attachment_dicts(imgs)


def test_persist_copies_video_and_hydrate_never_inlines_it(tmp_path):
    att = parse_attachment_dict(_staged(b"0123456789", "my clip.mp4"))
    rows = persist_message_attachments("conv1", 1.5, [att], tmp_path)
    assert rows == [{
        "kind": "video", "name": "my clip.mp4", "mime": "video/mp4",
        "path": "attachments/1500_0_my_clip.mp4", "size_bytes": 10,
    }]
    stored = tmp_path / "conv1" / rows[0]["path"]
    assert stored.read_bytes() == b"0123456789"
    frame = stored.with_name(stored.name + ".f01-01.jpg")
    frame.write_bytes(b"jpg")
    row = {**rows[0], "frames": [{"path": f"attachments/{frame.name}", "t_s": 0.5}]}
    hyd = hydrate_attachment_dict(row, "conv1", tmp_path)
    assert "data_base64" not in hyd
    assert hyd["abs_path"] == str(stored)
    assert hyd["media_url"].endswith("/chat-attachments/conv1/1500_0_my_clip.mp4")
    assert hyd["frames"][0]["abs_path"] == str(frame)
    assert hyd["frames"][0]["media_url"].endswith(f"/chat-attachments/conv1/{frame.name}")


def test_persist_adds_extension_when_name_has_none(tmp_path):
    raw = _staged(b"x", "blob")
    raw["name"] = "blob"
    att = parse_attachment_dict(raw)
    rows = persist_message_attachments("c", 1.0, [att], tmp_path)
    assert rows[0]["path"].endswith("_blob.mp4")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/test_video_attachments.py -q`
Expected: FAIL — `ImportError: cannot import name 'media_attachments'`

- [ ] **Step 3: Implement**

`ducky_app/backend/agent/message_attachment.py` — replace the dataclass:

```python
"""Shared attachment dataclass for chat multimodal messages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MessageAttachment:
    kind: str  # image | file | video
    name: str
    mime: str = ""
    data_base64: str = ""
    text: str = ""
    # video only: absolute source file, its size, and extracted (abs path, seconds) frames
    file_path: str = ""
    size_bytes: int = 0
    frames: list[tuple[str, float]] = field(default_factory=list)
```

`ducky_app/backend/agent/multimodal_content.py` — add below `image_attachments`:

```python
def media_attachments(attachments: list[MessageAttachment]) -> list[MessageAttachment]:
    """Images with pixels plus videos with a file on disk — what providers can see."""
    return [
        a
        for a in attachments
        if (a.kind == "image" and a.data_base64) or (a.kind == "video" and a.file_path)
    ]
```

`ducky_app/backend/agent/attachments.py`:
- Delete `_MAX_IMAGES = 20`.
- Change the import to `from backend.agent.multimodal_content import media_attachments`.
- Add a `kind == "video"` branch at the end of `parse_attachment_dict` (before `return None`), using this helper:

```python
def _parse_video(raw: dict[str, Any], name: str, mime: str) -> MessageAttachment | None:
    from backend.agent.video.limits import video_limits
    from backend.agent.video.staging import is_inside_app_data, normalize_video_mime, resolve_staged

    staged_id = str(raw.get("staged_id") or "").strip()
    if staged_id:
        path = resolve_staged(staged_id)
    else:
        path = is_inside_app_data(str(raw.get("abs_path") or "").strip() or ".")
        if path is None or not path.is_file():
            return None
    size = path.stat().st_size
    limit = video_limits().max_bytes
    if size > limit:
        raise ValueError(f"Video {name!r} exceeds the {limit // (1024 * 1024)}MB video limit")
    frames: list[tuple[str, float]] = []
    for fr in raw.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        fp = is_inside_app_data(str(fr.get("abs_path") or "").strip() or ".")
        if fp is not None and fp.is_file():
            frames.append((str(fp), float(fr.get("t_s") or 0.0)))
    return MessageAttachment(
        kind="video",
        name=name,
        mime=normalize_video_mime(mime, name) or normalize_video_mime("", path.name) or "video/mp4",
        file_path=str(path),
        size_bytes=size,
        frames=frames,
    )
```

```python
    if kind == "video":
        return _parse_video(raw, name, mime)
```

- In `parse_attachment_dicts`, replace `_MAX_IMAGES` with the setting:

```python
    from backend.agent.video.limits import video_limits

    max_images = video_limits().max_images_per_message
    out: list[MessageAttachment] = []
    image_count = 0
    for raw in raw_list:
        att = parse_attachment_dict(raw if isinstance(raw, dict) else {})
        if not att:
            continue
        if att.kind == "image":
            image_count += 1
            if image_count > max_images:
                raise ValueError(f"At most {max_images} images per message")
        out.append(att)
    return out
```

- In `prepare_outgoing_user_message`: replace `images = image_attachments(attachments)` with `images = media_attachments(attachments)` (the error text stays; videos need a vision model too), and in the `stored` loop add:

```python
        elif a.kind == "video":
            stored.append({"kind": "video", "name": a.name, "mime": a.mime, "size_bytes": a.size_bytes})
```

`ducky_app/frontend/ui_web/conversation_attachments.py`:
- `_CHAT_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+\.(?:png|jpe?g|webp|mp4|webm|mov|mkv)$", re.IGNORECASE)`
- Add `import shutil` at the top.
- In `persist_message_attachments`, add a branch after the `image` branch:

```python
        elif att.kind == "video" and att.file_path:
            from backend.agent.video.staging import VIDEO_MIME_EXT

            ext = VIDEO_MIME_EXT.get(att.mime, ".mp4")
            if Path(filename).suffix.lower() not in VIDEO_MIME_EXT.values():
                filename += ext
                rel = f"attachments/{filename}"
                full = conv_path / rel
            try:
                shutil.copyfile(att.file_path, full)
            except OSError:
                continue
            out.append(
                {
                    "kind": "video",
                    "name": att.name,
                    "mime": att.mime,
                    "path": rel,
                    "size_bytes": att.size_bytes,
                }
            )
```

- In `hydrate_attachment_dict`, before the final `return raw`:

```python
    if kind == "video":
        conv_path = conversation_dir(conv_id, None, conversations_dir)
        frames = []
        for fr in raw.get("frames") or []:
            if not isinstance(fr, dict) or not fr.get("path"):
                continue
            fp = conv_path / str(fr["path"])
            frames.append(
                {
                    **fr,
                    "abs_path": str(fp),
                    "media_url": build_chat_attachment_url(conv_id, fp.name),
                }
            )
        return {
            **raw,
            "abs_path": str(full),
            "media_url": build_chat_attachment_url(conv_id, full.name),
            "frames": frames,
        }
```

- [ ] **Step 4: Run tests (new + existing attachment tests)**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/test_video_attachments.py ducky_app/backend/agent/coding_agents/test_image_forwarding.py ducky_app/frontend/ui_web -q -k "attach or image or video"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/message_attachment.py ducky_app/backend/agent/attachments.py ducky_app/backend/agent/multimodal_content.py ducky_app/frontend/ui_web/conversation_attachments.py ducky_app/backend/agent/test_video_attachments.py
git commit -m "feat(video): add video attachment kind with staging, persist and hydrate"
```

---

### Task 6: Send-time frame preparation + wiring into the chat run

**Files:**
- Create: `ducky_app/backend/agent/video/send.py`
- Modify: `ducky_app/frontend/ui_web/agent_modes.py` (~lines 874, 885, 1572–1600)
- Modify: `ducky_app/backend/agent/runner.py` (~line 557)
- Modify: `ducky_app/backend/agent/coding_agents/runner.py` (`collect_image_paths`, ~line 259)
- Test: `ducky_app/backend/agent/video/test_send.py`

**Interfaces:**
- Consumes: `routing.needs_frames`, `frames.extract_frames`, `frames.VideoError`, `ffmpeg_install.binaries`, `limits.video_limits`, `multimodal_content.media_attachments`
- Produces: `prepare_video_frames(stored: list[dict], *, conv_dir: Path, provider: str, external: bool, push_status: Callable[[str], None] | None = None) -> None` (mutates video rows, adding `"frames": [{"path": "attachments/<jpg>", "t_s"}]`; raises `VideoError`); `runtime_video_dict(row: dict, conv_dir: Path) -> dict` (`{"kind": "video", "name", "mime", "abs_path", "frames": [{"abs_path", "t_s"}]}`)

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/video/test_send.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent.video import send
from backend.agent.video.frames import Frame, VideoError


def _setup(tmp_path, monkeypatch):
    conv_dir = tmp_path / "conv1"
    (conv_dir / "attachments").mkdir(parents=True)
    video = conv_dir / "attachments" / "1_0_bug.mp4"
    video.write_bytes(b"v")
    calls = []

    def fake_extract(path, n):
        calls.append((path, n))
        out = []
        for k in range(n):
            p = path.with_name(f"{path.name}.f{n:02d}-{k + 1:02d}.jpg")
            p.write_bytes(b"j")
            out.append(Frame(p, float(k)))
        return out

    monkeypatch.setattr(send, "extract_frames", fake_extract)
    row = {"kind": "video", "name": "bug.mp4", "mime": "video/mp4", "path": "attachments/1_0_bug.mp4", "size_bytes": 1}
    return conv_dir, row, calls


def test_frames_added_for_non_gemini(tmp_path, monkeypatch):
    conv_dir, row, calls = _setup(tmp_path, monkeypatch)
    statuses = []
    send.prepare_video_frames([row], conv_dir=conv_dir, provider="anthropic", external=False, push_status=statuses.append)
    assert calls and calls[0][1] == 20
    assert row["frames"][0] == {"path": "attachments/1_0_bug.mp4.f20-01.jpg", "t_s": 0.0}
    assert any("Extracting frames" in s for s in statuses)


def test_gemini_small_mp4_gets_no_frames(tmp_path, monkeypatch):
    conv_dir, row, calls = _setup(tmp_path, monkeypatch)
    send.prepare_video_frames([row], conv_dir=conv_dir, provider="gemini", external=False)
    assert calls == [] and "frames" not in row


def test_image_cap_counts_frames(tmp_path, monkeypatch):
    conv_dir, row, _ = _setup(tmp_path, monkeypatch)
    images = [{"kind": "image", "path": "attachments/x.png"}] * 25
    with pytest.raises(VideoError, match="Too many images"):
        send.prepare_video_frames([row, *images], conv_dir=conv_dir, provider="openai", external=False)


def test_runtime_dict_uses_absolute_paths(tmp_path, monkeypatch):
    conv_dir, row, _ = _setup(tmp_path, monkeypatch)
    row["frames"] = [{"path": "attachments/f.jpg", "t_s": 1.5}]
    out = send.runtime_video_dict(row, conv_dir)
    assert out == {
        "kind": "video", "name": "bug.mp4", "mime": "video/mp4",
        "abs_path": str(conv_dir / "attachments/1_0_bug.mp4"),
        "frames": [{"abs_path": str(conv_dir / "attachments/f.jpg"), "t_s": 1.5}],
    }


def test_collect_image_paths_includes_video_frames(tmp_path, monkeypatch):
    from backend.agent.coding_agents import runner as ca

    conv_dir = tmp_path / "convs" / "c1"
    (conv_dir / "attachments").mkdir(parents=True)
    (conv_dir / "attachments" / "f1.jpg").write_bytes(b"j")
    monkeypatch.setattr("frontend.ui_web.project_chats.get_conversations_dir", lambda root=None: tmp_path / "convs")
    conv = SimpleNamespace(id="c1", messages=[{"role": "user", "attachments": [
        {"kind": "video", "path": "attachments/v.mp4", "frames": [{"path": "attachments/f1.jpg", "t_s": 0.5}]},
    ]}])
    assert ca.collect_image_paths(conv) == [str((conv_dir / "attachments" / "f1.jpg").resolve())]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video/test_send.py -q`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `send.py`**

`ducky_app/backend/agent/video/send.py`:

```python
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
```

- [ ] **Step 4: Update `collect_image_paths`**

In `ducky_app/backend/agent/coding_agents/runner.py`, replace the loop body of `collect_image_paths`:

```python
    for att in attachments:
        if not isinstance(att, dict):
            continue
        if att.get("kind") == "image":
            rels = [att.get("path")]
        elif att.get("kind") == "video":
            rels = [f.get("path") for f in att.get("frames") or [] if isinstance(f, dict)]
        else:
            continue
        for rel in rels:
            rel = str(rel or "").strip()
            if not rel:
                continue
            full = (conv_dir / rel).resolve()
            if full.is_file():
                out.append(str(full))
    return out
```

Update its docstring first line to: `"""Absolute paths of images (and video frames) on the chat's latest user message.`

- [ ] **Step 5: Wire into `agent_modes.py`**

In the import at the top, change `image_attachments` usages: replace the two calls at ~874 and ~885 (`attachments=image_attachments(` and `current_images = image_attachments(parse_attachment_dicts(user_attachments))`) with `media_attachments(...)`, and import it next to `image_attachments` (`from backend.agent.multimodal_content import media_attachments`; keep `image_attachments` only if still used elsewhere in the file).

Replace the block from `stored_attachments = persist_message_attachments(` through the `current_user_attachments = [...]` list (~1578–1593) with:

```python
        conversations_dir = get_conversations_dir(settings.uefn_project_root)
        stored_attachments = persist_message_attachments(
            conv_id,
            ts,
            attachments_parsed,
            conversations_dir,
            settings.uefn_project_root,
        )
        conv_dir_path = conversations_dir / conv_id
        if any(r.get("kind") == "video" for r in stored_attachments):
            from backend.agent.video.send import prepare_video_frames, runtime_video_dict

            try:
                prepare_video_frames(
                    stored_attachments,
                    conv_dir=conv_dir_path,
                    provider=provider_name or "",
                    external=external,
                    push_status=lambda text: push({"type": "status", "text": text, "conv_id": conv_id}),
                )
            except ValueError as e:
                push({"type": "error", "text": str(e), "conv_id": conv_id})
                return ""
            if external:
                hints = [
                    f"Video file: {conv_dir_path / r['path']}"
                    for r in stored_attachments
                    if r.get("kind") == "video"
                ]
                content = (content + "\n\n" if content else "") + "\n".join(hints)
        current_user_attachments = [
            {
                "kind": a.kind,
                "name": a.name,
                "mime": a.mime,
                **({"data_base64": a.data_base64} if a.kind == "image" else {"text": a.text}),
            }
            for a in attachments_parsed
            if a.kind != "video"
        ] + [
            runtime_video_dict(r, conv_dir_path)
            for r in stored_attachments
            if r.get("kind") == "video"
        ]
```

Note: `runtime_video_dict` is imported inside the `if`; move the import above the `if` (unconditional `from backend.agent.video.send import prepare_video_frames, runtime_video_dict`) so the list comprehension always has it.

In `ducky_app/backend/agent/runner.py` ~line 557, replace `attachments=image_attachments(` with `attachments=media_attachments(` and update the import on line ~11 (`from backend.agent.multimodal_content import image_attachments` → add `media_attachments`).

- [ ] **Step 6: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/video ducky_app/backend/agent/coding_agents/test_image_forwarding.py ducky_app/backend/agent/test_video_attachments.py -q`
Expected: PASS

Run the broader suites touched: `.venv/Scripts/python -m pytest ducky_app/frontend/ui_web ducky_app/backend/agent -q -x`
Expected: PASS (same failures as before the change, if any — compare against `git stash` baseline when something unrelated fails)

- [ ] **Step 7: Commit**

```bash
git add ducky_app/backend/agent/video/send.py ducky_app/backend/agent/video/test_send.py ducky_app/frontend/ui_web/agent_modes.py ducky_app/backend/agent/runner.py ducky_app/backend/agent/coding_agents/runner.py
git commit -m "feat(video): extract frames at send time and forward to agents"
```

---

### Task 7: Provider builders understand videos

**Files:**
- Modify: `ducky_app/backend/agent/multimodal_content.py`
- Test: `ducky_app/backend/agent/test_multimodal_video.py`

**Interfaces:**
- Consumes: `MessageAttachment.file_path/size_bytes/frames`, `routing.gemini_inline_mime`
- Produces: `build_anthropic_user_content`, `build_openai_user_content`, `build_gemini_user_parts` accept video attachments (signatures unchanged). Frame label format: `Video "<name>" — frame <k>/<n> at MM:SS`. Missing frames → text `[Video "<name>" attached but could not be analyzed]`.

- [ ] **Step 1: Write the failing tests**

`ducky_app/backend/agent/test_multimodal_video.py`:

```python
from __future__ import annotations

import base64
import sys
import types as pytypes

from backend.agent.message_attachment import MessageAttachment
from backend.agent.multimodal_content import (
    build_anthropic_user_content,
    build_gemini_user_parts,
    build_openai_user_content,
)


def _video(tmp_path, *, frames=2, mime="video/mp4", size=10):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"VIDEO")
    fr = []
    for k in range(frames):
        p = tmp_path / f"f{k}.jpg"
        p.write_bytes(f"J{k}".encode())
        fr.append((str(p), 65.0 * k))
    return MessageAttachment(kind="video", name="bug.mp4", mime=mime, file_path=str(v), size_bytes=size, frames=fr)


def test_anthropic_gets_labelled_frames(tmp_path):
    blocks = build_anthropic_user_content("look", [_video(tmp_path)])
    assert blocks[0] == {"type": "text", "text": "look"}
    assert blocks[1] == {"type": "text", "text": 'Video "bug.mp4" — frame 1/2 at 00:00'}
    assert blocks[2]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"J0").decode()}
    assert blocks[3]["text"] == 'Video "bug.mp4" — frame 2/2 at 01:05'


def test_openai_gets_labelled_frames(tmp_path):
    parts = build_openai_user_content("", [_video(tmp_path, frames=1)])
    assert parts[0] == {"type": "text", "text": 'Video "bug.mp4" — frame 1/1 at 00:00'}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(b"J0").decode()


def test_video_without_frames_becomes_a_note(tmp_path):
    blocks = build_anthropic_user_content("x", [_video(tmp_path, frames=0)])
    assert blocks[-1] == {"type": "text", "text": '[Video "bug.mp4" attached but could not be analyzed]'}


def _fake_genai(monkeypatch):
    class Part:
        def __init__(self, **kw):
            self.kw = kw

        @staticmethod
        def from_text(text):
            return Part(text=text)

        @staticmethod
        def from_bytes(data, mime_type):
            return Part(data=data, mime_type=mime_type)

    types_mod = pytypes.SimpleNamespace(Part=Part)
    genai = pytypes.ModuleType("google.genai")
    genai.types = types_mod
    google = pytypes.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


def test_gemini_small_video_goes_native(tmp_path, monkeypatch):
    _fake_genai(monkeypatch)
    parts = build_gemini_user_parts("q", [_video(tmp_path, mime="video/quicktime")])
    assert parts[1].kw == {"data": b"VIDEO", "mime_type": "video/mov"}
    assert len(parts) == 2


def test_gemini_big_video_falls_back_to_frames(tmp_path, monkeypatch):
    _fake_genai(monkeypatch)
    parts = build_gemini_user_parts("q", [_video(tmp_path, size=50 * 1024 * 1024)])
    assert parts[1].kw == {"text": 'Video "bug.mp4" — frame 1/2 at 00:00'}
    assert parts[2].kw == {"data": b"J0", "mime_type": "image/jpeg"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/test_multimodal_video.py -q`
Expected: FAIL (videos ignored → assertion errors)

- [ ] **Step 3: Implement**

Replace the three builders in `ducky_app/backend/agent/multimodal_content.py` (keep `image_attachments` and `media_attachments`) and add helpers; add `from pathlib import Path` to imports:

```python
def _mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def _video_frames(att: MessageAttachment) -> list[tuple[str, bytes]]:
    """(label, jpeg bytes) per readable frame."""
    out: list[tuple[str, bytes]] = []
    n = len(att.frames)
    for k, (path, t_s) in enumerate(att.frames, 1):
        try:
            raw = Path(path).read_bytes()
        except OSError:
            continue
        out.append((f'Video "{att.name}" — frame {k}/{n} at {_mmss(t_s)}', raw))
    return out


def _video_note(att: MessageAttachment) -> str:
    return f'[Video "{att.name}" attached but could not be analyzed]'


def build_anthropic_user_content(text: str, attachments: list[MessageAttachment]) -> str | list[dict[str, Any]]:
    media = media_attachments(attachments)
    if not media:
        return text
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for att in media:
        if att.kind == "image":
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": att.mime or "image/png", "data": att.data_base64},
                }
            )
            continue
        frames = _video_frames(att)
        if not frames:
            blocks.append({"type": "text", "text": _video_note(att)})
        for label, raw in frames:
            blocks.append({"type": "text", "text": label})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(raw).decode("ascii"),
                    },
                }
            )
    return blocks or text


def build_openai_user_content(text: str, attachments: list[MessageAttachment]) -> str | list[dict[str, Any]]:
    media = media_attachments(attachments)
    if not media:
        return text
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for att in media:
        if att.kind == "image":
            mime = att.mime or "image/png"
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{att.data_base64}"}})
            continue
        frames = _video_frames(att)
        if not frames:
            parts.append({"type": "text", "text": _video_note(att)})
        for label, raw in frames:
            parts.append({"type": "text", "text": label})
            b64 = base64.b64encode(raw).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return parts or text


def build_gemini_user_parts(text: str, attachments: list[MessageAttachment]) -> list[Any]:
    from google.genai import types

    from backend.agent.video.routing import gemini_inline_mime

    parts: list[Any] = []
    if text:
        parts.append(types.Part.from_text(text=text))
    for att in media_attachments(attachments):
        if att.kind == "image":
            raw = base64.b64decode(att.data_base64)
            parts.append(types.Part.from_bytes(data=raw, mime_type=att.mime or "image/png"))
            continue
        native = gemini_inline_mime(att.mime, att.size_bytes)
        if native:
            try:
                parts.append(types.Part.from_bytes(data=Path(att.file_path).read_bytes(), mime_type=native))
                continue
            except OSError:
                pass
        frames = _video_frames(att)
        if not frames:
            parts.append(types.Part.from_text(text=_video_note(att)))
        for label, raw in frames:
            parts.append(types.Part.from_text(text=label))
            parts.append(types.Part.from_bytes(data=raw, mime_type="image/jpeg"))
    return parts
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/backend/agent/test_multimodal_video.py ducky_app/backend/agent -q -k "multimodal or image or attach or video"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/backend/agent/multimodal_content.py ducky_app/backend/agent/test_multimodal_video.py
git commit -m "feat(video): send native video to Gemini and labelled frames elsewhere"
```

---

### Task 8: Serve videos with HTTP Range

**Files:**
- Modify: `ducky_app/frontend/ui_web/panel_httpd.py` (`_CHAT_ATTACHMENT_RE` ~line 67; chat-attachment branch ~line 890)
- Test: `ducky_app/frontend/ui_web/test_chat_attachment_range.py`

**Interfaces:**
- Consumes: existing `_parse_range_header(range_header, file_size) -> (start, end) | None` (raises `ValueError` → 416)
- Produces: module function `_read_file_range(file_path: Path, range_header: str | None) -> tuple[int, bytes, dict[str, str]]` (status, body, extra headers) used by the chat-attachment branch.

- [ ] **Step 1: Write the failing test**

`ducky_app/frontend/ui_web/test_chat_attachment_range.py`:

```python
from __future__ import annotations

from frontend.ui_web import panel_httpd as h


def test_regex_accepts_videos_and_frames():
    assert h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/1_0_bug.mp4")
    assert h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/1_0_bug.mp4.f20-01.jpg")
    assert not h._CHAT_ATTACHMENT_RE.match("chat-attachments/c1/evil.exe")


def test_read_file_range(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0123456789")
    assert h._read_file_range(f, None) == (200, b"0123456789", {"Accept-Ranges": "bytes"})
    status, body, headers = h._read_file_range(f, "bytes=2-4")
    assert (status, body) == (206, b"234")
    assert headers == {"Accept-Ranges": "bytes", "Content-Range": "bytes 2-4/10"}
    status, body, headers = h._read_file_range(f, "bytes=50-60")
    assert (status, body, headers["Content-Range"]) == (416, b"", "bytes */10")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/frontend/ui_web/test_chat_attachment_range.py -q`
Expected: FAIL — `AttributeError: _read_file_range` and regex mismatch

- [ ] **Step 3: Implement**

Change the regex:

```python
_CHAT_ATTACHMENT_RE = re.compile(
    r"^chat-attachments/([A-Za-z0-9._-]{1,80})/([A-Za-z0-9._-]+\.(?:png|jpe?g|webp|mp4|webm|mov|mkv))$",
    re.IGNORECASE,
)
```

Add next to `_parse_range_header`:

```python
def _read_file_range(file_path: Path, range_header: str | None) -> tuple[int, bytes, dict[str, str]]:
    """Body + status for a file honoring a single ``Range`` (video seeking needs 206)."""
    size = file_path.stat().st_size
    try:
        byte_range = _parse_range_header(range_header, size)
    except ValueError:
        return 416, b"", {"Content-Range": f"bytes */{size}"}
    with file_path.open("rb") as fh:
        if byte_range is None:
            return 200, fh.read(), {"Accept-Ranges": "bytes"}
        start, end = byte_range
        fh.seek(start)
        body = fh.read(end - start + 1)
    return 206, body, {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"}
```

Replace the body of the `if chat_att:` branch after `resolve_chat_attachment_path` with:

```python
                    try:
                        status, data, extra = _read_file_range(file_path, self.headers.get("Range"))
                    except OSError:
                        self.send_error(404)
                        return
                    self.send_response(status)
                    self.send_header("Content-Type", media_content_type(file_path))
                    self.send_header("Content-Length", str(len(data)))
                    for key, value in extra.items():
                        self.send_header(key, value)
                    self.send_header("Cache-Control", "private, max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                    return
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/frontend/ui_web/test_chat_attachment_range.py ducky_app/frontend/ui_web -q -k "httpd or range or attachment"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/frontend/ui_web/panel_httpd.py ducky_app/frontend/ui_web/test_chat_attachment_range.py
git commit -m "feat(video): serve chat videos with range requests"
```

---

### Task 9: Panel API (stage, settings, ffmpeg)

**Files:**
- Create: `ducky_app/frontend/ui_web/panel_api_video.py`
- Modify: `ducky_app/frontend/ui_web/panel_api.py` (mixin import ~line 810, class bases ~line 813)
- Test: `ducky_app/frontend/ui_web/test_panel_api_video.py`

**Interfaces:**
- Consumes: `staging.stage_video`, `routing.needs_frames`, `ffmpeg_install.{status,start_install,remove}`, `limits` constants, `frontend.ui_web.project_chats.load_conversation(conv_id, project_root=None)`
- Produces (PanelApi methods):
  - `stage_video_attachment(conv_id: str = "", name: str = "", mime: str = "", data_base64: str = "") -> {"ok": bool, "error"?: str, "staged_id", "size_bytes", "mime", "needs_ffmpeg": bool, "ffmpeg": status}`
  - `get_video_settings() -> {"ok": True, "video_max_mb", "video_frames_per_video", "max_images_per_message", "ffmpeg": status}`
  - `set_video_settings(patch: dict) -> same as get_video_settings`
  - `get_ffmpeg_status() -> status`, `install_ffmpeg() -> status`, `remove_ffmpeg() -> status`

- [ ] **Step 1: Write the failing tests**

`ducky_app/frontend/ui_web/test_panel_api_video.py`:

```python
from __future__ import annotations

import base64

from frontend.ui_web.panel_api import PanelApi


def test_video_settings_roundtrip_and_clamp(monkeypatch):
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.status", lambda: {"state": "missing"})
    api = PanelApi()
    out = api.set_video_settings({"video_max_mb": 500, "video_frames_per_video": "12", "max_images_per_message": 0})
    assert (out["video_max_mb"], out["video_frames_per_video"], out["max_images_per_message"]) == (200, 12, 1)
    assert api.get_video_settings()["video_frames_per_video"] == 12
    assert out["ffmpeg"] == {"state": "missing"}


def test_stage_unknown_conv_starts_ffmpeg(monkeypatch):
    started = []
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.start_install", lambda: started.append(1) or {"state": "installing"})
    res = PanelApi().stage_video_attachment("nope", "a.mp4", "video/mp4", base64.b64encode(b"x").decode())
    assert res["ok"] and res["needs_ffmpeg"] and started == [1]
    assert res["ffmpeg"] == {"state": "installing"}


def test_stage_gemini_conv_skips_ffmpeg(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "frontend.ui_web.project_chats.load_conversation",
        lambda cid, project_root=None: SimpleNamespace(is_group=False, coding_agent="ducky", provider="gemini"),
    )
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.start_install", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.status", lambda: {"state": "missing"})
    res = PanelApi().stage_video_attachment("c1", "a.mp4", "video/mp4", base64.b64encode(b"x").decode())
    assert res["ok"] and res["needs_ffmpeg"] is False


def test_stage_error_is_returned_not_raised():
    res = PanelApi().stage_video_attachment("c", "a.avi", "video/avi", "eA==")
    assert res == {"ok": False, "error": "Unsupported video format for 'a.avi' — use MP4, WebM, MOV or MKV."}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest ducky_app/frontend/ui_web/test_panel_api_video.py -q`
Expected: FAIL — `AttributeError: 'PanelApi' object has no attribute 'set_video_settings'`

- [ ] **Step 3: Implement**

`ducky_app/frontend/ui_web/panel_api_video.py`:

```python
"""Panel API: video uploads (staging), Settings → Videos, and the ffmpeg install."""

from __future__ import annotations

from typing import Any

from frontend.ui_web import panel_api as _pa


class PanelApiVideoMixin:
    def stage_video_attachment(
        self, conv_id: str = "", name: str = "", mime: str = "", data_base64: str = ""
    ) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install
        from backend.agent.video.staging import stage_video

        try:
            staged = stage_video(str(name or ""), str(mime or ""), str(data_base64 or ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        needs = _video_needs_ffmpeg(str(conv_id or "").strip(), staged)
        ff = ffmpeg_install.start_install() if needs else ffmpeg_install.status()
        return {"ok": True, **staged, "needs_ffmpeg": needs, "ffmpeg": ff}

    def get_video_settings(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install
        from backend.agent.video.limits import video_limits

        lim = video_limits()
        return {
            "ok": True,
            "video_max_mb": lim.max_bytes // (1024 * 1024),
            "video_frames_per_video": lim.frames_per_video,
            "max_images_per_message": lim.max_images_per_message,
            "ffmpeg": ffmpeg_install.status(),
        }

    def set_video_settings(self, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.agent.video import limits as L

        data = _pa._coerce_mapping(patch, label="video settings patch")
        s = _pa.PanelSettings.load()
        if "video_max_mb" in data:
            s.video_max_mb = L.clamp(data["video_max_mb"], *L.VIDEO_MAX_MB_RANGE, L.DEFAULT_VIDEO_MAX_MB)
        if "video_frames_per_video" in data:
            s.video_frames_per_video = L.clamp(
                data["video_frames_per_video"], *L.FRAMES_PER_VIDEO_RANGE, L.DEFAULT_FRAMES_PER_VIDEO
            )
        if "max_images_per_message" in data:
            s.max_images_per_message = L.clamp(
                data["max_images_per_message"],
                *L.MAX_IMAGES_PER_MESSAGE_RANGE,
                L.DEFAULT_MAX_IMAGES_PER_MESSAGE,
            )
        s.save()
        return self.get_video_settings()

    def get_ffmpeg_status(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.status()

    def install_ffmpeg(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.start_install()

    def remove_ffmpeg(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.remove()


def _video_needs_ffmpeg(conv_id: str, staged: dict[str, Any]) -> bool:
    """Gemini-only single chats with a small supported video never need ffmpeg."""
    from backend.agent.coding_agents.base import normalize_coding_agent
    from backend.agent.video.routing import needs_frames
    from frontend.ui_web import project_chats

    conv = project_chats.load_conversation(conv_id) if conv_id else None
    if conv is None or getattr(conv, "is_group", False):
        return True
    external = normalize_coding_agent(getattr(conv, "coding_agent", None) or "ducky") != "ducky"
    return needs_frames(
        staged["mime"],
        int(staged["size_bytes"]),
        provider=str(getattr(conv, "provider", "") or ""),
        external=external,
    )
```

Check `_pa._coerce_mapping` and `_pa.PanelSettings` exist (they are used by `panel_api_settings.py`: `_pa._coerce_mapping(patch, label=...)`, `_pa.PanelSettings.load()`).

In `ducky_app/frontend/ui_web/panel_api.py`, add after the automations mixin import:

```python
from frontend.ui_web.panel_api_video import PanelApiVideoMixin  # noqa: E402
```

and add `PanelApiVideoMixin,` to the `class PanelApi(...)` bases after `PanelApiAutomationsMixin,`.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest ducky_app/frontend/ui_web/test_panel_api_video.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ducky_app/frontend/ui_web/panel_api_video.py ducky_app/frontend/ui_web/panel_api.py ducky_app/frontend/ui_web/test_panel_api_video.py
git commit -m "feat(video): panel API for staging, video settings and ffmpeg"
```

---

### Task 10: Frontend types + composer hook

**Files:**
- Modify: `ducky_app/frontend/ui_web/web/src/types/panel.ts` (`MessageAttachmentDto` ~line 706, `ComposerAttachment` ~line 716, `PanelApi` interface ~line 2256)
- Modify: `ducky_app/frontend/ui_web/web/src/hooks/useComposerAttachments.ts`
- Test: `ducky_app/frontend/ui_web/web/src/hooks/useComposerAttachments.test.ts` (append)

**Interfaces:**
- Consumes: Task 9 API methods.
- Produces (TS):

```ts
export interface VideoFrameDto { path?: string; t_s: number; abs_path?: string; media_url?: string }
export interface FfmpegStatusDto { state: "missing" | "installing" | "ready" | "error"; progress: number; error: string; version: string }
export interface VideoSettingsDto { ok?: boolean; video_max_mb: number; video_frames_per_video: number; max_images_per_message: number; ffmpeg: FfmpegStatusDto }
export type VideoAttachmentStatus = "uploading" | "preparing" | "ready" | "error";
```

`useComposerAttachments(initial?: MessageAttachmentDto[], opts?: { convId?: string })` returns the existing fields plus `hasPendingVideos: boolean` and `retryVideo(id: string): void`.

- [ ] **Step 1: Update types**

In `types/panel.ts`, replace `MessageAttachmentDto` and `ComposerAttachment`:

```ts
export interface VideoFrameDto {
  path?: string;
  t_s: number;
  abs_path?: string;
  media_url?: string;
}

export interface MessageAttachmentDto {
  kind: "image" | "file" | "video";
  name: string;
  mime?: string;
  data_base64?: string;
  text?: string;
  /** Project Saved/DuckyCaptures path when the snip was mirrored there. */
  project_path?: string;
  /** Video: composer upload id (staging dir). */
  staged_id?: string;
  /** Video: bytes on disk. */
  size_bytes?: number;
  /** Video: absolute file once persisted in a chat (resend). */
  abs_path?: string;
  /** Video: local playback URL (/chat-attachments/…). */
  media_url?: string;
  /** Video: frames the AI saw (non-Gemini recipients). */
  frames?: VideoFrameDto[];
}

export type VideoAttachmentStatus = "uploading" | "preparing" | "ready" | "error";

export type ComposerAttachment =
  | { id: string; kind: "image"; name: string; mime: string; dataUrl: string; projectPath?: string }
  | { id: string; kind: "file"; name: string; mime: string; text: string }
  | {
      id: string;
      kind: "video";
      name: string;
      mime: string;
      sizeBytes: number;
      status: VideoAttachmentStatus;
      progress?: number;
      error?: string;
      stagedId?: string;
      absPath?: string;
      previewUrl?: string;
    };

export interface FfmpegStatusDto {
  state: "missing" | "installing" | "ready" | "error";
  progress: number;
  error: string;
  version: string;
}

export interface VideoSettingsDto {
  ok?: boolean;
  video_max_mb: number;
  video_frames_per_video: number;
  max_images_per_message: number;
  ffmpeg: FfmpegStatusDto;
}
```

In `export interface PanelApi {`, add:

```ts
  stage_video_attachment?(
    conv_id: string,
    name: string,
    mime: string,
    data_base64: string,
  ): Promise<{
    ok: boolean;
    error?: string;
    staged_id?: string;
    size_bytes?: number;
    mime?: string;
    needs_ffmpeg?: boolean;
    ffmpeg?: FfmpegStatusDto;
  }>;
  get_video_settings?(): Promise<VideoSettingsDto>;
  set_video_settings?(patch: Partial<Omit<VideoSettingsDto, "ffmpeg" | "ok">>): Promise<VideoSettingsDto>;
  get_ffmpeg_status?(): Promise<FfmpegStatusDto>;
  install_ffmpeg?(): Promise<FfmpegStatusDto>;
  remove_ffmpeg?(): Promise<FfmpegStatusDto>;
```

- [ ] **Step 2: Write the failing tests** (append to `useComposerAttachments.test.ts`)

```ts
import { vi } from "vitest";
import * as panelApi from "./usePanelApi";

describe("video attachments", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockApi(api: Record<string, unknown>) {
    vi.spyOn(panelApi, "getApi").mockReturnValue(api as never);
  }

  it("stages a video once and sends only its id", async () => {
    const stage = vi.fn().mockResolvedValue({
      ok: true, staged_id: "a".repeat(32) + ".mp4", size_bytes: 3, mime: "video/mp4",
      needs_ffmpeg: false, ffmpeg: { state: "missing", progress: 0, error: "", version: "v" },
    });
    mockApi({ stage_video_attachment: stage, get_video_settings: vi.fn().mockResolvedValue({ video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40 }) });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    const file = new File([new Uint8Array([1, 2, 3])], "bug.mp4", { type: "video/mp4" });
    await act(async () => { await result.current.addFiles([file]); });
    await vi.waitFor(() => expect(result.current.hasPendingVideos).toBe(false));
    expect(stage).toHaveBeenCalledWith("c1", "bug.mp4", "video/mp4", "AQID");
    expect(result.current.toApiAttachments()).toEqual([
      { kind: "video", name: "bug.mp4", mime: "video/mp4", staged_id: "a".repeat(32) + ".mp4", size_bytes: 3 },
    ]);
  });

  it("rejects a video over the size limit before reading it", async () => {
    const stage = vi.fn();
    mockApi({ stage_video_attachment: stage, get_video_settings: vi.fn().mockResolvedValue({ video_max_mb: 10, video_frames_per_video: 20, max_images_per_message: 40 }) });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await vi.waitFor(() => expect(panelApi.getApi()?.get_video_settings).toHaveBeenCalled());
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.mp4", { type: "video/mp4" });
    await act(async () => { await result.current.addFiles([big]); });
    expect(stage).not.toHaveBeenCalled();
    expect(result.current.error).toBe("big.mp4 exceeds the 10MB video limit.");
  });

  it("stays pending while ffmpeg installs, then becomes ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const status = vi.fn()
      .mockResolvedValueOnce({ state: "installing", progress: 0.5, error: "", version: "v" })
      .mockResolvedValue({ state: "ready", progress: 1, error: "", version: "v" });
    mockApi({
      stage_video_attachment: vi.fn().mockResolvedValue({
        ok: true, staged_id: "b".repeat(32) + ".mp4", size_bytes: 1, mime: "video/mp4",
        needs_ffmpeg: true, ffmpeg: { state: "installing", progress: 0, error: "", version: "v" },
      }),
      get_ffmpeg_status: status,
      get_video_settings: vi.fn().mockResolvedValue({ video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40 }),
    });
    const { result } = renderHook(() => useComposerAttachments([], { convId: "c1" }));
    await act(async () => { await result.current.addFiles([new File([new Uint8Array([1])], "x.mp4", { type: "video/mp4" })]); });
    await vi.waitFor(() => expect(result.current.attachments[0]).toMatchObject({ status: "preparing" }));
    expect(result.current.hasPendingVideos).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    await vi.waitFor(() => expect(result.current.hasPendingVideos).toBe(false));
    vi.useRealTimers();
  });

  it("restores a queued video from its DTO", () => {
    const { result } = renderHook(() => useComposerAttachments());
    const dto: MessageAttachmentDto = { kind: "video", name: "q.mp4", mime: "video/mp4", staged_id: "c".repeat(32) + ".mp4", size_bytes: 9 };
    act(() => result.current.restoreAttachments([dto]));
    expect(result.current.hasPendingVideos).toBe(false);
    expect(result.current.toApiAttachments()).toEqual([dto]);
  });
});
```

(If `getApi` is not exported from `./usePanelApi` as a spy-able ESM binding, use `vi.mock("./usePanelApi", ...)` at the top of the file instead; check how other hook tests mock `getApi` with `grep -rn "usePanelApi" src/hooks/*.test.ts` and copy that pattern.)

- [ ] **Step 3: Run to verify failure**

Run (from `ducky_app/frontend/ui_web/web/`): `npm test -- src/hooks/useComposerAttachments.test.ts`
Expected: FAIL (video tests)

- [ ] **Step 4: Implement the hook changes**

In `useComposerAttachments.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { ComposerAttachment, MessageAttachmentDto } from "../types/panel";
import { getApi } from "./usePanelApi";

const DEFAULT_MAX_IMAGES = 40;
const DEFAULT_VIDEO_MAX_MB = 100;
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_FILE_TEXT = 256 * 1024;
const VIDEO_EXT_RE = /\.(mp4|webm|mov|mkv)$/i;
const VIDEO_EXT_MIME: Record<string, string> = {
  mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime", mkv: "video/x-matroska",
};

function videoMime(file: File): string {
  if (file.type.startsWith("video/")) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return VIDEO_EXT_MIME[ext] ?? "";
}

function isVideoFile(file: File): boolean {
  return file.type.startsWith("video/") || VIDEO_EXT_RE.test(file.name);
}
```

`composerAttachmentsFromDto` — add a video branch first:

```ts
export function composerAttachmentsFromDto(items: MessageAttachmentDto[]): ComposerAttachment[] {
  return items.map((a): ComposerAttachment => {
    if (a.kind === "video") {
      return {
        id: newId(),
        kind: "video",
        name: a.name,
        mime: a.mime || "video/mp4",
        sizeBytes: a.size_bytes ?? 0,
        status: "ready",
        ...(a.staged_id ? { stagedId: a.staged_id } : {}),
        ...(a.abs_path ? { absPath: a.abs_path } : {}),
        ...(a.media_url ? { previewUrl: a.media_url } : {}),
      };
    }
    return a.kind === "image"
      ? { /* existing image object unchanged */ }
      : { /* existing file object unchanged */ };
  });
}
```

Inside the hook (signature `useComposerAttachments(initial: MessageAttachmentDto[] = [], opts: { convId?: string } = {})`), add:

```ts
  const convIdRef = useRef(opts.convId ?? "");
  convIdRef.current = opts.convId ?? "";
  const filesRef = useRef(new Map<string, File>());
  const [limits, setLimits] = useState({ maxImages: DEFAULT_MAX_IMAGES, videoMaxMb: DEFAULT_VIDEO_MAX_MB });

  useEffect(() => {
    let alive = true;
    void getApi()?.get_video_settings?.().then((s) => {
      if (alive && s) setLimits({ maxImages: s.max_images_per_message, videoMaxMb: s.video_max_mb });
    }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  const patchVideo = useCallback((id: string, patch: Partial<Extract<ComposerAttachment, { kind: "video" }>>) => {
    setAttachments((prev) => prev.map((a) => (a.id === id && a.kind === "video" ? { ...a, ...patch } : a)));
  }, []);

  const stageVideo = useCallback(async (id: string, file: File) => {
    const api = getApi();
    if (!api?.stage_video_attachment) {
      patchVideo(id, { status: "error", error: "Video upload is not available." });
      return;
    }
    patchVideo(id, { status: "uploading", error: undefined });
    try {
      const dataUrl = await readFileAsDataUrl(file);
      const res = await api.stage_video_attachment(
        convIdRef.current, file.name, videoMime(file), dataUrl.replace(/^data:[^;]*;base64,/, ""),
      );
      if (!res?.ok || !res.staged_id) {
        patchVideo(id, { status: "error", error: res?.error || "Video upload failed." });
        return;
      }
      const ff = res.ffmpeg;
      const status = !res.needs_ffmpeg || ff?.state === "ready" ? "ready" : ff?.state === "error" ? "error" : "preparing";
      patchVideo(id, {
        stagedId: res.staged_id,
        mime: res.mime || file.type,
        sizeBytes: res.size_bytes ?? file.size,
        status,
        progress: ff?.progress ?? 0,
        error: status === "error" ? ff?.error : undefined,
      });
    } catch (e) {
      patchVideo(id, { status: "error", error: e instanceof Error ? e.message : "Video upload failed." });
    }
  }, [patchVideo]);

  const retryVideo = useCallback((id: string) => {
    const att = attachments.find((a) => a.id === id);
    if (!att || att.kind !== "video") return;
    if (att.stagedId) {
      patchVideo(id, { status: "preparing", error: undefined, progress: 0 });
      void getApi()?.install_ffmpeg?.();
      return;
    }
    const file = filesRef.current.get(id);
    if (file) void stageVideo(id, file);
  }, [attachments, patchVideo, stageVideo]);

  const preparing = attachments.some((a) => a.kind === "video" && a.status === "preparing");
  useEffect(() => {
    if (!preparing) return;
    const timer = window.setInterval(() => {
      void getApi()?.get_ffmpeg_status?.().then((st) => {
        if (!st) return;
        setAttachments((prev) => prev.map((a) => {
          if (a.kind !== "video" || a.status !== "preparing") return a;
          if (st.state === "ready") return { ...a, status: "ready", progress: 1 };
          if (st.state === "error" || st.state === "missing") {
            return { ...a, status: "error", error: st.error || "ffmpeg is not installed." };
          }
          return { ...a, progress: st.progress };
        }));
      }).catch(() => undefined);
    }, 500);
    return () => window.clearInterval(timer);
  }, [preparing]);

  const hasPendingVideos = attachments.some((a) => a.kind === "video" && a.status !== "ready");
```

In `addFiles`, use `limits.maxImages` instead of `MAX_IMAGES`, and handle videos before the image check (videos are uploaded after `setAttachments`):

```ts
      const uploads: Array<{ id: string; file: File }> = [];
      ...
        for (const file of list) {
          if (isVideoFile(file)) {
            if (opts?.imagesOnly) {
              setError("Only image files are supported for image upload.");
              continue;
            }
            if (file.size > limits.videoMaxMb * 1024 * 1024) {
              setError(`${file.name} exceeds the ${limits.videoMaxMb}MB video limit.`);
              continue;
            }
            const id = newId();
            const previewUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : undefined;
            filesRef.current.set(id, file);
            next.push({
              id, kind: "video", name: file.name, mime: videoMime(file), sizeBytes: file.size,
              status: "uploading", ...(previewUrl ? { previewUrl } : {}),
            });
            uploads.push({ id, file });
            continue;
          }
          const isImage = file.type.startsWith("image/");
          ... (existing code, MAX_IMAGES → limits.maxImages)
        }
        if (next.length > 0) {
          setAttachments((prev) => [...prev, ...next]);
        }
        await Promise.all(uploads.map((u) => stageVideo(u.id, u.file)));
```

Add `limits`, `stageVideo` to `addFiles` deps. Note the `addFiles` second parameter is named `opts` already — rename the hook option to `hookOpts` to avoid shadowing.

`removeAttachment` — revoke blob previews and forget the file:

```ts
  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const gone = prev.find((a) => a.id === id);
      if (gone?.kind === "video" && gone.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(gone.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
    filesRef.current.delete(id);
  }, []);
```

`toApiAttachments` — add a video branch:

```ts
      if (a.kind === "video") {
        const row: MessageAttachmentDto = { kind: "video", name: a.name, mime: a.mime, size_bytes: a.sizeBytes };
        if (a.stagedId) row.staged_id = a.stagedId;
        if (a.absPath) row.abs_path = a.absPath;
        return row;
      }
```

Return `hasPendingVideos` and `retryVideo` from the hook.

- [ ] **Step 5: Run tests + typecheck**

Run: `npm test -- src/hooks/useComposerAttachments.test.ts`
Expected: PASS
Run: `npx tsc -b`
Expected: errors only in components handled by Task 11 (`ChatPane.tsx`, `ComposerAttachmentChips.tsx`, `EditableUserMessage.tsx`, `AttachmentPreviewModal.tsx`) — note them, fix in Task 11.

- [ ] **Step 6: Commit**

```bash
git add src/types/panel.ts src/hooks/useComposerAttachments.ts src/hooks/useComposerAttachments.test.ts
git commit -m "feat(video): composer stages videos and tracks ffmpeg readiness"
```

---

### Task 11: Chat UI (chips, preview, send gating, history player)

**Files:**
- Modify: `src/components/ComposerAttachmentChips.tsx`, `src/components/AttachmentPreviewModal.tsx`, `src/components/ChatPane.tsx` (~lines 280–305, 838–857, 1496), `src/components/EditableUserMessage.tsx` (`AttachmentStrip` + its caller ~line 109), and the stylesheet that defines `.composer-attachment-chip` / `.message-bubble-attachments` (find with `grep -rln "composer-attachment-chip" src --include=*.css`).
- Test: `src/components/ComposerAttachmentChips.test.tsx`

**Interfaces:**
- Consumes: `ComposerAttachment` video variant, `retryVideo`, `hasPendingVideos`, `MessageAttachmentDto.media_url/frames`.
- Produces: `ComposerAttachmentChips` prop `onRetry?: (id: string) => void`.

- [ ] **Step 1: Write the failing test**

`src/components/ComposerAttachmentChips.test.tsx`:

```tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComposerAttachmentChips } from "./ComposerAttachmentChips";

afterEach(cleanup);

describe("video chips", () => {
  it("shows progress while preparing and a retry button on error", () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <ComposerAttachmentChips
        attachments={[{ id: "v1", kind: "video", name: "bug.mp4", mime: "video/mp4", sizeBytes: 5_000_000, status: "preparing", progress: 0.42 }]}
        onRemove={() => {}}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("Preparing… 42%")).toBeTruthy();
    rerender(
      <ComposerAttachmentChips
        attachments={[{ id: "v1", kind: "video", name: "bug.mp4", mime: "video/mp4", sizeBytes: 5_000_000, status: "error", error: "offline" }]}
        onRemove={() => {}}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByTitle("offline")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry bug.mp4" }));
    expect(onRetry).toHaveBeenCalledWith("v1");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/components/ComposerAttachmentChips.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement chips**

In `ComposerAttachmentChips.tsx`, add `onRetry?: (id: string) => void` to props and a helper:

```tsx
function videoStatusLabel(att: Extract<ComposerAttachment, { kind: "video" }>): string {
  if (att.status === "uploading") return "Uploading…";
  if (att.status === "preparing") return `Preparing… ${Math.round((att.progress ?? 0) * 100)}%`;
  if (att.status === "error") return "Error";
  return `${(att.sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}
```

Replace the thumbnail ternary with:

```tsx
            {att.kind === "image" ? (
              <img src={att.dataUrl} alt={att.name} className="composer-attachment-chip-thumb" />
            ) : att.kind === "video" ? (
              att.previewUrl ? (
                <video src={att.previewUrl} muted preload="metadata" className="composer-attachment-chip-thumb" />
              ) : (
                <span className="composer-attachment-chip-file-icon" aria-hidden>
                  <Icons.Play />
                </span>
              )
            ) : (
              <span className="composer-attachment-chip-file-icon" aria-hidden>
                <Icons.File />
              </span>
            )}
            <span className="composer-attachment-chip-name" title={att.name}>
              {att.name}
            </span>
            {att.kind === "video" ? (
              <span
                className={`composer-attachment-chip-status is-${att.status}`}
                title={att.status === "error" ? att.error : undefined}
              >
                {videoStatusLabel(att)}
              </span>
            ) : null}
```

And before the remove button:

```tsx
          {att.kind === "video" && att.status === "error" && onRetry ? (
            <button
              type="button"
              className="composer-attachment-chip-retry"
              aria-label={`Retry ${att.name}`}
              onClick={() => onRetry(att.id)}
            >
              <Icons.Replay />
            </button>
          ) : null}
```

CSS (in the same stylesheet as `.composer-attachment-chip`; the lint script forbids inline styles):

```css
.composer-attachment-chip-status {
  font-size: 11px;
  opacity: 0.75;
  white-space: nowrap;
}
.composer-attachment-chip-status.is-error {
  color: var(--color-danger, #e5484d);
  opacity: 1;
}
.composer-attachment-chip-retry {
  background: none;
  border: 0;
  padding: 0 2px;
  cursor: pointer;
  color: inherit;
}
.message-bubble-attachment-video {
  max-width: 360px;
  max-height: 240px;
  border-radius: 6px;
  display: block;
}
.message-bubble-video-frames summary {
  cursor: pointer;
  font-size: 12px;
  opacity: 0.75;
}
.message-bubble-video-frames-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 4px;
  margin-top: 4px;
}
.message-bubble-video-frames-grid figure {
  margin: 0;
  font-size: 10px;
  text-align: center;
}
.message-bubble-video-frames-grid img {
  width: 100%;
  border-radius: 4px;
}
.attachment-preview-video {
  max-width: 100%;
  max-height: 70vh;
}
```

- [ ] **Step 4: ChatPane wiring**

In `ChatPane.tsx`:
- Hook call: `useComposerAttachments(initialComposer?.attachments ?? [], { convId: chat.id })`, and destructure `hasPendingVideos, retryVideo`.
- `previewAttachment` memo: add before the file fallback:

```tsx
    if (att.kind === "video") {
      return { kind: "video", name: att.name, mime: att.mime, media_url: att.previewUrl };
    }
```

- `canCompose`: append `&& !hasPendingVideos` after `!visionBlocked`.
- `visionBlocked`: use `(hasImages || attachments.some((a) => a.kind === "video"))` in place of `hasImages`, so a non-vision model blocks videos too (Gemini models report vision, so the native path is unaffected).
- `<ComposerAttachmentChips ... onRetry={retryVideo} />`.

- [ ] **Step 5: Preview modal**

In `AttachmentPreviewModal.tsx`, extend the title fallback to `attachment.kind === "image" ? "Image" : attachment.kind === "video" ? "Video" : "File"`, and add before the `attachment.kind === "file"` branch:

```tsx
        ) : attachment.kind === "video" && attachment.media_url ? (
          <video src={attachment.media_url} controls autoPlay className="attachment-preview-video" />
```

- [ ] **Step 6: History player**

In `EditableUserMessage.tsx`, give `AttachmentStrip` a `videos: MessageAttachmentDto[]` prop and render, after the images:

```tsx
      {videos.map((att) => (
        <div key={`vid-${att.name}-${att.media_url ?? ""}`} className="message-bubble-attachment-video-wrap">
          {att.media_url ? (
            <video src={att.media_url} controls preload="metadata" className="message-bubble-attachment-video" />
          ) : (
            <span className="message-bubble-attachment-file-name">{att.name}</span>
          )}
          {att.frames && att.frames.length > 0 ? (
            <details className="message-bubble-video-frames">
              <summary>{att.frames.length} frames sent to the AI</summary>
              <div className="message-bubble-video-frames-grid">
                {att.frames.map((f, i) => (
                  <figure key={f.media_url ?? i}>
                    {f.media_url ? <img src={f.media_url} alt={`Frame ${i + 1}`} /> : null}
                    <figcaption>{formatSeconds(f.t_s)}</figcaption>
                  </figure>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      ))}
```

with

```tsx
function formatSeconds(t: number): string {
  const s = Math.floor(t);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
```

Update the early return to `if (images.length === 0 && files.length === 0 && videos.length === 0) return null;` and, where `AttachmentStrip` is used (~line 109), split `items` into `images`, `files` (kind `"file"`), and `videos` (kind `"video"`) and pass `videos`.

- [ ] **Step 7: Run tests, typecheck, lint**

Run: `npm test -- src/components/ComposerAttachmentChips.test.tsx src/hooks/useComposerAttachments.test.ts`
Expected: PASS
Run: `npx tsc -b && npm run lint`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add src/components src/hooks
git add $(grep -rln "composer-attachment-chip" src --include=*.css)
git commit -m "feat(video): video chips, preview, send gating and history player"
```

---

### Task 12: Settings → Videos tab

**Files:**
- Create: `src/views/settings/VideosTab.tsx`
- Modify: `src/views/SettingsView.tsx` (`CORE_TABS` ~line 61, `CORE_TAB_ICONS` ~line 79, lazy import ~line 54, render switch ~line 651)
- Test: `src/views/settings/VideosTab.test.tsx`

**Interfaces:**
- Consumes: `get_video_settings`, `set_video_settings`, `install_ffmpeg`, `remove_ffmpeg`, `get_ffmpeg_status`.

- [ ] **Step 1: Write the failing test**

`src/views/settings/VideosTab.test.tsx`:

```tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as panelApi from "../../hooks/usePanelApi";
import { VideosTab } from "./VideosTab";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const settings = {
  video_max_mb: 100, video_frames_per_video: 20, max_images_per_message: 40,
  ffmpeg: { state: "missing", progress: 0, error: "", version: "n9.0.1" },
};

describe("VideosTab", () => {
  it("loads, saves a clamped value and installs ffmpeg", async () => {
    const set = vi.fn().mockResolvedValue({ ...settings, video_frames_per_video: 40 });
    const install = vi.fn().mockResolvedValue({ ...settings.ffmpeg, state: "installing" });
    vi.spyOn(panelApi, "getApi").mockReturnValue({
      get_video_settings: vi.fn().mockResolvedValue(settings),
      set_video_settings: set,
      install_ffmpeg: install,
      get_ffmpeg_status: vi.fn().mockResolvedValue(settings.ffmpeg),
    } as never);
    render(<VideosTab />);
    const frames = await screen.findByLabelText("Frames per video");
    fireEvent.change(frames, { target: { value: "99" } });
    fireEvent.blur(frames);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ video_frames_per_video: 99 }));
    expect((frames as HTMLInputElement).value).toBe("40");
    expect(screen.getByText("Not installed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Install now" }));
    await waitFor(() => expect(install).toHaveBeenCalled());
  });
});
```

(Match the `getApi` mocking pattern used by other settings tests if `vi.spyOn` on the module doesn't work — see `src/views/settings/AppDataDatabase.test.tsx`.)

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/views/settings/VideosTab.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

`src/views/settings/VideosTab.tsx`:

```tsx
/**
 * Settings → Videos — video attachment limits and the on-demand ffmpeg install.
 */

import { useCallback, useEffect, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import type { FfmpegStatusDto, VideoSettingsDto } from "../../types/panel";
import { GeneralSectionHeader } from "./GeneralSectionHeader";

type NumericKey = "video_max_mb" | "video_frames_per_video" | "max_images_per_message";

const FIELDS: { key: NumericKey; label: string; min: number; max: number; hint: string }[] = [
  { key: "video_max_mb", label: "Max video size (MB)", min: 10, max: 200, hint: "Largest video one message can carry." },
  { key: "video_frames_per_video", label: "Frames per video", min: 1, max: 40, hint: "Frames sent to models without native video (Claude, OpenAI, coding agents…)." },
  { key: "max_images_per_message", label: "Max images per message", min: 1, max: 100, hint: "Images per message, video frames included." },
];

function ffmpegLabel(st: FfmpegStatusDto): string {
  if (st.state === "ready") return `Installed (${st.version})`;
  if (st.state === "installing") return `Installing… ${Math.round(st.progress * 100)}%`;
  if (st.state === "error") return st.error || "Install failed";
  return "Not installed";
}

export function VideosTab() {
  const [settings, setSettings] = useState<VideoSettingsDto | null>(null);
  const [draft, setDraft] = useState<Record<NumericKey, string>>({
    video_max_mb: "", video_frames_per_video: "", max_images_per_message: "",
  });

  const apply = useCallback((s: VideoSettingsDto) => {
    setSettings(s);
    setDraft({
      video_max_mb: String(s.video_max_mb),
      video_frames_per_video: String(s.video_frames_per_video),
      max_images_per_message: String(s.max_images_per_message),
    });
  }, []);

  useEffect(() => {
    void getApi()?.get_video_settings?.().then((s) => s && apply(s));
  }, [apply]);

  const installing = settings?.ffmpeg.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => {
      void getApi()?.get_ffmpeg_status?.().then((ffmpeg) => {
        if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [installing]);

  const save = useCallback(async (key: NumericKey) => {
    const value = Number(draft[key]);
    if (!Number.isFinite(value)) return;
    const next = await getApi()?.set_video_settings?.({ [key]: value });
    if (next) apply(next);
  }, [draft, apply]);

  const runFfmpeg = useCallback(async (action: "install" | "remove") => {
    const api = getApi();
    const ffmpeg = action === "install" ? await api?.install_ffmpeg?.() : await api?.remove_ffmpeg?.();
    if (ffmpeg) setSettings((prev) => (prev ? { ...prev, ffmpeg } : prev));
  }, []);

  if (!settings) return null;
  return (
    <div className="general-tab-shell">
      <GeneralSectionHeader title="Videos" />
      {FIELDS.map((f) => (
        <label key={f.key} className="settings-field">
          <span className="settings-field-label">{f.label}</span>
          <input
            type="number"
            min={f.min}
            max={f.max}
            aria-label={f.label}
            value={draft[f.key]}
            onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            onBlur={() => void save(f.key)}
          />
          <span className="settings-field-hint">{f.hint}</span>
        </label>
      ))}
      <div className="settings-field">
        <span className="settings-field-label">ffmpeg</span>
        <span>{ffmpegLabel(settings.ffmpeg)}</span>
        <span className="settings-field-hint">
          Downloaded automatically (~67 MB, LGPL build) the first time a video needs frames. Gemini users with small
          videos never need it.
        </span>
        <div>
          {settings.ffmpeg.state !== "ready" ? (
            <button type="button" disabled={installing} onClick={() => void runFfmpeg("install")}>
              Install now
            </button>
          ) : (
            <button type="button" onClick={() => void runFfmpeg("remove")}>
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
```

Before writing, check `GeneralSectionHeader`'s props (`sed -n 1,30p src/views/settings/GeneralSectionHeader.tsx`) and an existing numeric settings row in `MemoryTab.tsx` (~line 300) and reuse its class names instead of `settings-field*` if they differ.

In `SettingsView.tsx`:

```tsx
const VideosTab = lazy(() => import("./settings/VideosTab").then((m) => ({ default: m.VideosTab })));
```

Add `"Videos",` to `CORE_TABS` after `"Audio"`, `Videos: Icons.Play,` to `CORE_TAB_ICONS`, and `{activeTab === "Videos" && <VideosTab />}` after the Audio line in the render switch.

- [ ] **Step 4: Run tests, typecheck, lint**

Run: `npm test -- src/views/settings/VideosTab.test.tsx`
Expected: PASS
Run: `npx tsc -b && npm run lint`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add src/views/settings/VideosTab.tsx src/views/settings/VideosTab.test.tsx src/views/SettingsView.tsx
git commit -m "feat(video): Settings → Videos tab with ffmpeg controls"
```

---

### Task 13: Notices + end-to-end verification

**Files:**
- Modify: `UEFN-Ducky/THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Add the notice**

After the "Not redistributed — sourced from the user's UEFN install" section, add:

```markdown
## Downloaded at runtime — not bundled

### FFmpeg
- **License:** LGPL-2.1-or-later (BtbN `win64-lgpl-shared` build; no GPL components)
- **Source:** https://github.com/BtbN/FFmpeg-Builds (release `autobuild-2026-08-31-13-27`), FFmpeg source at https://ffmpeg.org
- **Use:** downloaded into `%LOCALAPPDATA%\UEFN-Ducky\tools\ffmpeg\` only when a chat video needs frames;
  verified by SHA-256 and run as a separate process (`ffmpeg.exe`, `ffprobe.exe`). The archive's
  `LICENSE.txt` is kept next to the binaries.
```

- [ ] **Step 2: Full test runs**

Run (from `UEFN-Ducky/`): `.venv/Scripts/python -m pytest ducky_app -q`
Expected: PASS (or only failures that already existed on the base branch — confirm by running the same command on the base commit)
Run (from `web/`): `npm test && npx tsc -b && npm run lint`
Expected: PASS

- [ ] **Step 3: Manual check in the running app** (hot-deploy per the listener workflow, then reload)

1. Chat on a Claude model → attach a 10–30 s MP4 → chip shows "Preparing… N%" (first time) then size → send → status "Extracting frames…" → reply references what happens in the video; history shows the player + "20 frames sent to the AI" with timestamps; seeking in the player works.
2. Chat on Gemini with a < 20 MB MP4 → chip ready immediately, no ffmpeg download if not installed yet (Settings → Videos still "Not installed") → reply describes the video.
3. Claude Code chat → attach video → reply shows it saw the frames.
4. Settings → Videos: set "Frames per video" to 5 → new message sends 5 frames. Click **Remove** → status "Not installed"; attach a video on Claude → downloads again.
5. Disconnect network, Remove ffmpeg, attach video on Claude → chip shows error with Retry; reconnect → Retry → ready.
6. Attach a 150 MB video with the default 100 MB limit → error "exceeds the 100MB video limit".

- [ ] **Step 4: Commit**

```bash
git add THIRD_PARTY_NOTICES.md
git commit -m "docs: note runtime-downloaded LGPL FFmpeg"
```
