#!/usr/bin/env python3
"""Fetch the pinned search model into ``build/search-model/`` for PyInstaller.

Skill and tool search embeds text with a model2vec static model
(``minishlab/potion-base-8M``, MIT). It ships inside the app; nothing downloads at
runtime. This script downloads the model at a fixed commit, checks every file's
SHA-256, and writes what the embedder reads:

- ``embeddings.f16.npy`` — the token embedding matrix as float16 (half the size;
  the parity test bounds the difference)
- ``tokenizer.json`` and ``config.json`` — unchanged
- ``MODEL_CARD.md`` — the upstream README (license and attribution)
- ``manifest.json`` — model id, revision, dimension and the output SHA-256s

Running it twice gives identical files. ``DUCKY_SEARCH_MODEL_DIR`` may point at a
folder that already holds the upstream files (their SHA-256 is still checked).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import urllib.request
from pathlib import Path

MODEL_ID = "minishlab/potion-base-8M"
REVISION = "bf8b056651a2c21b8d2565580b8569da283cab23"
UPSTREAM_SHA256 = {
    "model.safetensors": "f65d0f325faadc1e121c319e2faa41170d3fa07d8c89abd48ca5358d9a223de2",
    "tokenizer.json": "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50",
    "config.json": "2a6ac0e9aaa356a68a5688070db78fc3a464fefe85d2f06a1905ce3718687553",
    "README.md": "de8ec91bf63c5f4c0e20751c227b2d049953e1cab5f8d5d44211c59a44795bdd",
}
OUTPUT_FILES = ("embeddings.f16.npy", "tokenizer.json", "config.json", "MODEL_CARD.md")

DEFAULT_DEST = Path(__file__).resolve().parent / "search-model"


class SearchModelError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _urlopen(req: urllib.request.Request):
    try:
        import ssl

        import truststore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return urllib.request.urlopen(req, timeout=120, context=ctx)
    except ImportError:
        return urllib.request.urlopen(req, timeout=120)


def _download(name: str, dest: Path) -> None:
    url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "UEFN-Ducky-build"})
    with _urlopen(req) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh, 1 << 20)


def _check(path: Path, name: str) -> None:
    want = UPSTREAM_SHA256[name]
    got = sha256_of(path)
    if not want:
        raise SearchModelError(f"{name}: no pinned SHA-256 (got {got}); pin it in fetch_search_model.py")
    if got != want:
        raise SearchModelError(f"{name}: SHA-256 mismatch (expected {want}, got {got})")


def read_safetensors_matrix(path: Path, key: str = "embeddings"):
    """The one tensor the embedder needs, read with numpy (no safetensors package)."""
    import numpy as np

    raw = path.read_bytes()
    (header_len,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + header_len])
    meta = header.get(key)
    if meta is None:
        names = sorted(k for k in header if k != "__metadata__")
        raise SearchModelError(f"{path.name}: no '{key}' tensor (has {names})")
    dtypes = {"F32": np.float32, "F16": np.float16, "I8": np.int8}
    dtype = dtypes.get(meta["dtype"])
    if dtype is None:
        raise SearchModelError(f"{path.name}: unsupported dtype {meta['dtype']}")
    start, end = meta["data_offsets"]
    base = 8 + header_len
    return np.frombuffer(raw[base + start : base + end], dtype=dtype).reshape(meta["shape"]), header


def _up_to_date(dest: Path) -> bool:
    manifest = dest / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if data.get("model") != MODEL_ID or data.get("revision") != REVISION:
        return False
    files = data.get("files") or {}
    return all((dest / name).is_file() and sha256_of(dest / name) == files.get(name) for name in OUTPUT_FILES)


def ensure_model(dest: Path = DEFAULT_DEST) -> Path:
    """Return ``dest`` holding the verified model files; raises on any mismatch."""
    import numpy as np

    dest = Path(dest)
    if _up_to_date(dest):
        return dest
    staging = dest.with_name(dest.name + ".tmp")
    upstream = dest.with_name(dest.name + ".download")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    upstream.mkdir(parents=True, exist_ok=True)
    try:
        local = os.environ.get("DUCKY_SEARCH_MODEL_DIR", "").strip()
        for name in UPSTREAM_SHA256:
            src = upstream / name
            if local:
                src = Path(local) / name
                if not src.is_file():
                    raise SearchModelError(f"DUCKY_SEARCH_MODEL_DIR is missing {name}")
            elif not (src.is_file() and UPSTREAM_SHA256[name] and sha256_of(src) == UPSTREAM_SHA256[name]):
                _download(name, src)
            _check(src, name)
        matrix, _ = read_safetensors_matrix((Path(local) if local else upstream) / "model.safetensors")
        if matrix.ndim != 2:
            raise SearchModelError(f"embedding matrix has shape {matrix.shape}")
        np.save(staging / "embeddings.f16.npy", matrix.astype(np.float16), allow_pickle=False)
        src_dir = Path(local) if local else upstream
        shutil.copyfile(src_dir / "tokenizer.json", staging / "tokenizer.json")
        shutil.copyfile(src_dir / "config.json", staging / "config.json")
        shutil.copyfile(src_dir / "README.md", staging / "MODEL_CARD.md")
        manifest = {
            "model": MODEL_ID,
            "revision": REVISION,
            "license": "MIT",
            "dim": int(matrix.shape[1]),
            "vocab": int(matrix.shape[0]),
            "files": {name: sha256_of(staging / name) for name in OUTPUT_FILES},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(staging, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(upstream, ignore_errors=True)
    return dest


def main() -> int:
    try:
        dest = ensure_model()
    except SearchModelError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"search model ready: {dest} ({MODEL_ID}@{REVISION[:10]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
