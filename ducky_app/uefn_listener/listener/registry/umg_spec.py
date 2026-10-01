"""Pure widget-tree spec checks. No Unreal import — safe to unit test."""

from __future__ import annotations

from typing import Any

# Classes ListWidgetClasses marks as panels, plus the Fortnite buttons that
# host children (custom button is a panel). Leaves are everything we know
# cannot take children. Unknown classes may still be panels.
PANELS = frozenset(
    {
        "CanvasPanel",
        "GridPanel",
        "NamedSlot",
        "Overlay",
        "ScaleBox",
        "ScrollBox",
        "SizeBox",
        "StackBox",
        "UniformGridPanel",
        "WidgetSwitcher",
        "WrapBox",
        "UIFrameworkCustomButtonWidget",
        "CustomButton",
        "Border",
        "HorizontalBox",
        "VerticalBox",
    }
)

LEAVES = frozenset(
    {
        "Image",
        "TextBlock",
        "UIFrameworkTextBlock",
        "VerseFortniteUIFrameworkTextBlock",
        "CommonTextBlock",
        "Text",
        "Spacer",
        "CommonActionWidget",
        "ActionWidget",
        "DeveloperLayoutButtonProxy",
        "ProgressBar",
        "Slider",
    }
)


def validate_widget_tree_spec(spec: Any, *, where: str = "root") -> None:
    """Raise ValueError when a tree spec cannot be built.

    A node is ``{class, name, slot?, properties?, children?}``.
    Known leaves reject children. Known panels and unknown classes may nest.
    """
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: widget tree node must be an object")
    cls = str(spec.get("class") or "").strip()
    name = str(spec.get("name") or "").strip()
    if not cls:
        raise ValueError(f"{where}: widget tree node is missing class")
    if not name:
        raise ValueError(f"{where}: widget tree node is missing name")
    children = spec.get("children") or []
    if children is None:
        children = []
    if not isinstance(children, list):
        raise ValueError(f"{name}: children must be a list")
    if children and cls in LEAVES:
        raise ValueError(f"{name}: {cls} cannot contain children")
    for i, child in enumerate(children):
        validate_widget_tree_spec(child, where=f"{name}.children[{i}]")


# --------------------------------------------------------------------------- Verse fields (42.30)

# AddVerseField / EditVerseField `spec.type` values (GetSupportedVerseFieldTypes, 42.30).
# `logic` is Verse's bool.
FIELD_TYPES = {
    "bool": "bool",
    "logic": "bool",
    "int": "int",
    "float": "float",
    "string": "string",
    "message": "message",
    "color": "color",
    "color_alpha": "color_alpha",
    "texture": "texture",
    "material": "material",
    "event": "event",
}
# Event parameter types; VerseTypeEditor.MaxEventParametersNumberCreation is 1 in 42.30.
EVENT_PARAMETER_TYPES = {"bool": "bool", "logic": "bool", "int": "int", "float": "float"}
MAX_EVENT_PARAMETERS = 1
VISIBILITY = {"public": "Public", "internal": "Internal", "protected": "Protected", "private": "Private"}
BINDING_MODES = ("OneTimeToDestination", "OneWayToDestination", "TwoWay", "OneTimeToSource", "OneWayToSource")


def verse_field_spec(
    field_type: str,
    default_value: str = "",
    event_parameters: list[str] | None = None,
    mutable: bool = True,
    visibility: str = "public",
) -> dict[str, Any]:
    """The 42.30 VerseFieldSpec. Raises ValueError with a fix for anything UEFN would refuse."""
    kind = FIELD_TYPES.get((field_type or "").strip().lower())
    if kind is None:
        raise ValueError(f"field_type {field_type!r} is not supported. Use one of {sorted(set(FIELD_TYPES.values()))}.")
    vis = VISIBILITY.get((visibility or "public").strip().lower())
    if vis is None:
        raise ValueError(f"visibility {visibility!r} must be one of {sorted(VISIBILITY)}.")
    params: list[str] = []
    if kind == "event":
        for raw in event_parameters or []:
            mapped = EVENT_PARAMETER_TYPES.get(str(raw).strip().lower())
            if mapped is None:
                raise ValueError(f"event parameter {raw!r} must be bool, int or float.")
            params.append(mapped)
        if len(params) > MAX_EVENT_PARAMETERS:
            raise ValueError(
                f"An event field takes at most {MAX_EVENT_PARAMETERS} parameter in UEFN 42.30 "
                "(VerseTypeEditor.MaxEventParametersNumberCreation). Use one int (an index) instead."
            )
    elif event_parameters:
        raise ValueError("event_parameters only apply to field_type 'event'.")
    return {
        "type": kind,
        "eventParameterTypes": params,
        # Events have no default and are never `var`.
        "defaultValue": "" if kind == "event" else ("" if default_value is None else str(default_value)),
        "visibility": vis,
        "writeAccess": "",
        "bIsVar": False if kind == "event" else bool(mutable),
    }


# Custom Button (UIFrameworkCustomButtonWidget) events that compile as MVVM event
# sources in 42.30. OnClicked / OnPressed / OnReleased / OnHovered / OnUnhovered are
# listed by ListWidgetViewEvents but fail the blueprint compile ("property path is invalid").
BUTTON_EVENTS = ("OnButtonClicked", "OnButtonHighlight", "OnButtonUnhighlight")
_BUTTON_EVENT_ALIASES = {
    "onclicked": "OnButtonClicked",
    "onclick": "OnButtonClicked",
    "clicked": "OnButtonClicked",
    "onpressed": "OnButtonClicked",
    "onreleased": "OnButtonClicked",
    "onhovered": "OnButtonHighlight",
    "onhighlight": "OnButtonHighlight",
    "onunhovered": "OnButtonUnhighlight",
    "onunhighlight": "OnButtonUnhighlight",
}


def button_event_name(event_name: str, widget_class: str = "") -> str:
    """The event name that compiles for this widget (Custom Button names are remapped)."""
    name = (event_name or "").strip()
    if "CustomButton" not in (widget_class or "") and widget_class:
        return name
    if name in BUTTON_EVENTS:
        return name
    return _BUTTON_EVENT_ALIASES.get(name.lower(), name)
