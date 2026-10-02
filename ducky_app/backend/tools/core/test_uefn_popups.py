"""UEFN popups: buttons found in a capture, Verse-error popups answered, no save after a skip.

The fixtures are the real dialogs UEFN 42.30 showed when Tycoony opened with Verse
errors (Oct 2 2026); an agent and a workflow sat behind them until they timed out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from backend.tools.core import uefn_popups as popups

_FIX = Path(__file__).resolve().parent / "testdata" / "popups"


def _img(name: str) -> Image.Image:
    return Image.open(_FIX / f"{name}.png")


@pytest.mark.parametrize(
    ("name", "count", "primary", "press"),
    [
        ("verse_build_errors", 4, [4], 3),  # Copy Errors, Close Project, Skip Rebuild, [Rebuild and Validate]
        ("data_loss_warning", 2, [], 1),  # Skip Rebuild & Continue, Fix Errors First
        ("verse_validation_errors", 4, [2], 4),  # Open VS Code, [Rebuild Verse And Reload Map], Close Map, Continue
    ],
)
def test_buttons_are_found_and_the_known_rule_picks_the_right_one(name, count, primary, press) -> None:
    buttons = popups.find_buttons(_img(name))
    assert len(buttons) == count
    assert [i for i, b in enumerate(buttons, start=1) if b["primary"]] == primary
    assert [b["nx"] for b in buttons] == sorted(b["nx"] for b in buttons)
    rule = popups.known_rule(name.replace("_", " "), buttons)
    assert rule is not None and rule["press"] == press


def test_a_known_title_with_another_layout_is_not_pressed() -> None:
    buttons = popups.find_buttons(_img("verse_validation_errors"))
    assert popups.known_rule("Verse Build Errors", buttons) is None  # blue button in the wrong place
    assert popups.known_rule("Some Other Dialog", buttons) is None


def test_the_capture_numbers_every_button() -> None:
    img = _img("verse_build_errors")
    out = popups.annotate(img, popups.find_buttons(img))
    assert out.size == img.size and out.tobytes() != img.convert("RGB").tobytes()


@pytest.fixture()
def screen(monkeypatch, tmp_path):
    """A fake UEFN: a stack of popups; a click on the rule's button shows the next one."""
    monkeypatch.setattr("frontend.settings.default_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(popups, "_uefn_pids", lambda: {4242})
    stack = [("Verse Build Errors", "verse_build_errors", 3),
             ("Data Loss Warning", "data_loss_warning", 1),
             ("Verse Validation Errors", "verse_validation_errors", 4)]
    state = {"clicks": []}

    def list_popups():
        if not stack:
            return []
        title, name, _ = stack[0]
        w, h = _img(name).size
        return [{"hwnd": 100 + len(stack), "title": title, "rect": {"left": 0, "top": 0, "right": w, "bottom": h, "width": w, "height": h}}]

    def grab(rect):
        return _img(stack[0][1])

    def inject_pointer(hwnd, kind, nx, ny, **_):
        if kind != "up":
            return
        title, name, want = stack[0]
        hit = [i for i, b in enumerate(popups.find_buttons(_img(name)), start=1) if abs(b["nx"] - nx) < 1e-6]
        state["clicks"].append((title, hit[0]))
        if hit[0] == want:
            stack.pop(0)

    monkeypatch.setattr(popups, "list_popups", list_popups)
    monkeypatch.setattr(popups, "_grab", grab)
    monkeypatch.setattr("frontend.window_view.inject_pointer", inject_pointer)
    return state


def test_the_verse_popups_on_project_open_are_answered_in_order(screen) -> None:
    for _ in range(3):
        popups.answer_known_popups()
    assert screen["clicks"] == [("Verse Build Errors", 3), ("Data Loss Warning", 1), ("Verse Validation Errors", 4)]
    assert popups.list_popups() == []
    assert popups.verse_skip_active() is True


def test_nothing_saves_the_level_after_a_skip(screen, monkeypatch) -> None:
    for _ in range(3):
        popups.answer_known_popups()
    from backend.bridge import client
    from backend.tools.core import uefn_modal

    with pytest.raises(RuntimeError, match="Verse devices are broken"):
        client.send_command("save_all_dirty", {"maps": True})
    assert uefn_modal.auto_dismiss_save_modal() is None

    sent = []
    monkeypatch.setattr("backend.bridge.client.send_command", lambda *a, **k: sent.append(a) or {})
    monkeypatch.setattr("backend.bridge.client.listener_get_health", lambda *a, **k: {"ok": True})
    from frontend.ui_web.verse_editor.workflow.client import _presave_dirty_packages

    _presave_dirty_packages()
    assert sent == []  # no pre-save before the build


def test_a_clean_build_reloads_the_level_and_saving_works_again(screen, monkeypatch) -> None:
    for _ in range(3):
        popups.answer_known_popups()
    calls = []

    def send_command(command, params=None, timeout=0):
        calls.append(command)
        return {"result": {"level": "/Tycoony/Tycoony", "loaded": True}, "stdout": "", "stderr": ""}

    monkeypatch.setattr("backend.bridge.client.send_command", send_command)
    out = popups.reload_level_after_clean_build()
    assert calls == ["execute_python"] and out["loaded"] is True
    assert popups.verse_skip_active() is False
    assert popups.reload_level_after_clean_build() is None  # nothing to do any more


def test_the_block_ends_with_the_uefn_that_skipped(screen, monkeypatch) -> None:
    for _ in range(3):
        popups.answer_known_popups()
    monkeypatch.setattr(popups, "_uefn_pids", lambda: {9999})  # UEFN restarted: level reloads from disk
    assert popups.verse_skip_active() is False
