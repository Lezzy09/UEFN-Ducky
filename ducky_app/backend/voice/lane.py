"""Live voice quick-reply lane.

A live turn goes to a fast voice model first, with a compact context (rolling summary,
the last few messages, the current work status). It either answers on its own or says
in one line that it is handing the turn to the chat's agent.
"""

from __future__ import annotations

import re
from typing import Any, Callable

REPLY_LENGTHS = ("short", "normal", "detailed")

_SENTENCE_CAP = {"short": 2, "normal": 4, "detailed": 6}
_CAP_TEXT = {
    "short": "Short: 1-2 sentences, never more than 2",
    "normal": "Normal: 3-4 sentences at most",
    "detailed": "Detailed: up to 6 sentences",
}

HANDOFF_TAG = "HANDOFF:"
_RECENT_MAX = 6
_ROW_CHARS = 600
_SUMMARY_CHARS = 2000

CompleteFn = Callable[[str, str, str], dict[str, Any]]


def normalize_reply_length(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in REPLY_LENGTHS else "short"


def sentence_cap(reply_length: str) -> int:
    return _SENTENCE_CAP[normalize_reply_length(reply_length)]


def build_lane_system(reply_length: str = "short") -> str:
    length = normalize_reply_length(reply_length)
    return (
        "You are the live spoken voice of the assistant, talking with the user while "
        "the coding agent of this chat keeps working in the background. "
        f"Reply length: {_CAP_TEXT[length]}. "
        "Speak plainly: no code, no file paths, no markdown, no lists. "
        "Answer from the context below when you can: what is happening, progress, "
        "a quick question, small talk. "
        "If the user asks for real work (change, fix, build, create, run, edit, look "
        "something up, anything that needs tools or files), do not do it yourself: "
        f"start your reply with {HANDOFF_TAG} and then one short spoken line saying "
        "you are on it."
    )


def build_lane_user(
    text: str,
    *,
    summary: str = "",
    recent: list[tuple[str, str]] | None = None,
    work_status: str = "",
    agent_running: bool = False,
) -> str:
    parts: list[str] = []
    if summary.strip():
        parts.append(f"Chat so far (summary):\n{summary.strip()[:_SUMMARY_CHARS]}")
    rows = [(r, t) for r, t in (recent or []) if (t or "").strip()][-_RECENT_MAX:]
    if rows:
        lines = [f"{role}: {' '.join(body.split())[:_ROW_CHARS]}" for role, body in rows]
        parts.append("Last messages:\n" + "\n".join(lines))
    state = "working" if agent_running else "idle"
    status = work_status.strip()
    parts.append(f"Agent right now: {state}" + (f" ({status})" if status else ""))
    parts.append(f"User just said: {text.strip()}")
    return "\n\n".join(parts)


def build_lane_prompt(
    text: str,
    *,
    reply_length: str = "short",
    summary: str = "",
    recent: list[tuple[str, str]] | None = None,
    work_status: str = "",
    agent_running: bool = False,
) -> tuple[str, str]:
    """(system, user) for the voice model."""
    return (
        build_lane_system(reply_length),
        build_lane_user(
            text, summary=summary, recent=recent, work_status=work_status, agent_running=agent_running
        ),
    )


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def cap_sentences(text: str, cap: int) -> str:
    """Trim a spoken reply to at most ``cap`` sentences."""
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    parts = [p for p in _SENTENCE_END.split(clean) if p]
    return " ".join(parts[: max(1, cap)])


def parse_lane_reply(raw: str, reply_length: str = "short") -> tuple[str, str]:
    """Return (action, spoken): action is "answer" or "agent"."""
    text = (raw or "").strip().strip('"').strip()
    action = "answer"
    if text.upper().startswith(HANDOFF_TAG):
        action = "agent"
        text = text[len(HANDOFF_TAG):].strip()
    cap = 1 if action == "agent" else sentence_cap(reply_length)
    return action, cap_sentences(text, cap)


def run_voice_lane(
    text: str,
    *,
    model: str = "",
    reply_length: str = "short",
    summary: str = "",
    recent: list[tuple[str, str]] | None = None,
    work_status: str = "",
    agent_running: bool = False,
    complete: CompleteFn | None = None,
) -> dict[str, Any]:
    """Ask the voice model about one live turn.

    Returns ``{"ok", "action": "answer" | "agent", "text"}``. On a failed model call
    the turn goes to the agent with no spoken line, so nothing the user said is lost.
    """
    said = (text or "").strip()
    if not said:
        return {"ok": False, "action": "none", "text": "", "error": "empty turn"}
    system, user = build_lane_prompt(
        said,
        reply_length=reply_length,
        summary=summary,
        recent=recent,
        work_status=work_status,
        agent_running=agent_running,
    )
    if complete is None:
        from backend.voice.summary import complete_voice_text

        complete = complete_voice_text
    out = complete(system, user, (model or "").strip())
    if not out.get("ok"):
        return {"ok": False, "action": "agent", "text": "", "error": out.get("error") or "voice model failed"}
    action, spoken = parse_lane_reply(str(out.get("text") or ""), reply_length)
    if action == "answer" and not spoken:
        return {"ok": False, "action": "agent", "text": "", "error": "empty voice reply"}
    return {"ok": True, "action": action, "text": spoken, "model": out.get("model", "")}
