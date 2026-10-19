"""ducky_plugin_test on tools and nodes that wait by design (a timeout parameter):
they get a short timeout and pass when they give up cleanly; a real hang still fails."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from backend.tools.panel import panel_plugin_check as check


def _waiter(timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        time.sleep(0.02)
    return {"ok": True, "found": False, "timed_out": True}


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    monkeypatch.setattr(check, "_WAIT_TEST_S", 0.2)
    monkeypatch.setattr(check, "_TOOL_TIMEOUT_S", 1.5)
    release = threading.Event()
    yield release
    release.set()  # lets the hung worker end


def test_short_timeouts_only_touch_numeric_timeout_fields() -> None:
    fields = {
        "timeout_sec": {"type": "number", "default": 180},
        "timeout_ms": {"type": "integer"},
        "Timeout": {"type": ["number", "null"]},
        "timeout_label": {"type": "number"},
        "timeout_s": {"type": "string"},
        "pattern": {"type": "string"},
    }
    got = check.short_timeouts(fields)
    assert got == {"timeout_sec": check._WAIT_TEST_S, "timeout_ms": check._WAIT_TEST_S * 1000,
                   "Timeout": check._WAIT_TEST_S}
    assert check.short_timeouts(None) == {}


def test_a_waiting_tool_gets_a_short_timeout_and_a_hang_still_fails(quick, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.uefn_plugins import host

    def wait(pattern: str, timeout_sec: float = 180.0) -> dict[str, Any]:
        return _waiter(timeout_sec)

    def hang(pattern: str) -> dict[str, Any]:
        quick.wait(30)
        return {"ok": True}

    def schema(**props: Any) -> dict[str, Any]:
        return {"type": "object", "properties": {"pattern": {"type": "string"}, **props}, "required": ["pattern"]}

    tools = {
        "demo_wait": SimpleNamespace(fn=wait, parameters=schema(timeout_sec={"type": "number", "default": 180})),
        "demo_hang": SimpleNamespace(fn=hang, parameters=schema()),
    }
    monkeypatch.setattr(host, "get_contributions", lambda: {"agent_tools": {"demo": {"tools": list(tools)}}})
    monkeypatch.setattr(check.mcp._tool_manager, "get_tool", lambda name: tools.get(name))

    checks: list[dict[str, Any]] = []
    stragglers: list[threading.Thread] = []
    check._check_tools("demo", checks, stragglers)
    rows = {c["check"]: c for c in checks}

    waited = rows["tool demo_wait"]
    assert waited["status"] == "pass", waited
    assert waited["input"] == {"pattern": "", "timeout_sec": check._WAIT_TEST_S}
    assert "timed_out" in waited["result"] and "note" not in waited
    hung = rows["tool demo_hang"]
    assert hung["status"] == "fail" and "TimeoutError" in hung["detail"]
    assert len(stragglers) == 1


def test_a_waiting_node_gets_a_short_timeout_in_its_config(quick, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.automations import plugin

    seen: list[dict[str, Any]] = []

    def node_wait(ctx: dict[str, Any]) -> dict[str, Any]:
        seen.append(dict(ctx["config"]))
        return _waiter(ctx["config"].get("timeout_sec") or 180)

    monkeypatch.setattr(plugin, "node_types", lambda: [("demo.wait", "demo")])
    monkeypatch.setattr(plugin, "get_handler", lambda ntype: node_wait if ntype == "demo.wait" else None)
    manifest = {"contributes": {"automations": {"nodes": [{"id": "demo.wait", "config_fields": [
        {"id": "pattern", "type": "string", "default": "arrived"},
        {"id": "timeout_sec", "type": "number", "default": 180},
    ]}]}}}

    checks: list[dict[str, Any]] = []
    check._check_nodes("demo", manifest, checks, [])

    assert seen == [{"pattern": "arrived", "timeout_sec": check._WAIT_TEST_S}]
    assert checks[0]["status"] == "pass" and "waits by design" in checks[0]["detail"], checks
