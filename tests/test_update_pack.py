"""The update pack lets an installed Ducky fetch one file by its byte range."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
import zlib
from pathlib import Path

RELEASE = Path(__file__).resolve().parents[1] / "release"


def _load():
    sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location("update_pack_test", RELEASE / "update_pack.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "UEFN-Ducky-1.2.410"
    (app / "_internal" / "frontend").mkdir(parents=True)
    (app / "UEFN-Ducky.exe").write_bytes(b"MZ" + os.urandom(5000))
    (app / "UEFN-Ducky-Bridge.exe").write_bytes(b"MZ" + b"same " * 4000)
    (app / "_internal" / "python313.dll").write_bytes(os.urandom(70_000))
    (app / "_internal" / "frontend" / "index.html").write_text("<!doctype html>" * 300, encoding="utf-8")
    (app / "_internal" / "empty.txt").write_bytes(b"")
    return app


def test_every_file_reads_back_from_its_byte_range(tmp_path):
    up = _load()
    app = _app(tmp_path)
    out = tmp_path / "dist"
    out.mkdir()
    (out / "UEFN-Ducky-Update-1.2.409.zip").write_bytes(b"old")
    (out / "UEFN-Ducky-Update-1.2.409-files.zip").write_bytes(b"old")
    (out / "UEFN-Ducky-Setup-1.2.410.exe").write_bytes(b"setup")

    pack, manifest_zip, manifest = up.build_update_pack(app, "1.2.410", out)

    assert pack.name == "UEFN-Ducky-Update-1.2.410.zip"
    assert manifest_zip.name == "UEFN-Ducky-Update-1.2.410-files.zip"
    assert sorted(p.name for p in out.iterdir()) == [
        "UEFN-Ducky-Setup-1.2.410.exe",
        "UEFN-Ducky-Update-1.2.410-files.zip",
        "UEFN-Ducky-Update-1.2.410.zip",
    ]
    with zipfile.ZipFile(manifest_zip) as bundle:
        assert json.loads(bundle.read("manifest.json")) == manifest
    assert manifest["version"] == "1.2.410"
    assert manifest["pack"]["size"] == pack.stat().st_size
    assert manifest["pack"]["sha256"] == hashlib.sha256(pack.read_bytes()).hexdigest()
    paths = [f["path"] for f in manifest["files"]]
    assert paths == sorted(paths)
    assert "_internal/frontend/index.html" in paths

    data = pack.read_bytes()
    for entry in manifest["files"]:
        raw = data[entry["offset"] : entry["offset"] + entry["csize"]]
        body = zlib.decompressobj(-15).decompress(raw) if entry["method"] == zipfile.ZIP_DEFLATED else raw
        assert len(body) == entry["size"], entry["path"]
        assert hashlib.sha256(body).hexdigest() == entry["sha256"], entry["path"]
        assert body == (app / entry["path"]).read_bytes()


def test_a_refused_pack_upload_releases_without_a_pack(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location("publish_app_pack_test", RELEASE / "publish_app.py")
    pub = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(pub)
    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    _load().build_update_pack(_app(tmp_path), "1.2.410", root / "dist")
    monkeypatch.setattr(pub, "ROOT", root)

    def refused(base, key, path):
        raise SystemExit("process failed: bad request: security scan blocked upload: hidden_characters")

    monkeypatch.setattr(pub, "upload_app_release", refused)
    assert pub.upload_update_pack("https://uefnducky.org", "key", "1.2.410") is None
    assert "released without a pack" in capsys.readouterr().out


def test_an_expired_upload_ticket_is_tried_again(tmp_path, monkeypatch):
    """The Setup and the pack alike: a fresh ticket after "ticket expired", any other
    refusal at once, and the last expiry is the error."""
    sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location("publish_app_ticket_test", RELEASE / "publish_app.py")
    pub = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(pub)
    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    _load().build_update_pack(_app(tmp_path), "1.2.410", root / "dist")
    setup = root / "dist" / "UEFN-Ducky-Setup-1.2.410.exe"
    setup.write_bytes(b"setup")
    monkeypatch.setattr(pub, "ROOT", root)
    expired = 'POST /api/v1/files/app-release/complete HTTP 400: {"error":"ticket expired"}'
    calls = []

    def expires_once(base, key, path):
        calls.append(path.name)
        if calls.count(path.name) == 1 and path.suffix in (".exe", ".zip") and "files" not in path.name:
            raise SystemExit(expired)
        return {"fileId": f"id-{len(calls)}", "sha256": pub.sha256_file(path)}

    monkeypatch.setattr(pub, "_upload_app_release_once", expires_once)
    assert pub.upload_app_release("https://uefnducky.org", "key", setup)["fileId"] == "id-2"
    update = pub.upload_update_pack("https://uefnducky.org", "key", "1.2.410")
    assert update is not None and update["packFileId"] == "id-4" and update["manifestFileId"] == "id-5"
    assert calls == ["UEFN-Ducky-Setup-1.2.410.exe"] * 2 + ["UEFN-Ducky-Update-1.2.410.zip"] * 2 + [
        "UEFN-Ducky-Update-1.2.410-files.zip"]

    def always(base, key, path):
        calls.append(path.name)
        raise SystemExit(expired)

    monkeypatch.setattr(pub, "_upload_app_release_once", always)
    calls.clear()
    try:
        pub.upload_app_release("https://uefnducky.org", "key", setup)
    except SystemExit as exc:
        assert "ticket expired" in str(exc)
    else:
        raise AssertionError("an upload that keeps expiring must fail")
    assert len(calls) == pub.UPLOAD_TRIES
