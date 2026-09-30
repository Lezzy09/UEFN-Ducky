"""Tree-spec validator. No Unreal.

Loads umg_spec.py by path so listener.registry's unreal imports stay out.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = Path(__file__).resolve().parent / "registry" / "umg_spec.py"
_spec = importlib.util.spec_from_file_location("umg_spec_standalone", _SPEC)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
validate_widget_tree_spec = _mod.validate_widget_tree_spec


def test_rejects_empty_class():
    with pytest.raises(ValueError, match="missing class"):
        validate_widget_tree_spec({"class": "", "name": "Root"})


def test_rejects_leaf_parent():
    with pytest.raises(ValueError, match="cannot contain children"):
        validate_widget_tree_spec(
            {
                "class": "Image",
                "name": "Icon",
                "children": [{"class": "TextBlock", "name": "Label"}],
            }
        )


def test_accepts_canvas_with_child():
    validate_widget_tree_spec(
        {
            "class": "CanvasPanel",
            "name": "Root",
            "children": [
                {
                    "class": "Image",
                    "name": "Fill",
                    "slot": {"z_order": 0, "anchors": {"min": [0, 0], "max": [1, 1]}},
                }
            ],
        }
    )
