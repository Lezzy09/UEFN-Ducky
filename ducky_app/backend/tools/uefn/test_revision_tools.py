"""revision_push / revision_pull: lore_cli decides what to do, the listener does it."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.tools.uefn import level_viewport


def fake_lore(*, paths=None, states=None):
    states = list(states or [{"ok": True, "in_sync": True, "behind": 0, "ahead": 0}])
    calls = []

    def repo_state(root, *, timeout=60.0):
        calls.append(("repo_state", root))
        return states.pop(0) if len(states) > 1 else states[0]

    def pending_paths(root, *, timeout=60.0):
        calls.append(("pending_paths", root))
        return {"ok": True, "paths": list(paths or []), "error": ""}

    return SimpleNamespace(repo_state=repo_state, pending_paths=pending_paths, calls=calls)


@pytest.fixture
def root():
    with patch.object(level_viewport, "_island_root", return_value="C:/Islands/MyIsland"):
        yield "C:/Islands/MyIsland"


def test_push_checks_in_the_pending_files_then_confirms(root) -> None:
    lore = fake_lore(paths=["C:/Islands/MyIsland/Content/A.uasset"])
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        send.return_value = {"ok": True, "checked_in": ["a", "b"], "saved": ["b"], "error": ""}
        out = json.loads(level_viewport.revision_push("moved the cube"))
    assert send.call_args.args == (
        "revision_check_in",
        {"files": ["C:/Islands/MyIsland/Content/A.uasset"], "description": "moved the cube"},
    )
    assert lore.calls == [("repo_state", root), ("pending_paths", root), ("repo_state", root)]
    assert out == {"ok": True, "checked_in": 2, "saved": 1, "in_sync": True, "behind": 0, "ahead": 0, "error": ""}


def test_push_refuses_an_empty_description(root) -> None:
    with patch.object(level_viewport, "send_command") as send:
        out = json.loads(level_viewport.revision_push("  "))
    assert out["ok"] is False and "description" in out["error"]
    send.assert_not_called()


def test_push_stops_when_pending_files_cannot_be_listed(root) -> None:
    lore = fake_lore()
    lore.pending_paths = lambda r, timeout=60.0: {"ok": False, "paths": [], "error": "lore missing"}
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        out = json.loads(level_viewport.revision_push("d"))
    assert out == {"ok": False, "error": "lore missing"}
    send.assert_not_called()


def test_pull_up_to_date_never_touches_uefn(root) -> None:
    lore = fake_lore()
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        out = json.loads(level_viewport.revision_pull())
    assert out["ok"] is True and out["up_to_date"] is True
    send.assert_not_called()


def test_pull_syncs_when_behind_and_confirms(root) -> None:
    lore = fake_lore(states=[
        {"ok": True, "in_sync": False, "behind": 2, "ahead": 0},
        {"ok": True, "in_sync": True, "behind": 0, "ahead": 0},
    ])
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        send.return_value = {"ok": True, "synced": True, "reloaded": True, "seconds": 3.7, "error": ""}
        out = json.loads(level_viewport.revision_pull())
    assert send.call_args.args == ("revision_sync", {"force": False})
    assert out == {"ok": True, "reloaded": True, "seconds": 3.7, "in_sync": True, "behind": 0, "ahead": 0, "error": ""}


def test_pull_with_unsaved_work_asks_instead(root) -> None:
    lore = fake_lore(states=[{"ok": True, "in_sync": False, "behind": 1, "ahead": 0}])
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        send.return_value = {"ok": False, "needs_save": ["/MyIsland/X"], "synced": False}
        out = json.loads(level_viewport.revision_pull())
    assert out["ok"] is False and out["needs_save"] == ["/MyIsland/X"]
    assert "ask the person" in out["error"]
    assert lore.calls == [("repo_state", root)]


def test_no_island_open() -> None:
    with patch.object(level_viewport, "_island_root", return_value=""), \
            patch.object(level_viewport, "send_command") as send:
        assert json.loads(level_viewport.revision_pull())["ok"] is False
        assert json.loads(level_viewport.revision_push("d"))["ok"] is False
    send.assert_not_called()


def test_island_root_is_the_island_uefn_has_open() -> None:
    # Ducky's selected project can be another island: Lore must read the open one.
    with patch.object(level_viewport, "send_command", return_value={"island": "C:/Islands/Open/", "dirty": []}):
        assert level_viewport._island_root() == r"C:\Islands\Open"
    with patch.object(level_viewport, "send_command", return_value={"dirty": []}):
        assert level_viewport._island_root() == ""


def test_push_retries_a_check_in_that_fails_right_after_saving(root) -> None:
    lore = fake_lore()
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport.time, "sleep") as sleep, \
            patch.object(level_viewport, "send_command") as send:
        send.side_effect = [
            {"ok": False, "targets": ["/I/A"], "checked_in": [], "saved": ["/I/A"], "error": "check-in failed"},
            {"ok": True, "targets": ["/I/A"], "checked_in": ["/I/A"], "saved": [], "error": ""},
        ]
        out = json.loads(level_viewport.revision_push("moved the cube"))
    assert send.call_args.args == ("revision_check_in", {"files": ["/I/A"], "description": "moved the cube"})
    assert sleep.call_count == 1
    assert out["ok"] is True and out["checked_in"] == 1 and out["saved"] == 1


def test_push_does_not_retry_when_nothing_was_saved(root) -> None:
    lore = fake_lore()
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport.time, "sleep") as sleep, \
            patch.object(level_viewport, "send_command") as send:
        send.return_value = {"ok": False, "targets": ["/I/A"], "checked_in": [], "saved": [], "error": "remote said no"}
        out = json.loads(level_viewport.revision_push("d"))
    assert send.call_count == 1 and sleep.call_count == 0
    assert out["ok"] is False and out["error"] == "remote said no"


def test_push_refuses_while_the_island_is_behind(root) -> None:
    lore = fake_lore(states=[{"ok": True, "in_sync": False, "behind": True, "ahead": False}])
    with patch.object(level_viewport, "_lore_cli", return_value=lore), \
            patch.object(level_viewport, "send_command") as send:
        out = json.loads(level_viewport.revision_push("moved the cube"))
    assert out["ok"] is False and out["behind"] is True and "revision_pull" in out["error"]
    assert lore.calls == [("repo_state", root)]
    send.assert_not_called()
