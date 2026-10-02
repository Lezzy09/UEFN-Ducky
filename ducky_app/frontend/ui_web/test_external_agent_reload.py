"""External coding-agent turns must reload with their tool steps intact.

Adapters now persist interleaved thinking/text/tool_call blocks (the embedded
agent's format); _messages_to_ui rebuilds the step rows from them, so a panel
crash/reload no longer collapses a Claude Code/Codex turn to just its final text.
"""

from __future__ import annotations

from types import SimpleNamespace

from frontend.ui_web.panel_api import _messages_to_ui


def _conv(messages: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(id="conv-x", messages=messages)


def test_external_turn_blocks_rebuild_step_rows():
    conv = _conv(
        [
            {"role": "user", "text": "wire the button"},
            {
                "role": "assistant",
                "coding_agent": "claude_code",
                "content": "Wired and saved.",
                "blocks": [
                    {"type": "text", "text": "Checking the device first."},
                    {
                        "type": "tool_call",
                        "id": "t1",
                        "name": "mcp__uefn__wire_verse_device_ref",
                        "arguments": {"device": "Button"},
                        "started": 1000.0,
                        "duration_ms": 42,
                        "result": {"ok": True, "data": "wired", "hint": ""},
                        "status": "success",
                    },
                ],
            },
        ]
    )
    rows = _messages_to_ui(conv, project_root="")
    roles = [r["role"] for r in rows]
    # user, narration, tool intent, tool result, final answer — steps survive.
    assert roles == ["user", "assistant", "tool", "success", "assistant"]
    assert rows[1]["text"] == "Checking the device first."
    assert rows[2]["tool"]["name"] == "mcp__uefn__wire_verse_device_ref"
    assert rows[3]["tool"]["result"] == "wired"
    assert rows[4]["text"] == "Wired and saved."


def test_external_failed_turn_keeps_steps_and_interruption():
    conv = _conv(
        [
            {
                "role": "assistant",
                "coding_agent": "claude_code",
                "content": "",
                "incomplete": True,
                "error": "Cancelled",
                "blocks": [
                    {
                        "type": "tool_call",
                        "id": "t9",
                        "name": "Read",
                        "arguments": {},
                        "started": 1000.0,
                        "duration_ms": 0,
                        "result": {"ok": False, "data": "Cancelled before the tool finished.", "hint": ""},
                        "status": "error",
                    },
                ],
            },
        ]
    )
    rows = _messages_to_ui(conv, project_root="")
    roles = [r["role"] for r in rows]
    assert roles == ["tool", "error", "assistant"]
    # The interruption row survives with its error.
    assert rows[2]["incomplete"] is True
    assert rows[2]["error"] == "Cancelled"


def _checkpoint() -> list[dict]:
    """A coding agent mid-turn: the crash-safe checkpoint, one tool still running."""
    return [
        {"role": "user", "content": "Inspect Tycoony"},
        {
            "role": "assistant",
            "content": "",
            "run_id": "run-1",
            "incomplete": True,
            "blocks": [
                {"type": "text", "text": "I'll open the file."},
                {"type": "tool_call", "name": "workspace_list_verse_errors", "arguments": {"server": "uefn"},
                 "status": "pending", "result": {"ok": False, "data": "", "hint": ""}},
            ],
        },
    ]


def test_live_turn_is_not_shown_as_interrupted():
    # Reopening a tab while the agent works used to show "Interrupted before finishing"
    # and "Interrupted: ⚙ … · pending · 0ms" for a run that was still going.
    rows = _messages_to_ui(_conv(_checkpoint()), project_root="", live=True)
    assert [r["role"] for r in rows] == ["user", "assistant", "tool"]
    assert rows[2]["tool"]["status"] == "pending"
    assert not any(r.get("incomplete") for r in rows)


def test_dead_turn_still_shows_the_interruption():
    rows = _messages_to_ui(_conv(_checkpoint()), project_root="", live=False)
    assert rows[-1].get("incomplete") is True
    assert any(r["role"] == "error" and "pending" in r["text"] for r in rows)
