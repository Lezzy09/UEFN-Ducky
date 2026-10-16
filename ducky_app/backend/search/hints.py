"""Skill hints for a user turn: the few sections that best match what the person asked.

Added to the turn's live context (Ducky's own agent) or prompt (coding agents),
never to the system prompt, so the cached prompt prefix stays byte-identical. A
hint is only given when the top match is clearly relevant; chit-chat ("continue",
"did you finish?") gets none.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger("uefn_ducky.search")
_SENTENCE = re.compile(r"(?<=[.?!])\s+")

MAX_CHARS = 400
MIN_TEXT = 8
QUERY_CHARS = 600
# A hit counts when its meaning score is high, or when keywords and meaning agree.
# Calibrated on backend/search/eval (agent questions vs everyday chat lines).
MEANING_ALONE = 0.42
MEANING_WITH_KEYWORD = 0.28


def _relevant(row: dict[str, Any]) -> bool:
    match = row.get("match") or {}
    meaning = match.get("meaning")
    kw = match.get("keyword_rank")
    if meaning is None:
        return kw is not None and kw <= 3
    return meaning >= MEANING_ALONE or (kw is not None and kw <= 10 and meaning >= MEANING_WITH_KEYWORD)


def _label(row: dict[str, Any]) -> str:
    pack, sub, section = row.get("pack"), row.get("subskill"), row.get("section")
    if row.get("kind") == "pack":
        return str(pack)
    name = f"{pack}/{sub}"
    return f"{name} > {section}" if section else name


def context_for_conversation(conv: Any) -> Any:
    """The search context of a chat's own skill selection (packs and sub-skills it may use)."""
    from backend.search.query import Context, chat_context

    try:
        from backend.skills.store import resolve_conversation_selection
        from frontend.settings import PanelSettings

        sel = resolve_conversation_selection(conv, PanelSettings.load())
        ctx = chat_context()
        return Context(
            disabled_packs=frozenset(sel.disabled_packs) | ctx.disabled_packs,
            enabled_subskills={k: frozenset(v) for k, v in (sel.enabled_subskills or {}).items()} or ctx.enabled_subskills,
            plugin_enabled=ctx.plugin_enabled,
        )
    except Exception:  # noqa: BLE001
        return chat_context()


def _focus(text: str) -> str:
    """The sentence the request is about: the first with three or more content words.

    Later sentences are often about the answer ("reply in three lines", "don't change any
    files", "name the section you read"); searched with the rest they pulled the hint
    toward UEFN Ducky's own how-to sections (Oct 16 live test).
    """
    from backend.store.repos.search import title_words

    for sentence in _SENTENCE.split(text):
        if len(title_words(sentence).split()) >= 3:
            return sentence.strip()
    return text


def skill_hint(user_text: str, *, conv: Any = None, limit: int = 3) -> str:
    """One short block naming the best sections for ``user_text``, or '' when none is clear."""
    text = " ".join((user_text or "").split())
    if len(text) < MIN_TEXT:
        return ""
    try:
        from backend.search import indexer, query

        indexer.maybe_refresh()
        ctx = context_for_conversation(conv) if conv is not None else query.chat_context()
        focus = _focus(text)
        rows = [r for r in query.search(focus[:QUERY_CHARS], limit=limit, context=ctx, refresh=False) if _relevant(r)]
        if not rows and focus != text:
            rows = [r for r in query.search(text[:QUERY_CHARS], limit=limit, context=ctx, refresh=False) if _relevant(r)]
    except Exception:  # noqa: BLE001 — a hint is optional
        _log.debug("search: skill hint failed", exc_info=True)
        return ""
    if not rows:
        return ""
    parts: list[str] = []
    used = 0
    for row in rows:
        piece = f"{_label(row)} — {row.get('read', '')}"
        if used + len(piece) > MAX_CHARS and parts:
            break
        parts.append(piece)
        used += len(piece)
    return "Relevant skills for this request (read before acting): " + "; ".join(parts)
