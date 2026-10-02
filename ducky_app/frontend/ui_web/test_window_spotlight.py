"""Desktop spotlight geometry: pin a box to a corner, follow a move or resize, keep the card on the monitor."""

from __future__ import annotations

from frontend.ui_web.window_spotlight import anchor_box, clean_box, pad_hole, place_card, project_box


def test_box_fractions_clamp_into_the_window():
    assert clean_box({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}) == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    assert clean_box({"x": -1, "y": 0.9, "w": 0.5, "h": 2}) == {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}
    assert clean_box({"x": 0, "y": 0, "w": 0, "h": 0.2}) is None
    assert clean_box("nope") is None


def test_anchor_follows_a_move_and_sticks_to_the_nearest_corner():
    toolbar = anchor_box({"x": 0.02, "y": 0.01, "w": 0.1, "h": 0.05}, 1000, 800)
    assert toolbar["ax"] == "left" and toolbar["ay"] == "top"
    x, y, _w, _h = project_box(toolbar, 100, 50, 1000, 800)
    assert (x, y) == (120, 58)
    moved = project_box(toolbar, 400, 200, 1000, 800)
    assert (moved[0] - 400, moved[1] - 200) == (x - 100, y - 50)
    wider = project_box(toolbar, 100, 50, 1600, 800)
    assert wider[0] == 120

    details = anchor_box({"x": 0.8, "y": 0.2, "w": 0.15, "h": 0.4}, 1000, 800)
    assert details["ax"] == "right"
    x, _y, w, _h = project_box(details, 0, 0, 1000, 800)
    gap = 1000 - (x + w)
    x2, _y2, w2, _h2 = project_box(details, 0, 0, 1400, 900)
    assert 1400 - (x2 + w2) == gap


def test_hole_is_padded_and_round_like_the_in_app_spotlight():
    assert pad_hole(100, 100, 50, 20) == (92, 92, 66, 36, 12)
    x, y, w, h, radius = pad_hole(100, 100, 20, 10)
    assert (w, h) == (36, 36)
    assert radius == 18
    assert (x, y) == (92, 87)


def test_card_stays_on_the_monitor_and_off_the_hole():
    hole = (100, 100, 40, 20)
    monitor = (0, 0, 800, 600)
    x, y = place_card(hole, monitor, 200, 120)
    assert (x, y) == (152, 100)
    assert x + 200 <= 800 and y + 120 <= 600

    # No room on the right: the card goes to the left, still on the monitor.
    x, y = place_card((700, 100, 80, 20), monitor, 200, 120)
    assert x >= 0 and x + 200 <= 800
    assert y >= 0 and y + 120 <= 600
    assert x + 200 <= 700
