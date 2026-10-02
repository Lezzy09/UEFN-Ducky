"""42.30: Verse-field tools open the widget's editor once so fields are real — no Unreal required.

Without that the event field is a transient object: the Assets digest lists the widget with no
members and a click binding is saved with no target (verified live in UEFN 42.30, Oct 2 2026).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


class _Editors:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = False

    def open_editor_for_assets(self, assets):
        if self.fail:
            raise RuntimeError("no editor")
        self.calls += [("open", a.path) for a in assets]
        return True

    def close_all_editors_for_asset(self, asset):
        self.calls.append(("close", asset.path))


class _Asset:
    def __init__(self, path: str) -> None:
        self.path = path


@pytest.fixture()
def author(monkeypatch):
    editors = _Editors()
    unreal = types.ModuleType("unreal")
    unreal.AssetEditorSubsystem = object
    unreal.get_editor_subsystem = lambda cls: editors
    monkeypatch.setitem(sys.modules, "unreal", unreal)
    # listener.dispatch / listener.registry.umg_spec without the real (Unreal-importing) package.
    listener = types.ModuleType("listener")
    listener.__path__ = []
    dispatch = types.ModuleType("listener.dispatch")
    dispatch.register = lambda name: (lambda fn: fn)
    registry = types.ModuleType("listener.registry")
    registry.__path__ = []
    spec_mod = importlib.util.spec_from_file_location("listener.registry.umg_spec", _HERE / "registry" / "umg_spec.py")
    umg_spec = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(umg_spec)
    for name, mod in {"listener": listener, "listener.dispatch": dispatch, "listener.registry": registry,
                      "listener.registry.umg_spec": umg_spec}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("umg_author_under_test", _HERE / "registry" / "umg_author.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    open_now: list[str] = []
    mod._ref = lambda obj: f"{obj.path}.{obj.path.rsplit('/', 1)[-1]}"
    mod._open_asset_packages = lambda: set(open_now)
    return mod, editors, open_now


def test_opens_the_editor_once_then_remembers(author):
    mod, editors, _ = author
    wbp = _Asset("/Proj/UI/UW_Shop")
    assert mod.ensure_verse_fields_live(wbp) == "opened"
    assert editors.calls == [("open", "/Proj/UI/UW_Shop"), ("close", "/Proj/UI/UW_Shop")]
    assert mod.ensure_verse_fields_live(wbp) == "ready"
    assert len(editors.calls) == 2


def test_leaves_an_editor_the_user_has_open(author):
    mod, editors, open_now = author
    open_now.append("/Proj/UI/UW_Shop")
    assert mod.ensure_verse_fields_live(_Asset("/Proj/UI/UW_Shop")) == "already_open"
    assert editors.calls == []


def test_a_recreated_widget_is_opened_again(author):
    mod, editors, _ = author
    wbp = _Asset("/Proj/UI/UW_Shop")
    mod.ensure_verse_fields_live(wbp)
    mod.forget_verse_fields_live("/Proj/UI/UW_Shop")
    assert mod.ensure_verse_fields_live(wbp) == "opened"
    assert editors.calls.count(("open", "/Proj/UI/UW_Shop")) == 2


def test_a_failed_open_is_reported_and_retried(author):
    mod, editors, _ = author
    editors.fail = True
    wbp = _Asset("/Proj/UI/UW_Shop")
    assert mod.ensure_verse_fields_live(wbp).startswith("failed:")
    editors.fail = False
    assert mod.ensure_verse_fields_live(wbp) == "opened"


def test_bind_widget_event_makes_the_fields_live_before_binding(author, monkeypatch):
    mod, _, _ = author
    order: list[str] = []
    wbp = _Asset("/Proj/UI/UW_Shop")
    monkeypatch.setattr(mod, "_load_wbp", lambda path: wbp)
    monkeypatch.setattr(mod, "ensure_verse_fields_live", lambda w: order.append("live") or "opened")
    monkeypatch.setattr(mod, "_widget_object", lambda w, name: (object(), {"widgetClassPath": {"refPath": "/Script/UIFramework.UIFrameworkCustomButtonWidget"}}))
    monkeypatch.setattr(mod, "_ref_of", lambda node: node.get("refPath", "") if isinstance(node, dict) else "")
    monkeypatch.setattr(mod, "_field_names", lambda path: ["BuyClicked"])
    monkeypatch.setattr(mod, "_compile_checked", lambda w: {"compiled": True})

    class _MVVM:
        @staticmethod
        def create_view_event_binding(*args):
            order.append(f"bind:{args[2]}")
            return "event"

    monkeypatch.setattr(mod, "_mvvm", lambda: _MVVM)
    out = mod.bind_widget_event("/Proj/UI/UW_Shop", "BuyButton", "OnClicked", "BuyClicked")
    assert order == ["live", "bind:OnButtonClicked"]
    assert out["verse_ready"] == "opened" and out["event_name"] == "OnButtonClicked"
    assert "note" not in out
