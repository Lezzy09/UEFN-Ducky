"""Render trim: a redraw burst after captures/heavy commands, never touching realtime."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


class _FakeSubsystem:
    def __init__(self) -> None:
        self.invalidations = 0
        self.realtime_calls = 0

    def editor_invalidate_viewports(self) -> None:
        self.invalidations += 1

    def editor_set_viewport_realtime(self, _on: bool) -> None:  # must never be called
        self.realtime_calls += 1


def _load(fake_sub):
    unreal = types.ModuleType("unreal")
    unreal.LevelEditorSubsystem = type("LevelEditorSubsystem", (), {})
    unreal.get_editor_subsystem = lambda _cls: fake_sub
    unreal.EditorLevelLibrary = types.SimpleNamespace(editor_invalidate_viewports=lambda: None)
    sys.modules["unreal"] = unreal
    path = Path(__file__).resolve().parent / "render_trim.py"
    spec = importlib.util.spec_from_file_location("render_trim_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sub():
    return _FakeSubsystem()


def test_burst_redraws_once_per_tick_then_goes_quiet(sub):
    mod = _load(sub)
    assert mod.pending() == 0
    mod.tick()
    assert sub.invalidations == 0  # idle ticks cost nothing
    mod.request_trim(3)
    for _ in range(10):
        mod.tick()
    assert sub.invalidations == 3
    assert mod.pending() == 0
    assert sub.realtime_calls == 0  # the user's realtime setting is never changed


def test_requests_extend_but_never_stack(sub):
    mod = _load(sub)
    mod.request_trim(5)
    mod.tick()
    mod.request_trim(5)  # a second capture mid-burst
    assert mod.pending() == 5
    mod.request_trim(2)  # a shorter request never cuts a burst short
    assert mod.pending() == 5
    assert mod.TRIM_TICKS == 60


def test_fallback_to_level_library_when_no_subsystem():
    calls = []
    unreal = types.ModuleType("unreal")
    unreal.LevelEditorSubsystem = type("LevelEditorSubsystem", (), {})
    unreal.get_editor_subsystem = lambda _cls: None
    unreal.EditorLevelLibrary = types.SimpleNamespace(editor_invalidate_viewports=lambda: calls.append(1))
    sys.modules["unreal"] = unreal
    path = Path(__file__).resolve().parent / "render_trim.py"
    spec = importlib.util.spec_from_file_location("render_trim_under_test_fb", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.request_trim(2)
    mod.tick()
    mod.tick()
    assert calls == [1, 1]


def test_a_failing_redraw_ends_the_burst_quietly(sub):
    mod = _load(sub)

    def boom():
        raise RuntimeError("no viewport")

    sub.editor_invalidate_viewports = boom
    mod.request_trim(10)
    mod.tick()
    assert mod.pending() == 0
    mod.tick()  # stays quiet afterwards
