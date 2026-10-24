"""ui_rpc.pending_question: the chat's oldest unanswered ask_user, with when it was asked."""

from __future__ import annotations

import time

import pytest

from frontend.ui_web import ui_rpc


@pytest.fixture
def pending(monkeypatch):
    monkeypatch.setattr(ui_rpc, "_restore_questions_locked", lambda: None)
    monkeypatch.setattr(ui_rpc, "_pending", {})
    return ui_rpc._pending


def _ask(prompt: str, conv_id: str = "c1", asked_at: float | None = None) -> ui_rpc._Pending:
    slot = ui_rpc._Pending(conv_id, "ask_user", {"conv_id": conv_id, "questions": [{"id": "q", "prompt": prompt}]})
    if asked_at is not None:
        slot.asked_at = asked_at
    return slot


def test_none_without_a_question(pending):
    assert ui_rpc.pending_question("c1") is None and ui_rpc.pending_question("") is None
    pending["r0"] = _ask("Other chat?", conv_id="c2")
    assert ui_rpc.pending_question("c1") is None


def test_the_oldest_open_question(pending):
    now = time.time()
    pending["r2"] = _ask("Newer?", asked_at=now - 5)
    pending["r1"] = _ask("Which folder?", asked_at=now - 62)
    assert ui_rpc.pending_question("c1") == {"request_id": "r1", "text": "Which folder?", "since": now - 62}
    pending["r1"].event.set()  # answered
    assert ui_rpc.pending_question("c1")["request_id"] == "r2"
