"""Three-way JSON merge: objects key by key, arrays by id, scalars both sides changed are
conflicts, atomic arrays, set arrays, and no base."""

from __future__ import annotations

from backend.uefn_plugins.json_merge import MISSING, merge, same


def test_disjoint_fields_merge() -> None:
    base = {"hp": 1, "name": "Pip", "tags": ["a"]}
    out = merge(base, {**base, "name": "Pipo"}, {**base, "hp": 2})
    assert out.clean and out.value == {"hp": 2, "name": "Pipo", "tags": ["a"]}


def test_nested_objects_merge_key_by_key() -> None:
    base = {"stats": {"hp": 1, "atk": 1}, "art": {"url": "a"}}
    theirs = {"stats": {"hp": 1, "atk": 5}, "art": {"url": "a"}}
    mine = {"stats": {"hp": 9, "atk": 1}, "art": {"url": "a", "alt": "pip"}}
    out = merge(base, theirs, mine)
    assert out.clean and out.value == {"stats": {"hp": 9, "atk": 5}, "art": {"url": "a", "alt": "pip"}}


def test_a_scalar_both_sides_changed_differently_is_a_conflict() -> None:
    base = {"hp": 1, "name": "Pip"}
    out = merge(base, {"hp": 3, "name": "Pip"}, {"hp": 2, "name": "Pipo"})
    assert out.conflicts == ["$.hp"]
    assert out.value == {"hp": 3, "name": "Pipo"}  # theirs where they clash, the rest merged


def test_the_same_change_on_both_sides_is_clean() -> None:
    out = merge({"hp": 1}, {"hp": 2}, {"hp": 2})
    assert out.clean and out.value == {"hp": 2}


def test_removed_on_one_side_unchanged_on_the_other_goes() -> None:
    base = {"hp": 1, "old": True}
    assert merge(base, {"hp": 1}, {"hp": 2, "old": True}).value == {"hp": 2}
    assert merge(base, {"hp": 3, "old": True}, {"hp": 1}).value == {"hp": 3}


def test_removed_on_one_side_changed_on_the_other_is_a_conflict() -> None:
    base = {"hp": 1, "note": "x"}
    out = merge(base, {"hp": 1}, {"hp": 1, "note": "y"})
    assert out.conflicts == ["$.note"]


def test_id_keyed_arrays_follow_theirs_order_and_append_mine() -> None:
    base = {"cards": [{"id": 1, "hp": 1}, {"id": 2, "hp": 2}, {"id": 3, "hp": 3}]}
    theirs = {"cards": [{"id": 3, "hp": 3}, {"id": 1, "hp": 10}, {"id": 2, "hp": 2}, {"id": 4, "hp": 4}]}
    mine = {"cards": [{"id": 1, "hp": 1}, {"id": 3, "hp": 30}, {"id": 5, "hp": 5}, {"id": 6, "hp": 6}]}  # 2 removed
    out = merge(base, theirs, mine)
    assert out.clean
    assert out.value == {"cards": [{"id": 3, "hp": 30}, {"id": 1, "hp": 10}, {"id": 4, "hp": 4},
                                   {"id": 5, "hp": 5}, {"id": 6, "hp": 6}]}


def test_id_keyed_element_edited_on_both_sides_merges_or_conflicts_inside() -> None:
    base = {"cards": [{"id": "a", "hp": 1, "atk": 1}]}
    clean = merge(base, {"cards": [{"id": "a", "hp": 2, "atk": 1}]}, {"cards": [{"id": "a", "hp": 1, "atk": 3}]})
    assert clean.clean and clean.value == {"cards": [{"id": "a", "hp": 2, "atk": 3}]}
    clash = merge(base, {"cards": [{"id": "a", "hp": 2, "atk": 1}]}, {"cards": [{"id": "a", "hp": 4, "atk": 1}]})
    assert clash.conflicts == ["$.cards[id=a].hp"]


def test_an_element_removed_by_one_side_and_edited_by_the_other_is_a_conflict() -> None:
    base = {"cards": [{"id": 1, "hp": 1}, {"id": 2, "hp": 2}]}
    out = merge(base, {"cards": [{"id": 1, "hp": 1}]}, {"cards": [{"id": 1, "hp": 1}, {"id": 2, "hp": 20}]})
    assert out.conflicts == ["$.cards[id=2]"]


def test_other_arrays_are_atomic() -> None:
    base = {"path": [1, 2, 3]}
    assert merge(base, {"path": [1, 2]}, {"path": [1, 2, 3, 4]}).conflicts == ["$.path"]
    assert merge(base, {"path": [1, 2]}, base).value == {"path": [1, 2]}
    dupes = {"cards": [{"id": 1}, {"id": 1}]}  # not unique ids: atomic too
    assert merge({"cards": []}, dupes, {"cards": [{"id": 2}]}).conflicts == ["$.cards"]


def test_set_arrays_keep_both_sides_adds_and_removals() -> None:
    base = {"folders": ["A", "B"]}
    theirs = {"folders": ["A", "B", "C"]}
    mine = {"folders": ["B", "D"]}
    out = merge(base, theirs, mine, set_arrays=True)
    assert out.clean and out.value == {"folders": ["B", "C", "D"]}
    assert merge(base, theirs, mine).conflicts == ["$.folders"]


def test_without_a_base_additions_merge_and_clashes_conflict() -> None:
    out = merge(MISSING, {"a": 1, "both": 1}, {"b": 2, "both": 1})
    assert out.clean and out.value == {"a": 1, "both": 1, "b": 2}
    assert merge(MISSING, {"x": 1}, {"x": 2}).conflicts == ["$.x"]


def test_json_equality_is_strict_about_types() -> None:
    assert same(1, 1.0) and same({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]})
    assert not same(True, 1) and not same(0, False) and not same("1", 1) and not same([1], (1,))
    out = merge({"v": 1}, {"v": True}, {"v": 2})
    assert out.conflicts == ["$.v"]
