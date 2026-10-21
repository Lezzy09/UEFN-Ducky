#!/usr/bin/env python3
"""Build the web installer: dist/UEFN-Ducky-WebSetup.exe (about 1.4 MB; the full Setup is ~170 MB).

It is the Ducky Setup host with no engine inside. Install asks the Store for the
latest release, downloads that release's full Setup, checks its size, SHA-256 and
Authenticode signer, then runs it silently the way the in-app updater does, with
the progress in its own window. It always installs the newest release, so it is
rebuilt only when the host or its page changes, not on every release.

    py release/build_web_setup.py              # build + sign (signing must be set up)
    py release/build_web_setup.py --check      # then download + check the latest Setup with it
    py release/build_web_setup.py --no-sign    # local try-out only, never publish it
    py release/build_web_setup.py --check --upload   # build, check, then put it on the site

--check runs the built EXE with /CHECKDOWNLOAD: it downloads and verifies the Store's
latest full Setup, prints "ok <version> <bytes> <sha256>", deletes it and installs nothing.

--upload replaces web-setup/UEFN-Ducky-Setup.exe in the site's public storage (same file
id, so the Download button's link /api/v1/files/<id>/content keeps working). It is kept
out of app-releases/: an .exe uploaded there pushes out an old Setup restore slot.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ducky_app" / "frontend" / "ui_web" / "web" / "public"
OUT = ROOT / "dist" / "UEFN-Ducky-WebSetup.exe"
SMALL_PUBLIC = ROOT / "dist" / "web-setup-public"

# The page shows the logo at 92 px and the ducks at up to 56 px; twice that covers
# 200% displays. The panel's originals are ~350 KB each, most of the EXE.
IMAGES = {
    "OnlineMCPIcon.png": 256,
    "duckies/Artist.png": 160,
    "duckies/cowboy.png": 160,
    "duckies/hacker.png": 160,
    "duckies/wizard.png": 160,
}


def shrink_images(dest: Path) -> None:
    from PIL import Image

    if dest.exists():
        shutil.rmtree(dest)
    for rel, size in IMAGES.items():
        src = PUBLIC / rel
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGBA")
            img.thumbnail((size, size), Image.LANCZOS)
            img.save(out, "PNG", optimize=True)
        print(f"  {rel}: {src.stat().st_size // 1024} KB -> {out.stat().st_size // 1024} KB")


def sign(path: Path) -> None:
    print("=== Authenticode sign (web Setup) ===")
    subprocess.run(
        [sys.executable, str(ROOT / "release" / "sign_windows.py"), "--require", str(path)],
        check=True,
        cwd=str(ROOT),
    )


def check(path: Path) -> None:
    print("=== Download + check the Store's latest Setup (installs nothing) ===")
    proc = subprocess.run([str(path), "/CHECKDOWNLOAD"], capture_output=True, text=True, timeout=1800)
    out = (proc.stdout or "").strip()
    print(f"  {out}")
    if proc.returncode != 0 or not out.startswith("ok "):
        raise SystemExit("The web Setup couldn't download and check the latest release.")


def upload(path: Path) -> None:
    import base64

    sys.path.insert(0, str(ROOT / "release"))
    import publish_app

    print("=== Upload to the site (web-setup/UEFN-Ducky-Setup.exe) ===")
    base, key = publish_app.ensure_store_env()
    result = publish_app.mcp_call(base, key, "storage_upload", {
        "filename": "UEFN-Ducky-Setup.exe",
        "prefix": "web-setup",
        "namespace": "media",
        "public": True,
        "replace": True,
        "mimeType": "application/octet-stream",
        "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
    })
    file = result.get("file") or {}
    if not result.get("ok") or not file.get("id"):
        raise SystemExit(f"Upload failed: {result}")
    print(f"  {base}/api/v1/files/{file['id']}/content  ({file.get('sizeBytes')} bytes, sha256 {file.get('sha256')})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-sign", action="store_true", help="Skip signing (local try-out; never publish it)")
    parser.add_argument("--check", action="store_true", help="Download and check the latest Setup with the built EXE")
    parser.add_argument("--upload", action="store_true", help="Replace the web installer on the site (signed builds only)")
    args = parser.parse_args()
    if args.upload and args.no_sign:
        raise SystemExit("--upload needs a signed build: drop --no-sign.")

    print("=== Small page images ===")
    shrink_images(SMALL_PUBLIC)
    print("=== Ducky Setup host (web) ===")
    subprocess.run(
        [
            "powershell", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "release" / "installer" / "make_release_installer.ps1"),
            "-Web", "-PublicDir", str(SMALL_PUBLIC),
        ],
        check=True,
        cwd=str(ROOT),
    )
    if not OUT.is_file():
        raise SystemExit(f"The host build did not produce {OUT}")
    if not args.no_sign:
        sign(OUT)
    shutil.rmtree(SMALL_PUBLIC, ignore_errors=True)
    print(f"Built {OUT.name}: {OUT.stat().st_size:,} bytes")
    if args.check:
        check(OUT)
    if args.upload:
        upload(OUT)


if __name__ == "__main__":
    main()
