"""A team chat whose coding-agent session got too big starts its next turn on a fresh one.

Codex and the other resumable CLIs re-read their whole thread on every turn. A team lead
that resumed one thread all afternoon read over five million tokens per turn, so each
turn took many minutes and the team waited on it. When a team chat's last turn read more
than ``FRESH_SESSION_TOKENS``, its next turn starts a new session instead, carrying a
handoff Ducky builds from what it already keeps: the chat's own last replies and its plan.
Every message stays in the chat; only the agent's resumed thread is dropped.
"""

from __future__ import annotations

import time
from typing import Any

FRESH_SESSION_TOKENS = 2_000_000
_LAST_REPLIES = 5
_REPLY_CHARS = 1200


def _team_chat(conv_id: str) -> bool:
    """A lead or member of an agent group (nested groups included)."""
    try:
        from backend.agent.a2a_broker import _groups_by_member

        containing = _groups_by_member()
    except Exception:
        return False
    return bool(containing) and conv_id in containing


def _turn_tokens(conv: Any) -> int:
    stats = getattr(conv, "coding_agent_stats", None)
    if not isinstance(stats, dict):
        return 0
    try:
        return int(stats.get("context_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def needs_fresh_session(conv: Any) -> bool:
    if not str(getattr(conv, "upstream_session_id", "") or "").strip():
        return False
    if _turn_tokens(conv) < FRESH_SESSION_TOKENS:
        return False
    return _team_chat(str(getattr(conv, "id", "") or ""))


def _last_replies(conv: Any) -> list[str]:
    rows: list[str] = []
    for message in reversed(list(getattr(conv, "messages", None) or [])):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text = str(message.get("text") or message.get("content") or "").strip()
        if not text:
            continue
        stamp = message.get("ts")
        when = time.strftime("%H:%M", time.localtime(float(stamp))) if stamp else ""
        clipped = text if len(text) <= _REPLY_CHARS else text[:_REPLY_CHARS] + " …"
        rows.append(f"- {when} {clipped}".rstrip())
        if len(rows) >= _LAST_REPLIES:
            break
    return list(reversed(rows))


def _plan_outline(conv_id: str) -> list[str]:
    try:
        from backend.agent.coding_agents.plans import load_plan, outline_numbers

        plan = load_plan(conv_id)
    except Exception:
        return []
    if not isinstance(plan, dict):
        return []
    rows = outline_numbers(plan.get("nodes"))
    if not rows:
        return []
    done = sum(1 for _label, node in rows if node.get("status") == "completed")
    open_rows = [f"- {label} {node.get('status', '')}: {str(node.get('content', ''))[:140]}"
                 for label, node in rows if node.get("status") not in ("completed", "cancelled")]
    return [f"{done} of {len(rows)} steps done. Open steps:", *open_rows]


def fresh_session_handoff(conv: Any) -> str:
    """The handoff to put before this turn's message when it starts a fresh session ('' = keep)."""
    if not needs_fresh_session(conv):
        return ""
    tokens = _turn_tokens(conv)
    parts = [
        "## Fresh session",
        f"Your previous session got too big (your last turn re-read {tokens / 1_000_000:.1f}M tokens), "
        "so Ducky started this turn on a fresh one. Every message is still in this chat; nothing was lost.",
    ]
    replies = _last_replies(conv)
    if replies:
        parts += ["", "Where you were (your own last replies, newest last):", *replies]
    outline = _plan_outline(str(getattr(conv, "id", "") or ""))
    if outline:
        parts += ["", "Your plan:", *outline]
    parts += [
        "",
        "Re-read only what you need (ducky_get_plan, project_memory_list, ducky_read_chat) and carry on.",
        "",
    ]
    return "\n".join(parts)


def start_fresh(conv: Any) -> None:
    """Drop the resumed thread; the new session reports its own size."""
    conv.upstream_session_id = ""
    conv.coding_agent_stats = None
