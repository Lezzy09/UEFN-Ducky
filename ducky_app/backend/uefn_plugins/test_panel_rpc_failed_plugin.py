"""A panel polling a plugin that fails to load doesn't reload it on every call, and
hears why it failed instead of "Unknown panel RPC" (Account polled account.status every
2 s, re-importing the plugin and logging a load error each time)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.uefn_plugins import host, store


def test_a_failed_plugin_is_retried_on_the_backoff_and_says_why(monkeypatch, tmp_path: Path) -> None:
    loads: list[str] = []

    def failing_load(pid, root, manifest):
        loads.append(pid)
        host._LOAD_FAILURES[pid] = "LicenseError: This copy isn't licensed for this PC"

    monkeypatch.setattr(host, "is_plugin_enabled", lambda pid: True)
    monkeypatch.setattr(host, "wait_plugin_toggles", lambda timeout=0: None)
    monkeypatch.setattr(host, "_load_enabled_plugin", failing_load)
    monkeypatch.setattr(store, "load_plugin_manifest", lambda pid: {"id": pid})
    monkeypatch.setattr(store, "plugin_dir", lambda pid: tmp_path)
    monkeypatch.setattr(host, "_PANEL_RPC", {})
    monkeypatch.setattr(host, "_LOAD_FAILURES", {})
    monkeypatch.setattr(host, "_REPAIR_ATTEMPTS", {})

    for _ in range(3):
        with pytest.raises(ValueError, match="didn't load: LicenseError"):
            host.call_panel_rpc("account", "status")
    assert loads == ["account"]

    host._REPAIR_ATTEMPTS["account"] -= host._REPAIR_BACKOFF_S
    with pytest.raises(ValueError):
        host.call_panel_rpc("account", "status")
    assert loads == ["account", "account"]
