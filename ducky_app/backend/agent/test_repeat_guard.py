"""Repeat-call guard bookkeeping: only a SUCCESSFUL mutation resets other calls' history."""

from __future__ import annotations

from backend.agent.runner import (
    _MAX_IDENTICAL_RESULT_CALLS,
    _call_signature,
    _is_readonly_tool,
    _repeat_guard_message,
    note_executed_call,
)


def _record(calls, name, ok, payload):
    sig = _call_signature(name, {})
    note_executed_call(calls, sig, payload, ok=ok, readonly=_is_readonly_tool(name))
    return sig


def test_successful_mutation_resets_other_histories_but_keeps_its_own():
    calls: dict[str, list[str]] = {}
    status = _record(calls, "ducky_get_status", True, "s1")
    _record(calls, "ducky_get_status", True, "s1")
    assert len(calls[status]) == 2
    write = _record(calls, "workspace_write_file", True, "ok")
    assert status not in calls  # the write may have changed what status says
    _record(calls, "workspace_write_file", True, "ok")
    assert len(calls[write]) == 2  # a no-op rewrite still accumulates


def test_failed_mutation_resets_nothing():
    """The status → sync(error) → status loop: the failing sync must not wipe status."""
    calls: dict[str, list[str]] = {}
    status = _record(calls, "ducky_get_status", True, "same")
    sync = _record(calls, "ducky_sync_project_to_uefn", False, "err")
    _record(calls, "ducky_get_status", True, "same")
    _record(calls, "ducky_sync_project_to_uefn", False, "err")
    assert len(calls[status]) == _MAX_IDENTICAL_RESULT_CALLS
    assert len(calls[sync]) == _MAX_IDENTICAL_RESULT_CALLS
    assert len(set(calls[status][-_MAX_IDENTICAL_RESULT_CALLS:])) == 1


def test_readonly_calls_never_reset():
    calls: dict[str, list[str]] = {}
    a = _record(calls, "ducky_list_projects", True, "x")
    _record(calls, "ducky_get_local_project", True, "y")
    assert a in calls


def test_guard_message_points_at_the_user_exit():
    text = _repeat_guard_message("ducky_sync_project_to_uefn", 2)
    assert "ducky_ask_user" in text
    assert "ducky_sync_project_to_uefn" in text


def test_a_question_answered_with_nothing_working_since_is_not_asked_again():
    # Oct 17 2026: every file read failed, and the model asked the same picture-budget
    # question five times although the person said yes each time.
    from backend.agent.runner import AskedAlready

    asked = AskedAlready()
    assert not asked.blocks("ducky_ask_user")
    asked.note("ducky_ask_user", True, '{"answers": {"approve": {"selected": ["yes"]}}}')
    asked.note("workspace_read_file", False, "Path is outside allowed workspace folders")
    assert asked.blocks("ducky_ask_user")
    assert not asked.blocks("workspace_read_file")
    assert '"yes"' in asked.message() and "Not asked again" in asked.message()
    # Real progress since the answer: a new question is fine.
    asked.note("workspace_read_file", True, "ok")
    assert not asked.blocks("ducky_ask_user")
