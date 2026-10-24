"""Host side: ``UEFN-Ducky.exe agent-host --slot N --pipe <name>`` (``python -m frontend agent-host`` from source).

Started only by the app's supervisor. Connects back over the pipe with the key in
``UEFN_DUCKY_HOST_KEY`` and runs until the app says ``shutdown`` or the pipe closes. It never
takes the single-instance lock, opens a window, applies IDE config or syncs skills.
Frames other than ``shutdown`` go to ``frontend.agent_host.turns.on_frame(channel, frame)``
once that module exists.
"""

from __future__ import annotations

import argparse
import os
import threading
from typing import Any

from frontend.agent_host import protocol
from frontend.agent_host.supervisor import KEY_ENV


def _turns_handler() -> Any:
    try:
        from frontend.agent_host import turns
    except ImportError:
        return None
    return getattr(turns, "on_frame", None)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="agent-host")
    ap.add_argument("--slot", required=True)
    ap.add_argument("--pipe", required=True)
    args = ap.parse_args(argv)
    key = bytes.fromhex(os.environ.pop(KEY_ENV, ""))  # never handed on to the CLIs this host starts
    done = threading.Event()
    box: list[protocol.Channel] = []
    handler = _turns_handler()

    def on_frame(frame: dict[str, Any]) -> None:
        if frame["op"] == "shutdown":
            done.set()
        elif handler is not None and box:
            handler(box[0], frame)

    box.append(protocol.connect_app(args.pipe, key, on_frame, lambda _reason: done.set()))
    done.wait()
    box[0].close("shutdown")
    return 0
