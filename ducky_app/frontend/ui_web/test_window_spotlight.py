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


# ---- pixels: the desktop card, ring and dim drawn like the in-app Show me popup ----


def test_card_pixels_match_the_popup_layout_and_expose_its_buttons():
    from frontend.ui_web.window_spotlight_paint import CARD_W, SURFACE, CardState, render_card

    px = render_card(CardState(title="Your custom water materials", body="Both are **here**: `Materials`.", index=1, total=3))
    pad_l, pad_t, pad_r, pad_b = px.pad
    assert px.visible[0] == CARD_W
    assert px.image.size == (pad_l + CARD_W + pad_r, pad_t + px.visible[1] + pad_b)
    # Opaque surface in the middle, fully transparent far corner (so a click there passes through).
    assert px.image.getpixel((pad_l + CARD_W // 2, pad_t + 40))[:3] == SURFACE
    assert px.image.getpixel((0, 0))[3] == 0
    assert set(px.hits) == {"close", "next", "back"}
    cx0, cy0, cx1, cy1 = px.hits["close"]
    assert cx1 - cx0 == 28 and cy1 - cy0 == 28
    assert cx1 <= pad_l + CARD_W and cy0 >= pad_t - 4
    assert px.hit(cx0 + 14, cy0 + 14) == "close"
    assert px.hit(pad_l + 20, pad_t + 20) is None

    # One step: no footer, no Next/Back; a click step keeps Next off until the last step.
    single = render_card(CardState(title="T", body="B", index=0, total=1))
    assert set(single.hits) == {"close"} and single.visible[1] < px.visible[1]
    clicky = render_card(CardState(title="T", body="B", index=0, total=2, click=True))
    assert "next" not in clicky.hits
    last = render_card(CardState(title="T", body="B", index=1, total=2, click=True))
    assert "next" in last.hits  # it reads Close there


def test_hovering_a_button_changes_its_pixels_only():
    from frontend.ui_web.window_spotlight_paint import CardState, render_card

    plain = render_card(CardState(title="T", body="B", index=0, total=1))
    hover = render_card(CardState(title="T", body="B", index=0, total=1, hover="close"))
    x0, y0, x1, y1 = plain.hits["close"]
    assert plain.image.getpixel((x0 + 3, y0 + 3)) != hover.image.getpixel((x0 + 3, y0 + 3))
    pad_l, pad_t, _r, _b = plain.pad
    assert plain.image.getpixel((pad_l + 30, pad_t + 60)) == hover.image.getpixel((pad_l + 30, pad_t + 60))


def test_dim_is_clear_inside_the_hole_and_dark_outside():
    from frontend.ui_web.window_spotlight_paint import DIM_ALPHA, render_dim

    dim = render_dim(400, 300, (100, 100, 120, 80), 12)
    assert dim.size == (400, 300)
    assert dim.getpixel((160, 140))[3] == 0
    assert dim.getpixel((10, 10))[3] == DIM_ALPHA
    assert dim.getpixel((100, 100))[3] == DIM_ALPHA  # rounded corner stays dim
    assert 0 < dim.getpixel((104, 104))[3] < DIM_ALPHA  # anti-aliased edge


def test_ring_glows_outside_and_stays_clear_inside():
    from frontend.ui_web.window_spotlight_paint import render_ring

    ring, margin = render_ring(120, 80, 12)
    assert ring.size == (120 + 2 * margin, 80 + 2 * margin)
    assert ring.getpixel((ring.width // 2, ring.height // 2))[3] == 0
    assert ring.getpixel((margin + 1, ring.height // 2))[3] > 200
    assert 0 < ring.getpixel((margin - 6, ring.height // 2))[3] < 200
    assert ring.getpixel((0, 0))[3] == 0


def test_clear_rect_and_text_helpers():
    from PIL import Image

    from frontend.ui_web.window_spotlight_paint import clear_rect, font, plain_text, wrap

    img = Image.new("RGBA", (50, 50), (1, 2, 3, 255))
    out = clear_rect(img, (10, 10, 20, 20))
    assert out.getpixel((15, 15))[3] == 0 and out.getpixel((5, 5))[3] == 255
    assert img.getpixel((15, 15))[3] == 255  # the input is untouched
    assert plain_text("Line one\n- item **bold** `code`\n\nSecond para") == ["Line one • item bold code", "Second para"]
    fnt = font("regular", 13)
    lines = wrap("a few words that will certainly not fit on one short line", fnt, 120)
    assert len(lines) > 1 and all(fnt.getlength(line) <= 120 for line in lines)
    assert wrap("", fnt, 100) == [""]
