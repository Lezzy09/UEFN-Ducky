"""uefn_window_click / uefn_window_key only drive UEFN editor windows.

Oct 2 2026: an agent pressed Escape in the Fortnite client (not a UEFN window) while it
loaded; its GPU hung right after and the client closed.
"""

from __future__ import annotations

import pytest

from backend.tools.core import uefn_windows


@pytest.fixture()
def sent(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        "backend.tools.core.uefn_modal._enum_uefn_windows",
        lambda: [{"hwnd": 111, "title": "Unreal Editor for Fortnite", "owned": False}],
    )
    monkeypatch.setattr(uefn_windows, "_rect", lambda hwnd: {"left": 0, "top": 0, "right": 10, "bottom": 10, "width": 10, "height": 10})
    monkeypatch.setattr("frontend.window_view.inject_key", lambda *a, **k: calls.append(("key", a)))
    monkeypatch.setattr("frontend.window_view.inject_pointer", lambda *a, **k: calls.append(("pointer", a)))
    return calls


def test_keys_and_clicks_reach_a_uefn_window(sent) -> None:
    assert uefn_windows.key_uefn_window(111, "Escape")["ok"] is True
    assert uefn_windows.click_uefn_window(111, 0.5, 0.5)["ok"] is True
    assert [c[0] for c in sent] == ["key", "key", "pointer", "pointer"]


def test_the_fortnite_client_gets_no_input(sent) -> None:
    out = uefn_windows.key_uefn_window(2296444, "Escape")
    assert out["ok"] is False and "not a UEFN editor window" in out["error"]
    assert uefn_windows.click_uefn_window(2296444, 0.5, 0.5)["ok"] is False
    assert sent == []
