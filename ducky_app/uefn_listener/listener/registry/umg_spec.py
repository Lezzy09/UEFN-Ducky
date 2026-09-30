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
