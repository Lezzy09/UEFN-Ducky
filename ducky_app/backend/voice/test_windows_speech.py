"""Windows speech session plumbing — no PowerShell, no mic: events are injected."""

from __future__ import annotations

import pytest

from backend.voice import windows_speech as ws


@pytest.fixture()
def helper(monkeypatch: pytest.MonkeyPatch) -> ws._Helper:
    fresh = ws._Helper()
    monkeypatch.setattr(ws, "_helper", fresh)
    return fresh


def test_poll_returns_only_this_sessions_events_after_cursor(helper: ws._Helper) -> None:
    helper._push({"t": "interim", "sid": "a", "text": "hel"})
    helper._push({"t": "interim", "sid": "b", "text": "other chat"})
    helper._push({"t": "final", "sid": "a", "text": "hello"})

    out = ws.poll_session("a", 0, wait_ms=0)
    assert [ev["text"] for ev in out["events"]] == ["hel", "hello"]
    assert out["active"] is True

    again = ws.poll_session("a", out["cursor"], wait_ms=0)
    assert again["events"] == []


def test_poll_marks_session_inactive_on_end_or_helper_exit(helper: ws._Helper) -> None:
    helper._push({"t": "ended", "sid": "a", "status": "Success"})
    assert ws.poll_session("a", 0, wait_ms=0)["active"] is False

    cursor = helper.cursor()
    helper._push({"t": "exit", "message": "helper stopped"})
    assert ws.poll_session("z", cursor, wait_ms=0)["active"] is False


def test_privacy_error_gets_a_plain_message(helper: ws._Helper) -> None:
    helper._push(
        {
            "t": "error",
            "sid": "a",
            "code": "speech_privacy",
            "message": "The text associated with this error code could not be found.\r\n\r\nThe speech privacy policy was not accepted",
        }
    )
    ev = ws.poll_session("a", 0, wait_ms=0)["events"][0]
    assert ev["code"] == "speech_privacy"
    assert ev["message"].startswith("Windows speech is off")


def test_unknown_error_drops_the_winrt_junk_prefix() -> None:
    raw = "The text associated with this error code could not be found.\r\n\r\nSomething broke"
    assert ws._friendly_error("failed", raw) == "Something broke"


def test_open_windows_settings_only_opens_whitelisted_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(ws, "windows_speech_supported", lambda: True)
    monkeypatch.setattr("os.startfile", lambda uri: opened.append(uri), raising=False)

    assert ws.open_windows_settings("speech_privacy")["ok"] is True
    assert ws.open_windows_settings("ms-settings:windowsupdate")["ok"] is False
    assert opened == ["ms-settings:privacy-speech"]
