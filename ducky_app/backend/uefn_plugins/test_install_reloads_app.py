"""A plugin installed from the agents' tool server is loaded in the app process too."""

from __future__ import annotations

import json
import threading

from backend.uefn_plugins import store
from frontend.ui_web import agent_modes


class _SyncThread:
    def __init__(self, target, **_kwargs):
        self._target = target

    def start(self) -> None:
        self._target()


def _capture_posts(monkeypatch) -> list[tuple[str, list]]:
    posts: list[tuple[str, list]] = []

    class _Reply:
        def read(self) -> bytes:
            return b'{"ok": true}'

    def _urlopen(req, timeout=0):
        posts.append((req.full_url, json.loads(req.data)["args"]))
        return _Reply()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    monkeypatch.setattr(threading, "Thread", _SyncThread)
    return posts


def test_tool_server_install_asks_the_app_to_reload(monkeypatch) -> None:
    posts = _capture_posts(monkeypatch)
    monkeypatch.setattr(agent_modes, "_in_bridge_process", lambda: True)
    store._reload_in_app_process("island-media-kit")
    assert len(posts) == 1
    url, args = posts[0]
    assert url.endswith("/__panel_api/reload_uefn_plugin")
    assert args == ["island-media-kit"]


def test_the_app_itself_does_not_call_itself(monkeypatch) -> None:
    posts = _capture_posts(monkeypatch)
    monkeypatch.setattr(agent_modes, "_in_bridge_process", lambda: False)
    store._reload_in_app_process("island-media-kit")
    assert posts == []
