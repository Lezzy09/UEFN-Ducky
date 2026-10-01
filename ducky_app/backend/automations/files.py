"""Files on data wires: what each Input node may pick, the ref that travels, and the
signed loopback link the editor shows it through (thumbnails, Last run).

A link is ``/workflow-media/<sig>/<token>/<name>``: the token is the file's path, the
sig an HMAC of it with a key kept in AppData, so the panel server only hands out files
this app linked (run outputs, files the user picked) and only media types."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import shutil
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

FILE_FILTERS: dict[str, tuple[str, ...]] = {
    "image": ("Images (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp;*.tga;*.tif;*.tiff;*.exr)", "All files (*.*)"),
    "audio": ("Audio (*.mp3;*.wav;*.ogg;*.m4a;*.flac;*.webm)", "All files (*.*)"),
    "video": ("Video (*.mp4;*.mov;*.webm;*.mkv;*.avi)", "All files (*.*)"),
    "mesh": ("3D models (*.fbx;*.glb;*.gltf;*.obj;*.usd;*.usda;*.usdz;*.stl;*.ply;*.blend)", "All files (*.*)"),
    "pdf": ("PDF documents (*.pdf)", "All files (*.*)"),
    "svg": ("SVG (*.svg)", "All files (*.*)"),
    "any": ("All files (*.*)",),
}


def file_ref(path: Any, kind: str) -> dict[str, str]:
    text = str(path)
    return {"kind": kind if kind in FILE_FILTERS and kind != "any" else "file", "path": text, "name": Path(text).name}


# Kinds by extension, for files a generator downloads (it doesn't say what each one is).
KIND_BY_EXT: dict[str, str] = {
    **{ext: "image" for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tga", ".tif", ".tiff", ".exr")},
    **{ext: "mesh" for ext in (".glb", ".gltf", ".fbx", ".obj", ".usd", ".usda", ".usdz", ".stl", ".ply")},
    **{ext: "audio" for ext in (".mp3", ".wav", ".ogg", ".m4a", ".flac")},
    **{ext: "video" for ext in (".mp4", ".mov", ".webm", ".mkv")},
    ".pdf": "pdf",
    ".svg": "svg",
}
# What the panel server may hand out through a link (no scripts, no archives).
_SERVED = frozenset(KIND_BY_EXT) - {".exr", ".tga", ".tif", ".tiff", ".usd", ".usda", ".ply"}
_RUNS_KEPT = 20
_key_lock = threading.Lock()
_key_cache: bytes = b""


def media_root(*, for_write: bool = True) -> Path:
    """AppData folder for files workflow runs make: ``workflow_media/<workflow>/<run>/<node>``."""
    from frontend.app_paths import resolve_app_data_dir

    path = resolve_app_data_dir(for_write=for_write) / "workflow_media"
    if for_write:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _safe(raw: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in (raw or "").strip())
    return cleaned[:80] or "run"


def run_folder(workflow_id: str, run_id: str, node_id: str) -> Path:
    """Where one node of one run saves its files. Making a new run's folder drops the
    oldest runs of that workflow beyond the last 20, so they never pile up."""
    wf_dir = media_root() / _safe(workflow_id)
    run_dir = wf_dir / _safe(run_id)
    fresh = not run_dir.exists()
    path = run_dir / _safe(node_id)
    path.mkdir(parents=True, exist_ok=True)
    if fresh:
        _prune_runs(wf_dir)
    return path


def _prune_runs(wf_dir: Path) -> None:
    try:
        runs = sorted((p for p in wf_dir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in runs[_RUNS_KEPT:]:
        shutil.rmtree(old, ignore_errors=True)


def kind_of(path: Any, fallback: str = "file") -> str:
    return KIND_BY_EXT.get(Path(str(path)).suffix.lower(), fallback)


def _key() -> bytes:
    global _key_cache
    with _key_lock:
        if _key_cache:
            return _key_cache
        path = media_root() / ".key"
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        if len(data) < 32:
            fresh = secrets.token_bytes(32)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                try:
                    os.write(fd, fresh)
                finally:
                    os.close(fd)
                data = fresh
            except FileExistsError:  # another process made it first
                data = path.read_bytes()
        _key_cache = data
        return data


def _sign(text: str) -> str:
    return hmac.new(_key(), text.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def media_url(path: Any) -> str:
    """The loopback link the editor shows this file through ("" when it can't be shown)."""
    if not path:
        return ""
    target = Path(str(path))
    if target.suffix.lower() not in _SERVED:
        return ""
    text = str(target)
    token = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")
    from frontend.settings import PANEL_LISTENER_PORT

    return f"http://127.0.0.1:{PANEL_LISTENER_PORT - 1}/workflow-media/{_sign(text)}/{token}/{quote(target.name)}"


def resolve_media(sig: str, token: str) -> Path:
    """The file a link points at; ValueError when it was not signed here or isn't media."""
    try:
        text = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("bad link") from exc
    if not hmac.compare_digest(_sign(text), sig or ""):
        raise ValueError("bad link")
    target = Path(text)
    if target.suffix.lower() not in _SERVED or not target.is_file():
        raise ValueError("not a file")
    return target


def with_url(ref: Any) -> Any:
    """A file ref with its link added (refreshed: the port or key may have changed)."""
    if isinstance(ref, dict) and ref.get("path"):
        url = media_url(ref["path"])
        return {**ref, "url": url} if url else {key: value for key, value in ref.items() if key != "url"}
    return ref


def is_file_ref(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("path")) and isinstance(value.get("kind"), str)
