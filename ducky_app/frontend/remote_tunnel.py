"""Remote Ducky has no tunnel: the phone connects to this PC directly (peer to peer,
frontend.remote_direct). The Cloudflare tunnel (cloudflared) is gone.

These do nothing. They stay only because Ducky Account 1.0.51 and older import this
module from their Browser access switch and sign-out; delete the module once every
supported Account version is 1.0.52 or newer.
"""

from __future__ import annotations

import threading
from typing import Any

_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def remote_tunnel_status() -> dict[str, Any]:
    return {"running": False, "error": ""}


def start_remote_tunnel() -> None:
    return None


def stop_remote_tunnel(*, deprovision: bool = False) -> None:
    return None


def kill_cloudflared() -> None:
    return None
