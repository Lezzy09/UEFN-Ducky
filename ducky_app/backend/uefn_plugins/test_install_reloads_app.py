"""A plugin installed from the agents' tool server is loaded in the app process too, and a
plugin whose folders moved (its reload epoch) reloads in another process before that
process runs its next tool call."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from backend.uefn_plugins import store
from frontend.ui_web import agent_modes


class _SyncThread:
    def __init__(self, target, args=(), **_kwargs):
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


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


# --------------------------------------------------------------------------- a moved epoch in a second process

APP_DIR = str(Path(__file__).resolve().parents[2])
PROBE = "folder-probe"

_PROBE_BACKEND = '''
import os
import time

LOADED = time.time_ns()


def register(api):
    path = os.path.join(os.environ["LOCALAPPDATA"], "probe-loads.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write("load\\n")

    @api.tool(name="folder_probe_count", listener=False)
    def folder_probe_count() -> dict:
        with open(path, encoding="utf-8") as f:
            return {"loads": len(f.read().splitlines()), "module": LOADED}
'''

# The MCP bridge: loads the plugin once, then runs its tool once per line on stdin.
_BRIDGE = '''
import json, os, sys
sys.path.insert(0, {app!r})
os.environ["UEFN_DUCKY_MCP_BRIDGE"] = "1"
from backend.uefn_plugins import host
from backend.uefn_plugins.store import load_plugin_manifest, plugin_dir
host.get_enabled_plugin_ids = lambda: [{pid!r}]
host._load_one({pid!r}, plugin_dir({pid!r}), load_plugin_manifest({pid!r}))
from backend.server import mcp
print(json.dumps({{"ready": True}}), flush=True)
for _line in sys.stdin:
    try:
        out = mcp._tool_manager.get_tool("folder_probe_count").fn()
    except Exception as exc:
        out = {{"error": str(exc)}}
    print(json.dumps(out), flush=True)
'''


@pytest.mark.skipif(sys.platform != "win32", reason="team folders are NTFS junctions")
def test_a_bumped_epoch_reloads_the_plugin_in_another_process_before_its_next_call() -> None:
    from backend.store.repos import folder_files

    root = store.plugin_dir(PROBE)
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text(_PROBE_BACKEND, encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({
        "id": PROBE, "kind": "plugin", "version": "1.0.0", "label": "Folder probe",
        "team_folders": [{"id": "scenes", "root": "{LOCALAPPDATA}/UEFN-Ducky/folder-probe/scenes", "unit": "*"}],
    }), encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-c", _BRIDGE.format(app=APP_DIR, pid=PROBE)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env={**os.environ})

    def call() -> dict:
        proc.stdin.write("call\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    try:
        assert json.loads(proc.stdout.readline()) == {"ready": True}
        first = call()
        assert first["loads"] == 1
        assert call() == first  # nothing moved: the same plugin
        folder_files.reload_bump(PROBE, "pull")  # another process re-pointed its folders
        moved = call()
        assert moved["loads"] == 2 and moved["module"] != first["module"]  # reloaded before the call ran
        assert call() == moved  # once
    finally:
        proc.stdin.close()
        proc.kill()
        proc.wait(10)


def test_the_app_restarts_a_plugin_whose_folders_moved_once_its_calls_are_done(monkeypatch) -> None:
    from backend.store.repos import folder_files
    from backend.uefn_plugins import host, team_folders

    restarted: list[str] = []
    monkeypatch.setattr(host, "_restart_moved", restarted.append)  # reload_single_plugin, then panels
    monkeypatch.setitem(host._FOLDER_EPOCH, PROBE, folder_files.reload_epoch(PROBE))
    assert host.reload_moved_plugins(100.0) == []  # nothing moved
    folder_files.reload_bump(PROBE, "pull")  # a pull in this or another process
    assert host.reload_moved_plugins(100.0) == []  # a switch restarts it itself first
    calls = [{"key": "k"}]
    monkeypatch.setattr(team_folders, "live_calls", lambda pid: calls)
    assert host.reload_moved_plugins(100.0 + host.FOLDER_RELOAD_GRACE_S) == []  # a call still runs
    calls.clear()
    assert host.reload_moved_plugins(100.0 + host.FOLDER_RELOAD_GRACE_S) == [PROBE]
    for _ in range(100):  # the restart runs on its own thread
        if restarted:
            break
        time.sleep(0.05)
    assert restarted == [PROBE] and PROBE not in host._FOLDER_EPOCH  # its load records the epoch again
    assert host.reload_moved_plugins(200.0) == []
