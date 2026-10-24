"""App boot starts the meters once, right after the main window exists."""

from __future__ import annotations

import ast
import logging
import sys
import types
from pathlib import Path

_APP = Path(__file__).with_name("webview_app.py")
_TREE = ast.parse(_APP.read_text(encoding="utf-8"))


def _calls(name: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(_TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == name
    ]


def _function(name: str):
    node = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace: dict[str, object] = {"logging": logging}
    exec(compile(ast.Module([node], []), str(_APP), "exec"), namespace)
    return namespace[name]


def test_boot_starts_the_meters_once_after_the_window_is_created() -> None:
    (start,) = _calls("_start_boot_meters")
    (create,) = [c for c in _calls("create_window")]
    assert start.lineno > create.lineno


def test_the_core_wait_meter_and_heartbeat_start(monkeypatch) -> None:
    started: list[str] = []
    health = types.SimpleNamespace(start_core_wait=lambda: started.append("core_wait"))
    monkeypatch.setitem(sys.modules, "frontend.self_health", health)
    import frontend
    import frontend.boot_report as boot_report

    monkeypatch.setattr(frontend, "self_health", health, raising=False)
    monkeypatch.setattr(boot_report, "start_heartbeat", lambda agents: started.append("heartbeat"))
    _function("_start_boot_meters")()
    assert started == ["core_wait", "heartbeat"]


def test_a_failing_meter_never_blocks_boot(monkeypatch) -> None:
    def boom() -> None:
        raise RuntimeError("no meter")

    health = types.SimpleNamespace(start_core_wait=boom)
    monkeypatch.setitem(sys.modules, "frontend.self_health", health)
    import frontend

    monkeypatch.setattr(frontend, "self_health", health, raising=False)
    _function("_start_boot_meters")()  # logs, never raises


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
