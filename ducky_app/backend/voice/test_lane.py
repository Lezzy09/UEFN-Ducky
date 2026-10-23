"""Live voice lane: prompt length caps and the answer / hand-to-agent branches."""

from __future__ import annotations

from backend.voice.lane import (
    build_lane_prompt,
    cap_sentences,
    parse_lane_reply,
    run_voice_lane,
)


def _stub(reply: str, seen: list | None = None):
    def complete(system: str, user: str, model: str) -> dict:
        if seen is not None:
            seen.append((system, user, model))
        return {"ok": True, "text": reply, "model": model or "stub"}

    return complete


def test_short_caps_at_two_sentences_in_prompt():
    system, _ = build_lane_prompt("hi", reply_length="short")
    assert "1-2 sentences" in system
    assert "never more than 2" in system


def test_lengths_change_the_cap():
    assert "3-4 sentences" in build_lane_prompt("hi", reply_length="normal")[0]
    assert "up to 6 sentences" in build_lane_prompt("hi", reply_length="detailed")[0]
    assert "1-2 sentences" in build_lane_prompt("hi", reply_length="bogus")[0]


def test_prompt_carries_compact_context():
    _, user = build_lane_prompt(
        "what are you doing?",
        summary="Building a tycoon.",
        recent=[("user", "fix the errors"), ("assistant", "On it.")],
        work_status="Compiling, 2 errors left",
        agent_running=True,
    )
    assert "Building a tycoon." in user
    assert "user: fix the errors" in user
    assert "Agent right now: working (Compiling, 2 errors left)" in user
    assert user.endswith("User just said: what are you doing?")


def test_short_reply_is_trimmed_to_two_sentences():
    _, spoken = parse_lane_reply("One. Two. Three. Four.", "short")
    assert spoken == "One. Two."
    assert cap_sentences("A. B. C.", 4) == "A. B. C."


def test_answer_only_branch():
    seen: list = []
    out = run_voice_lane(
        "what are you doing?",
        model="claude_code:claude-haiku-5-5",
        work_status="Compiling, 2 errors left",
        agent_running=True,
        complete=_stub("Compiling, 2 errors left.", seen),
    )
    assert out == {"ok": True, "action": "answer", "text": "Compiling, 2 errors left.", "model": "claude_code:claude-haiku-5-5"}
    assert seen[0][2] == "claude_code:claude-haiku-5-5"


def test_hand_to_agent_branch():
    out = run_voice_lane(
        "make the button blue",
        complete=_stub("HANDOFF: Sure, making it blue now. I'll tell you when it's done."),
    )
    assert out["ok"] is True
    assert out["action"] == "agent"
    assert out["text"] == "Sure, making it blue now."


def test_model_failure_hands_to_agent_silently():
    out = run_voice_lane("hello", complete=lambda s, u, m: {"ok": False, "error": "no key"})
    assert out["action"] == "agent"
    assert out["text"] == ""
    assert out["ok"] is False


def test_empty_turn_does_nothing():
    out = run_voice_lane("   ", complete=_stub("x"))
    assert out["action"] == "none"
