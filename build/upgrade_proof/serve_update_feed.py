"""Local stand-in for the DuckyOS Store app-version feed, for rehearsing the in-app update.

    py build/upgrade_proof/serve_update_feed.py dist/UEFN-Ducky-Setup-1.2.1.exe [--port 8765]

Then start the *installed* UEFN Ducky with the feed pointed here:

    set DUCKY_UPDATE_BASE_URL=http://127.0.0.1:8765
    "%LOCALAPPDATA%\\Programs\\UEFN Ducky\\UEFN-Ducky.exe"

Settings → General → App → "Check for updates" now sees the served version,
"Update now" downloads the installer from this server (sha256-verified),
runs it silently and relaunches — the exact production path, minus TLS,
which the updater only waives for 127.0.0.1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FEED_PATH = "/api/v1/plugins/uefn-ducky-store/collect/app-version"


def _version_from_name(name: str) -> str:
    m = re.search(r"(\d+\.\d+\.\d+)", name)
    if not m:
        raise SystemExit(f"cannot read a version from {name!r} (expected UEFN-Ducky-Setup-<x.y.z>.exe)")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("installer", help="the newer UEFN-Ducky-Setup-<version>.exe to offer")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--version", default="", help="override the version parsed from the file name")
    ap.add_argument("--notes", default="Local update rehearsal.")
    ap.add_argument(
        "--notes-file",
        type=Path,
        default=None,
        help="the short changes for What's new, as release/publish_app.py --notes-file takes them",
    )
    ap.add_argument(
        "--pack",
        type=Path,
        default=None,
        help="UEFN-Ducky-Update-<v>.zip from release/update_pack.py: offer it as the update pack "
        "(its -files.zip beside it), unsigned, which only a loopback feed may be",
    )
    args = ap.parse_args()

    installer = Path(args.installer).resolve()
    if not installer.is_file():
        raise SystemExit(f"not a file: {installer}")
    version = args.version or _version_from_name(installer.name)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    base = f"http://127.0.0.1:{args.port}"
    payload = {
        "currentVersion": version,
        "installerUrl": f"{base}/{installer.name}",
        "installerSha256": digest,
        "releaseNotes": args.notes,
    }
    if args.notes_file is not None:
        items = json.loads(args.notes_file.read_text(encoding="utf-8"))
        payload["versions"] = [
            {"version": version, "changelog": args.notes, "created_at": str(int(time.time())), "items": items}
        ]
    files = {f"/{installer.name}": installer.read_bytes()}
    if args.pack is not None:
        pack = args.pack.resolve()
        manifest = pack.with_name(pack.stem + "-files.zip")
        files[f"/{pack.name}"] = pack.read_bytes()
        files[f"/{manifest.name}"] = manifest.read_bytes()
        payload["update"] = {
            "version": version,
            "packUrl": f"/{pack.name}",
            "packSha256": hashlib.sha256(files[f"/{pack.name}"]).hexdigest(),
            "packSize": len(files[f"/{pack.name}"]),
            "manifestUrl": f"/{manifest.name}",
            "manifestSha256": hashlib.sha256(files[f"/{manifest.name}"]).hexdigest(),
            "signature": "",
            "issuedAt": int(time.time()),
        }
    body = json.dumps({"handled": True, "payload": payload}).encode("utf-8")
    data = files[f"/{installer.name}"]

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, content: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == FEED_PATH:
                self._send(200, body, "application/json")
            else:
                self._send(404, b"{}", "application/json")

        def do_GET(self) -> None:  # noqa: N802
            if self.path == FEED_PATH:
                self._send(200, body, "application/json")
                return
            content = files.get(self.path)
            if content is None:
                self._send(404, b"not found", "text/plain")
                return
            ranged = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range") or "")
            if not ranged:
                self._send(200, content, "application/octet-stream")
                return
            start, end = int(ranged.group(1)), min(int(ranged.group(2)), len(content) - 1)
            part = content[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(content)}")
            self.send_header("Content-Length", str(len(part)))
            self.end_headers()
            self.wfile.write(part)

        def log_message(self, fmt: str, *a: object) -> None:  # noqa: D401
            sys.stderr.write("  feed: " + (fmt % a) + "\n")

    print(f"serving version {version} from {installer.name} ({len(data) // (1024 * 1024)} MB)")
    print(f"  feed:      {base}{FEED_PATH}")
    print(f"  installer: {payload['installerUrl']}")
    print(f"  sha256:    {digest}")
    print()
    print(f"start the installed app with:  set DUCKY_UPDATE_BASE_URL={base}")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
