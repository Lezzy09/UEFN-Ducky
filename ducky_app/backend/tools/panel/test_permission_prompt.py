"""Approval cards for Claude Code's --permission-prompt-tool."""

from __future__ import annotations

import json

import pytest

from backend.tools.panel import permission_prompt as pp


class _Conv:
    def __init__(self) -> None:
        self.agent_allow_rules: list[str] = []


@pytest.fixture
def conv(monkeypatch):
    c = _Conv()
    saved: list[list[str]] = []
    monkeypatch.setattr(pp, "_load_conv", lambda _cid: c)
    monkeypatch.setattr("frontend.chat_store.save_conversation", lambda cv, *_a, **_k: saved.append(list(cv.agent_allow_rules)))
    c.saved = saved
    return c


def _answer(monkeypatch, selected: list[str], text: str = "") -> list[dict]:
    asked: list[dict] = []

    def fake_ask(questions, title=""):
        asked.append({"questions": questions, "title": title})
        return json.dumps({"ok": True, "answers": {"agent_permission": {"selected": selected, "text": text, "skipped": False}}})

    monkeypatch.setattr("backend.tools.panel.panel_ui.ducky_ask_user", fake_ask)
    return asked


def test_plain_command_can_be_always_allowed(monkeypatch, conv) -> None:
    asked = _answer(monkeypatch, ["always"])
    out = pp.decide("Bash", {"command": "git status"}, conv_id="c1")
    assert out == {"behavior": "allow", "updatedInput": {"command": "git status"}}
    question = asked[0]["questions"][0]
    assert question["detail"] == "git status"
    assert [o["id"] for o in question["options"]] == ["once", "always", "deny"]
    assert conv.agent_allow_rules == ["Bash:git status"]
    # Remembered: the next git status runs without a card.
    asked.clear()
    assert pp.decide("Bash", {"command": "git status --short"}, conv_id="c1")["behavior"] == "allow"
    assert asked == []


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push --force",
        "git reset --hard HEAD~1",
        "gh pr create --fill",
        "rm -rf build",
        "py build/build_exes.py",
        "py scripts/release.py --publish",
        "gh auth status 2>&1 | head -5",
        "git add -A && git commit -m x",
    ],
)
def test_risky_or_chained_commands_never_offer_always(monkeypatch, conv, command: str) -> None:
    asked = _answer(monkeypatch, ["once"])
    assert pp.decide("Bash", {"command": command}, conv_id="c1")["behavior"] == "allow"
    ids = [o["id"] for o in asked[0]["questions"][0]["options"]]
    assert ids == ["once", "deny"]
    assert conv.agent_allow_rules == []


def test_risky_command_is_never_auto_allowed_even_if_remembered(monkeypatch, conv) -> None:
    conv.agent_allow_rules = ["Bash:git push"]
    asked = _answer(monkeypatch, ["deny"])
    out = pp.decide("Bash", {"command": "git push"}, conv_id="c1")
    assert out["behavior"] == "deny"
    assert asked, "a push must always show the card"


def test_deny_passes_the_users_reason(monkeypatch, conv) -> None:
    _answer(monkeypatch, [], text="use the staging branch")
    out = pp.decide("Bash", {"command": "npm test"}, conv_id="c1")
    assert out == {"behavior": "deny", "message": "The user denied this and said: use the staging branch"}


def test_push_in_local_only_ai_plugin_warns(monkeypatch, conv) -> None:
    asked = _answer(monkeypatch, ["deny"])
    pp.decide("Bash", {"command": "git push"}, conv_id="c1", project_root=r"C:\GitHub\uefn-plugins\uefn-plugin-anthropic")
    assert "local-only AI plugin" in asked[0]["questions"][0]["warning"]


def test_panel_unreachable_denies(monkeypatch, conv) -> None:
    monkeypatch.setattr(
        "backend.tools.panel.panel_ui.ducky_ask_user", lambda *_a, **_k: json.dumps({"error": "panel not running"})
    )
    out = pp.decide("Bash", {"command": "ls"}, conv_id="c1")
    assert out == {"behavior": "deny", "message": "No approval: panel not running"}


def test_file_tool_card_shows_path(monkeypatch, conv) -> None:
    asked = _answer(monkeypatch, ["once"])
    out = pp.decide("Write", {"file_path": r"D:\elsewhere\a.txt", "content": "x"}, conv_id="c1", project_root=r"C:\repo")
    assert out["behavior"] == "allow"
    question = asked[0]["questions"][0]
    assert question["detail"] == r"D:\elsewhere\a.txt"
    assert question["warning"] == "Outside the project folder."


def test_tool_returns_claude_code_json(monkeypatch, conv) -> None:
    _answer(monkeypatch, ["once"])
    monkeypatch.setattr(pp, "_conv_id", lambda: "c1")
    raw = pp.ducky_permission_prompt("Bash", {"command": "ls"}, tool_use_id="t1")
    assert json.loads(raw) == {"behavior": "allow", "updatedInput": {"command": "ls"}}


def test_hook_is_hidden_from_the_embedded_agent() -> None:
    from backend.agent.toolsets.excluded import EXCLUDED_TOOLS

    assert "ducky_permission_prompt" in EXCLUDED_TOOLS
