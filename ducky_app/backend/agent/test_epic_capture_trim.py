"""A viewport capture through Epic's MCP asks the listener for the redraw burst."""

from __future__ import annotations

import backend.agent.tools as tools


def test_detects_epic_capture_calls_only():
    assert tools.is_epic_capture_call(
        "unreal__call_tool",
        {"toolset_name": "EditorToolset.EditorAppToolset", "tool_name": "CaptureViewport"},
    )
    assert tools.is_epic_capture_call(
        "mcp__unreal__call_tool", {"tool_name": "EditorToolset.EditorAppToolset.CaptureViewport"}
    )
    assert not tools.is_epic_capture_call("unreal__call_tool", {"tool_name": "SetCameraTransform"})
    assert not tools.is_epic_capture_call("unreal__describe_toolset", {"tool_name": "CaptureViewport"})
    assert not tools.is_epic_capture_call("take_high_res_screenshot", {})
    assert not tools.is_epic_capture_call("", {})
    assert not tools.is_epic_capture_call("unreal__call_tool", {})


def test_trim_request_is_fire_and_forget(monkeypatch):
    sent: list[tuple[str, dict]] = []
    import threading

    done = threading.Event()

    def fake_send(cmd, params, timeout=0.0):
        sent.append((cmd, params))
        done.set()
        return {"ticks": 60}

    monkeypatch.setattr("backend.bridge.send_command", fake_send)
    tools._request_render_trim()
    assert done.wait(5)
    assert sent == [("render_trim", {})]


def test_trim_request_swallows_an_offline_listener(monkeypatch):
    import threading

    done = threading.Event()

    def boom(*_a, **_k):
        done.set()
        raise RuntimeError("listener offline")

    monkeypatch.setattr("backend.bridge.send_command", boom)
    tools._request_render_trim()  # must not raise, must not block
    assert done.wait(5)
