"""An open question answered by typing in the composer: the agent gets the person's own words."""

from __future__ import annotations

from frontend.ui_web import ui_rpc

QUESTIONS = [
    {"id": "path", "prompt": "Which option?", "options": [{"id": "a"}, {"id": "b"}], "allow_free_text": True},
    {"id": "go", "prompt": "Proceed?", "options": [{"id": "yes"}], "allow_free_text": False},
]


def test_free_text_answers_open_questions() -> None:
    request_id, _event = ui_rpc.submit("ask_user", {"conv_id": "lead", "questions": QUESTIONS})
    try:
        assert ui_rpc.respond(request_id, {}, free_text="use option B") is True
        result = ui_rpc.wait(request_id, 0.1)
        assert result["note"] == ui_rpc.FREE_TEXT_NOTE and result["free_text"] == "use option B"
        assert result["answers"]["path"] == {"selected": [], "text": "use option B", "free_text": True}
        assert result["answers"]["go"]["selected"] == ["other"]  # options-only: an 'other' answer
        assert result["answers"]["go"]["text"] == "use option B"
    finally:
        ui_rpc.cancel(request_id)


def test_free_text_in_payload_keeps_picked_answers() -> None:
    request_id, _event = ui_rpc.submit("ask_user", {"conv_id": "lead", "questions": QUESTIONS})
    try:
        payload = {"answers": {"go": {"selected": ["yes"]}}, "free_text": "b, but keep it small"}
        assert ui_rpc.respond(request_id, payload) is True
        answers = ui_rpc.wait(request_id, 0.1)["answers"]
        assert answers["go"] == {"selected": ["yes"]}
        assert answers["path"]["text"] == "b, but keep it small"
    finally:
        ui_rpc.cancel(request_id)


def test_option_answer_unchanged() -> None:
    request_id, _event = ui_rpc.submit("ask_user", {"conv_id": "lead", "questions": QUESTIONS})
    answer = {"ok": True, "answers": {"path": {"selected": ["b"]}, "go": {"selected": ["yes"]}}}
    try:
        assert ui_rpc.respond(request_id, answer) is True
        assert ui_rpc.wait(request_id, 0.1) == answer
    finally:
        ui_rpc.cancel(request_id)
