"""A failed tool call always says what went wrong: an empty answer or a bare exception used to
reach the agent as {"error": ""} (get_editor_log with no new lines, a timeout with no message)."""

from __future__ import annotations

from unittest.mock import patch

from backend.agent import tools


def test_an_empty_failure_still_has_a_message() -> None:
    assert tools._looks_like_tool_failure("get_editor_log", "")
    assert tools._failure_text("") == "The tool returned no output."
    assert tools._failure_text("  Error: listener busy \n") == "Error: listener busy"


def test_an_exception_without_a_message_names_its_type() -> None:
    assert tools._exception_text(TimeoutError()) == "TimeoutError (no message)"
    assert tools._exception_text(ValueError("bad path")) == "bad path"


def test_get_editor_log_with_nothing_new_says_so() -> None:
    from backend.tools.core import system

    with patch.object(system, "send_command", return_value={"lines": []}):
        assert system.get_editor_log() == "No new Output Log lines."
        assert system.get_editor_log(regex="LogVerse") == "No Output Log lines matching 'LogVerse'."
    with patch.object(system, "send_command", return_value={"lines": ["a", "b"]}):
        assert system.get_editor_log() == "a\nb"
