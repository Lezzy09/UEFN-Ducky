"""42.30 Verse field specs and Custom Button event names — no Unreal required."""

from __future__ import annotations

import importlib.util
import re
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


def test_designer_text_is_keyed_nsloctext():
    a, b = mod.nsloctext("Play"), mod.nsloctext("Play")
    assert a != b  # a fresh key each time
    assert re.fullmatch(r'NSLOCTEXT\("", "[0-9A-F]{32}", "Play"\)', a)
    # Quote, backslash and newline are escaped the way FText import text reads them back.
    assert mod.nsloctext('Say "hi"' + chr(92) + chr(10), key="K") == r'NSLOCTEXT("", "K", "Say \"hi\"\\\n")'
    assert mod.is_text_macro('NSLOCTEXT("", "K", "Play")') and mod.is_text_macro('INVTEXT("1")')
    assert not mod.is_text_macro("Play") and not mod.is_text_macro(None)


# Exported FMVVMBlueprintPropertyPath / FMVVMBlueprintPin text, copied from UEFN 42.30 (Oct 16 2026).
_NESTED_EVENT = (
    "(Paths=((BindingReference=(MemberParent=\"/Script/UMG.WidgetBlueprintGeneratedClass'/P/UI/UW_Button_Toggle"
    ".UW_Button_Toggle_C'\",MemberName=\"Main_Button\",MemberGuid=D050922049E67AD8C486D098F15D8641),"
    "BindingKind=Property),(BindingReference=(MemberParent=\"/Script/CoreUObject.Class'/Script/UIFramework."
    "UIFrameworkCustomButtonWidget'\",MemberName=\"OnButtonClicked\"),BindingKind=Property)),"
    "WidgetName=\"ToggleButton1\",ContextId=00000000000000000000000000000000,Source=Widget,bIsComponent=False,"
    "bDeprecatedSource=True)"
)
_SELF_FIELD = (
    "(Paths=((BindingReference=(MemberName=\"OnToggleButtonClicked\",MemberGuid=CAC4AED74AB76349D48E82A8B36A607B,"
    "bSelfContext=True))),WidgetName=\"\",ContextId=00000000000000000000000000000000,Source=SelfContext,"
    "bIsComponent=False,bDeprecatedSource=True)"
)
_PIN = (
    "(Id=(PinNames=(\"Param0\")),Path=(Paths=,WidgetName=\"\",ContextId=00000000000000000000000000000000,"
    "Source=None,bIsComponent=False,bDeprecatedSource=False),DefaultString=\"0\",DefaultText=\"\","
    "DefaultObject=None,bSplit=False,Status=Valid)"
)


def test_view_event_paths_read_back_as_dotted_paths():
    assert mod.property_path_text(_NESTED_EVENT) == "ToggleButton1.Main_Button.OnButtonClicked"
    assert mod.property_path_text(_SELF_FIELD) == "OnToggleButtonClicked"
    assert mod.property_path_text("") == ""
    assert mod.event_pin_values([_PIN]) == {"Param0": "0"}
    assert mod.event_pin_values([_PIN.replace('DefaultString="0"', 'DefaultString="2"')]) == {"Param0": "2"}
    assert mod.event_pin_values([]) == {}


def test_object_tool_listings_shrink_to_value_formats():
    listing = {
        "desiredFocusWidget": {"title": "WidgetChild", "type": "object",
                               "properties": {"widgetName": {"type": "string"}}, "required": ["widgetName"]},
        "visibility": {"type": "string", "title": "ESlateVisibility", "enum": ["Visible", "Collapsed"]},
        "bIsFocusable": {"type": "boolean", "description": "long text"},
        "padding": {"title": "Margin", "type": "object", "properties": {
            "left": {"type": "number"}, "inner": {"type": "object", "title": "Deep", "properties": {"x": {}}}}},
        "tags": {"type": "array", "items": {"type": "string"}},
    }
    assert mod.property_shapes(listing) == {
        "bIsFocusable": "boolean",
        "desiredFocusWidget": {"widgetName": "string"},
        "padding": {"left": "number", "inner": "Deep"},
        "tags": ["string"],
        "visibility": "Visible|Collapsed",
    }
    assert mod.property_shapes("not a listing") == {}
