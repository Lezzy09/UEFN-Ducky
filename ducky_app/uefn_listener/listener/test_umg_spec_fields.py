"""42.30 Verse field specs and Custom Button event names — no Unreal required."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent / "registry" / "umg_spec.py"
_spec = importlib.util.spec_from_file_location("umg_spec_under_test", _PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_value_field_spec_matches_42_30_shape():
    assert mod.verse_field_spec("logic", "true") == {
        "type": "bool", "eventParameterTypes": [], "defaultValue": "true",
        "visibility": "Public", "writeAccess": "", "bIsVar": True,
    }
    assert mod.verse_field_spec("int", "3", mutable=False, visibility="private")["visibility"] == "Private"
    assert mod.verse_field_spec("int", "3", mutable=False)["bIsVar"] is False


def test_event_fields_take_one_parameter_and_no_default():
    spec = mod.verse_field_spec("event", "ignored", event_parameters=["logic"])
    assert spec["type"] == "event" and spec["eventParameterTypes"] == ["bool"]
    assert spec["defaultValue"] == "" and spec["bIsVar"] is False
    assert mod.verse_field_spec("event")["eventParameterTypes"] == []
    with pytest.raises(ValueError, match="at most 1"):
        mod.verse_field_spec("event", event_parameters=["int", "bool"])
    with pytest.raises(ValueError, match="bool, int or float"):
        mod.verse_field_spec("event", event_parameters=["string"])
    with pytest.raises(ValueError, match="only apply"):
        mod.verse_field_spec("int", event_parameters=["int"])
    with pytest.raises(ValueError, match="not supported"):
        mod.verse_field_spec("vector3")


def test_custom_button_events_use_the_names_that_compile():
    cb = "/Script/UIFramework.UIFrameworkCustomButtonWidget"
    assert mod.button_event_name("OnClicked", cb) == "OnButtonClicked"
    assert mod.button_event_name("OnHovered", cb) == "OnButtonHighlight"
    assert mod.button_event_name("OnUnhovered", cb) == "OnButtonUnhighlight"
    assert mod.button_event_name("OnButtonHighlight", cb) == "OnButtonHighlight"
    # Unknown class: still remap (most bound buttons are Custom Buttons).
    assert mod.button_event_name("OnClicked") == "OnButtonClicked"
    # Other widget classes keep their own event names.
    assert mod.button_event_name("OnClicked", "/Script/UMG.Button") == "OnClicked"
