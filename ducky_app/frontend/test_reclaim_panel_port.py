"""Opening Ducky closes a stuck copy that still holds the panel port."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from frontend import frozen_process


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only reclaim")
def test_only_a_stuck_ducky_on_the_panel_port_is_closed(monkeypatch) -> None:
    import psutil

    names = {101: "UEFN-Ducky.exe", 102: "UEFN-Ducky-Setup-1.2.360.exe", 103: "python.exe", 104: "UEFN-Ducky.exe"}
    conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=4199), pid=101),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=4199), pid=102),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=4199), pid=103),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5000), pid=104),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": conns)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(name=lambda: names[pid]))
    killed: list[int] = []
    monkeypatch.setattr(frozen_process, "_kill_pid_tree", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(frozen_process, "_panel_answers", lambda port: False)

    assert frozen_process.reclaim_panel_port(4199) is True
    assert killed == [101]  # never Setup, never a dev server, never another port


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only reclaim")
def test_a_live_panel_that_answers_is_never_closed(monkeypatch) -> None:
    # Oct 21 2026: a Ducky started with another AppData killed the person's busy, live panel.
    import http.server
    import threading

    import psutil

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    conns = [SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=port), pid=101)]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": conns)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(name=lambda: "UEFN-Ducky.exe"))
    killed: list[int] = []
    monkeypatch.setattr(frozen_process, "_kill_pid_tree", lambda pid: killed.append(pid) or True)
    try:
        assert frozen_process.reclaim_panel_port(port) is False  # it answered (501): alive
        assert killed == []
    finally:
        server.shutdown()
        server.server_close()
