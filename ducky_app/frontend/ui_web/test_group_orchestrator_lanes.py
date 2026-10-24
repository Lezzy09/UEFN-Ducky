"""Roster rows keep read-only and unrestricted lanes apart."""

from __future__ import annotations

from frontend.ui_web.group_orchestrator import normalize_member


def test_read_only_and_unrestricted_stay_distinct() -> None:
    assert normalize_member({"member_conv_id": "b", "write_allowed": []})["write_allowed"] == []
    assert normalize_member({"member_conv_id": "b", "write_allowed": None})["write_allowed"] is None
    assert normalize_member({"member_conv_id": "b"})["write_allowed"] is None
    again = normalize_member(normalize_member({"member_conv_id": "b", "write_allowed": [], "lane_set_by": "lead", "lane_set_at": 5}))
    assert again["write_allowed"] == [] and again["lane_set_by"] == "lead" and again["lane_set_at"] == 5.0


def test_a_lane_that_no_longer_parses_never_becomes_unrestricted() -> None:
    assert normalize_member({"member_conv_id": "b", "write_allowed": ["../x"]})["write_allowed"] == []
    assert normalize_member({"member_conv_id": "b", "write_allowed": ["src", "C:/Gone/x"]})["write_allowed"] == ["src/**"]
    assert normalize_member({"member_conv_id": "b", "write_allowed": {"bad": 1}})["write_allowed"] == []
