"""stop_listener releases the port — no Unreal required.

Regression: stop_listener only called ``shutdown()``, which ends serve_forever but
leaves the listening socket bound. On Windows the next start (reload_listener,
or the second init_unreal boot) bound the same port beside the orphan via
SO_REUSEADDR, and connections that landed on the orphan hung until timeout.
"""

from __future__ import annotations

import socket
import sys
import types
from pathlib import Path

import pytest

_LISTENER_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def runtime(monkeypatch):
    unreal = types.ModuleType("unreal")
    unreal.log = unreal.log_warning = unreal.log_error = lambda *_a, **_k: None
    unreal.register_slate_post_tick_callback = lambda _fn: object()
    unreal.unregister_slate_post_tick_callback = lambda _h: None
    monkeypatch.setitem(sys.modules, "unreal", unreal)

    for name in [m for m in sys.modules if m == "listener" or m.startswith("listener.")]:
        monkeypatch.delitem(sys.modules, name)
    # The real tick and status window pull in the whole editor surface (and Tk).
    tick = types.ModuleType("listener.tick")
    tick.tick_handler = lambda _dt: None
    status_window = types.ModuleType("listener.status_window")
    status_window.MCPStatusWindow = object
    monkeypatch.setitem(sys.modules, "listener.tick", tick)
    monkeypatch.setitem(sys.modules, "listener.status_window", status_window)
    monkeypatch.setattr(sys, "path", [str(_LISTENER_ROOT), *sys.path])

    import listener.runtime as rt

    yield rt
    if unreal._mcp_server is not None:
        rt.stop_listener()


def test_stop_closes_listening_socket(runtime, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("UEFN_DUCKY_LISTENER_PORT", str(port))
    assert runtime.start_listener(show_status=False) == port
    server = sys.modules["unreal"]._mcp_server

    runtime.stop_listener()

    assert server.socket.fileno() == -1
    # A bind WITHOUT SO_REUSEADDR only succeeds once nothing holds the port.
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_restart_serves_on_same_port(runtime, monkeypatch):
    import json
    import urllib.request

    port = _free_port()
    monkeypatch.setenv("UEFN_DUCKY_LISTENER_PORT", str(port))
    runtime.start_listener(show_status=False)
    runtime.stop_listener()
    runtime.start_listener(show_status=False)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as resp:
        assert json.load(resp)["status"] == "ok"
