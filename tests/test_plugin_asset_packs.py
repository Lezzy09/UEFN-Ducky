"""Asset packs: a 300 MB pack downloads, resumes after a cut connection, verifies and
unpacks; a wrong hash is refused; a bad ``asset_packs`` field refuses the install."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.uefn_plugins import asset_packs

PACK_MB = 300


class _Zeros(io.RawIOBase):
    def __init__(self, n: int) -> None:
        self.left = n

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        n = min(len(b), self.left)
        b[:n] = bytes(n)
        self.left -= n
        return n


def _serve(path: Path, cut_first_at: int | None):
    """HTTP server for one file with Range support; the first response stops after
    ``cut_first_at`` bytes (the connection drops mid-download)."""
    seen: list[str] = []
    data_len = path.stat().st_size

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401 — quiet
            pass

        def do_GET(self):
            rng = self.headers.get("Range") or ""
            seen.append(rng)
            start = int(rng[len("bytes="):].rstrip("-")) if rng.startswith("bytes=") else 0
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(data_len - start))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{data_len - 1}/{data_len}")
            self.end_headers()
            limit = cut_first_at if len(seen) == 1 and cut_first_at is not None else None
            sent = 0
            with path.open("rb") as f:
                f.seek(start)
                while chunk := f.read(1 << 20):
                    if limit is not None and sent + len(chunk) > limit:
                        self.wfile.write(chunk[: limit - sent])
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    self.wfile.write(chunk)
                    sent += len(chunk)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/pack", seen


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def test_300mb_pack_resumes_after_interrupt_and_unpacks(tmp_path, monkeypatch):
    src = tmp_path / "src" / "toolchain.tar"
    src.parent.mkdir()
    big = PACK_MB * 1024 * 1024
    with tarfile.open(src, "w") as tf:
        info = tarfile.TarInfo("emsdk/blob.bin")
        info.size = big
        tf.addfile(info, _Zeros(big))
        note = b"emcc 4.0.0\n"
        info = tarfile.TarInfo("emsdk/VERSION")
        info.size = len(note)
        tf.addfile(info, io.BytesIO(note))
    size = src.stat().st_size
    sha = _sha(src)
    manifest = {"id": "webx", "version": "1.0.0",
                "asset_packs": [{"id": "toolchain-win64", "sha256": sha, "bytes": size,
                                 "platform": asset_packs.this_platform()}]}
    server, url, seen = _serve(src, cut_first_at=100 * 1024 * 1024)
    try:
        # The first try loses its connection at 100 MB and gives up (one attempt):
        monkeypatch.setattr(asset_packs, "ATTEMPTS", 1)
        first = asset_packs.ensure_packs("webx", manifest, lambda p: url)
        assert not first["ok"] and first["packs"][0]["state"] == "failed"
        part = next((asset_packs.packs_root() / "webx" / ".downloads").glob("*.part"))
        assert part.stat().st_size == 100 * 1024 * 1024
        assert asset_packs.asset_pack_path("webx", "toolchain-win64") is None

        # The next try resumes from there with a Range request and lands the pack.
        monkeypatch.setattr(asset_packs, "ATTEMPTS", 4)
        second = asset_packs.ensure_packs("webx", manifest, lambda p: url)
    finally:
        server.shutdown()
    assert second["ok"], second
    assert seen == ["", f"bytes={100 * 1024 * 1024}-"]
    folder = asset_packs.asset_pack_path("webx", "toolchain-win64")
    assert folder is not None
    assert (folder / "emsdk" / "blob.bin").stat().st_size == big
    assert (folder / "emsdk" / "VERSION").read_text() == "emcc 4.0.0\n"
    row = asset_packs.status("webx", manifest)[0]
    assert row["state"] == "ready" and row["done"] == size
    assert not list((asset_packs.packs_root() / "webx" / ".downloads").glob("*"))  # archive removed
    # Already there: nothing downloads again.
    again = asset_packs.ensure_packs("webx", manifest, lambda p: pytest.fail("downloaded again"))
    assert again["ok"]


def _zip_pack(tmp_path: Path) -> Path:
    path = tmp_path / "srczip" / "pack.zip"
    path.parent.mkdir()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("bin/slangc.txt", "slangc 2025.1")
    return path


def test_wrong_hash_is_refused_and_deleted(tmp_path):
    src = _zip_pack(tmp_path)
    manifest = {"id": "webx", "asset_packs": [{"id": "sdk", "sha256": "0" * 64, "bytes": src.stat().st_size}]}
    server, url, _ = _serve(src, cut_first_at=None)
    try:
        out = asset_packs.ensure_packs("webx", manifest, lambda p: url)
    finally:
        server.shutdown()
    assert not out["ok"]
    assert "sha256" in out["error"]
    assert out["packs"][0]["state"] == "failed"
    assert asset_packs.asset_pack_path("webx", "sdk") is None
    assert not list((asset_packs.packs_root() / "webx" / ".downloads").glob("*"))


def test_zip_pack_lands_and_other_platforms_are_skipped(tmp_path):
    src = _zip_pack(tmp_path)
    manifest = {"id": "webx", "asset_packs": [
        {"id": "sdk", "sha256": _sha(src), "bytes": src.stat().st_size},
        {"id": "sdk-elsewhere", "sha256": "1" * 64, "bytes": 5, "platform": "nowhere"},
    ]}
    server, url, _ = _serve(src, cut_first_at=None)
    try:
        out = asset_packs.ensure_packs("webx", manifest, lambda p: url)
    finally:
        server.shutdown()
    assert out["ok"] and [r["id"] for r in out["packs"]] == ["sdk"]
    folder = asset_packs.asset_pack_path("webx", "sdk")
    assert (folder / "bin" / "slangc.txt").read_text() == "slangc 2025.1"


@pytest.mark.parametrize("entry", [
    {"id": "../x", "sha256": "a" * 64, "bytes": 1},
    {"id": "ok", "sha256": "abc", "bytes": 1},
    {"id": "ok", "sha256": "a" * 64, "bytes": 0},
    {"id": "ok", "sha256": "a" * 64, "bytes": True},
    {"id": "ok", "sha256": "a" * 64, "bytes": 1, "platform": "Win/64"},
])
def test_bad_manifest_entries_raise(entry):
    with pytest.raises(ValueError):
        asset_packs.manifest_packs({"asset_packs": [entry]})


def test_install_refuses_bad_asset_packs_field():
    from backend.uefn_plugins.store import import_plugin_from_bytes, plugin_dir

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.json", json.dumps({
            "id": "packdemo", "label": "Pack demo", "version": "1.0.0",
            "asset_packs": [{"id": "tc", "sha256": "nothex", "bytes": 10}],
        }))
        zf.writestr("backend.py", "def register(api):\n    pass\n")
    out = import_plugin_from_bytes(buf.getvalue(), source="local", replace=True)
    assert not out["ok"] and "sha256" in out["error"]
    assert not plugin_dir("packdemo").exists()
