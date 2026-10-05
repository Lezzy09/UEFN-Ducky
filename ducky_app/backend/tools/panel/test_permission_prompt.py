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
    assert [o["id"] for o in question["options"]] == ["once", "always", "all", "deny"]
    assert pp._rules("c1") == ["Bash:git status"]
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
        "cd repo && git push",
    ],
)
def test_risky_commands_never_offer_always(monkeypatch, conv, command: str) -> None:
    asked = _answer(monkeypatch, ["once"])
    assert pp.decide("Bash", {"command": command}, conv_id="c1")["behavior"] == "allow"
    ids = [o["id"] for o in asked[0]["questions"][0]["options"]]
    assert ids == ["once", "all", "deny"]  # never "always <this>", but Allow everything is offered
    assert pp._rules("c1") == []


@pytest.mark.parametrize(
    "command",
    [
        "gh auth status 2>&1 | head -5",
        "git add -A && git commit -m x",
        'py -3 -c "\nimport json\nprint(json.dumps({}))\n"',
    ],
)
def test_chained_commands_offer_only_allow_everything(monkeypatch, conv, command: str) -> None:
    asked = _answer(monkeypatch, ["once"])
    assert pp.decide("Bash", {"command": command}, conv_id="c1")["behavior"] == "allow"
    ids = [o["id"] for o in asked[0]["questions"][0]["options"]]
    assert ids == ["once", "all", "deny"]
    assert pp._rules("c1") == []


def test_allow_everything_never_asks_again(monkeypatch, conv) -> None:
    script = 'py -3 -c "\nimport json\nd=json.load(open(r\'C:/x.txt\'))\nprint(list(d.keys()))\n"'
    asked = _answer(monkeypatch, ["all"])
    assert pp.decide("Bash", {"command": script}, conv_id="c1")["behavior"] == "allow"
    assert pp._rules("c1") == ["*"]
    asked.clear()
    for tool, payload in (
        ("Bash", {"command": "npm run test && npm run lint"}),
        ("PowerShell", {"command": "Get-ChildItem | Select-Object -First 5"}),
        ("Write", {"file_path": r"D:\elsewhere\a.txt", "content": "x"}),
        ("WebFetch", {"url": "https://example.com"}),
    ):
        assert pp.decide(tool, payload, conv_id="c1")["behavior"] == "allow"
    # Pushes, deletes, publishes and deploys too: the person said everything.
    for command in ("git push origin main", "rm -rf build", "py scripts/release.py --publish", "git reset --hard HEAD~1"):
        assert pp.decide("Bash", {"command": command}, conv_id="c1")["behavior"] == "allow"
    assert asked == []


def test_a_remembered_command_rule_never_covers_a_risky_command(monkeypatch, conv) -> None:
    pp._remember("c1", "Bash:git push")
    asked = _answer(monkeypatch, ["deny"])
    assert pp.decide("Bash", {"command": "git push"}, conv_id="c1")["behavior"] == "deny"
    assert asked, "only Allow everything stops the card for a push"


def test_allow_everything_still_refuses_to_push_a_local_only_ai_plugin(monkeypatch, conv) -> None:
    pp._remember("c1", "*")
    asked = _answer(monkeypatch, ["once"])
    out = pp.decide("Bash", {"command": "git push"}, conv_id="c1", project_root=r"C:\GitHub\uefn-plugins\uefn-plugin-anthropic")
    assert out["behavior"] == "deny" and "local-only AI plugin" in out["message"]
    assert asked == []
    assert pp.decide("Bash", {"command": "git status"}, conv_id="c1",
                     project_root=r"C:\GitHub\uefn-plugins\uefn-plugin-anthropic")["behavior"] == "allow"


def test_allow_everything_covers_the_agents_a_chat_starts(monkeypatch, conv) -> None:
    family = {"sub": {"parent_conv_id": "lead"}, "member": {"leader_conv_id": "sub"}, "loop-a": {"parent_conv_id": "loop-b"},
              "loop-b": {"parent_conv_id": "loop-a"}}
    monkeypatch.setattr("backend.store.repos.chats.conv_get", lambda cid, **_k: family.get(cid))
    pp._remember("lead", "*")
    assert pp.allows_everything("lead") and pp.allows_everything("sub") and pp.allows_everything("member")
    assert not pp.allows_everything("loop-a") and not pp.allows_everything("stranger") and not pp.allows_everything("")
    asked = _answer(monkeypatch, ["deny"])
    assert pp.decide("Bash", {"command": "npm test && git push"}, conv_id="member")["behavior"] == "allow"
    assert asked == []


@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "LS"])
def test_read_only_tools_never_ask(monkeypatch, conv, tool: str) -> None:
    asked = _answer(monkeypatch, ["deny"])
    payload = {"file_path": r"C:\Users\me\AppData\Local\UEFN-Ducky\brainrot_tcg\assets\a.png"}
    assert pp.decide(tool, payload, conv_id="c1") == {"behavior": "allow", "updatedInput": payload}
    assert asked == []


def test_quoted_body_is_not_part_of_the_rule() -> None:
    assert pp._command_key('git commit -m "fix the thing"') == "git commit"
    assert pp._command_key('py -3 -c "print(1)"') == "py"


def test_deny_passes_the_users_reason(monkeypatch, conv) -> None:
    _answer(monkeypatch, [], text="use the staging branch")
    out = pp.decide("Bash", {"command": "npm test"}, conv_id="c1")
    assert out == {"behavior": "deny", "message": "The user denied this and said: use the staging branch"}


def test_push_in_local_only_ai_plugin_warns(monkeypatch, conv) -> None:
    asked = _answer(monkeypatch, ["deny"])
    pp.decide("Bash", {"command": "git push"}, conv_id="c1", project_root=r"C:\GitHub\uefn-plugins\uefn-plugin-anthropic")
    assert "local-only AI plugin" in asked[0]["questions"][0]["warning"]
    assert [o["id"] for o in asked[0]["questions"][0]["options"]] == ["once", "deny"]  # no Allow everything here


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


def test_a_chat_save_cannot_drop_a_remembered_approval(monkeypatch, conv) -> None:
    """The app saves its own copy of the chat during a turn; the rule is not on that record."""
    asked = _answer(monkeypatch, ["all"])
    assert pp.decide("Bash", {"command": "npm test"}, conv_id="c1")["behavior"] == "allow"
    assert conv.saved == [] and conv.agent_allow_rules == []  # nothing written onto the chat
    assert pp._rules("c1") == ["*"] and pp._rules("other") == []
    asked.clear()
    script = 'py -3 -c "\nprint(1)\n"'  # multi-line: covered by "allow everything"
    assert pp.decide("Bash", {"command": script}, conv_id="c1")["behavior"] == "allow"
    assert asked == []
