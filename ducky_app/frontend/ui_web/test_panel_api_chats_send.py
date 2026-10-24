"""send_message passes admission's 'queued' marker through as a friendly reply."""

import frontend.ui_web.panel_api as _pa
from frontend.ui_web import panel_api_chats
from frontend.ui_web.panel_api_chats import PanelApiChatsMixin


def _send(monkeypatch, run_id: str) -> dict:
    monkeypatch.setattr(_pa, "load_conversation", lambda conv_id: None)
    monkeypatch.setattr(_pa, "run_message", lambda *a, **k: run_id)
    monkeypatch.setattr(panel_api_chats, "_sync_composer_selection", lambda *a, **k: None)
    api = PanelApiChatsMixin()
    api._push = lambda *a, **k: None
    return api.send_message("c1", "hi", "agent", "m")


def test_queued_send_says_sent(monkeypatch) -> None:
    assert _send(monkeypatch, "queued") == {
        "ok": True, "queued": True, "note": "Sent — the agent takes it at its next step"}


def test_started_send_returns_run_id(monkeypatch) -> None:
    assert _send(monkeypatch, "r1") == {"run_id": "r1"}
