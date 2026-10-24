"""The lead's spec as a member brief: whole `##` sections, never cut mid-rule.

Oct 24 2026: the keeper cut the spec at character 1200, so Google's briefs ended
"No secret in git, no .env, no s …" and Media Kit's at "Limits …". Here hard-rule
sections (Secrets, Decisions, Interfaces/Contract, any heading saying "hard rule")
always stay whole; other sections drop whole from the end, each named with a
ducky_get_plan(section=…) pointer, until the brief fits BRIEF_BYTES."""

from __future__ import annotations

import re
from typing import Any

BRIEF_BYTES = 3900  # + the wrapper line stays under 4 KB
_HEADING = re.compile(r"##(?!#)\s*(.+)")
_HARD = re.compile(r"secret|decision|interface|contract|hard rule", re.I)


def _spec_text(plan: dict[str, Any]) -> str:
    """Overview + description of the main plan (loaded when the keeper's row has no body)."""
    doc = plan
    if "body_markdown" not in plan and plan.get("project_root"):
        try:
            from backend.agent.coding_agents.plans import load_plan

            doc = load_plan(str(plan.get("chat_id") or ""), plan.get("project_root")) or plan
        except Exception:
            doc = plan
    overview = str(doc.get("overview") or "").strip()
    body = str(doc.get("body_markdown") or "").strip()
    return body if overview and body.startswith(overview) else "\n\n".join(p for p in (overview, body) if p)


def _sections(text: str) -> list[tuple[str | None, str]]:
    """(heading, text) per `##` section; the part before the first heading has heading None."""
    out: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if m:
            out.append((m.group(1).strip(), []))
        out[-1][1].append(line)
    return [(t, "\n".join(lines).strip("\n")) for t, lines in out if t is not None or "".join(lines).strip()]


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut_words(text: str, limit: int) -> str:
    """At most `limit` bytes, ending on a whole word."""
    if _size(text) <= limit:
        return text
    head = text.encode("utf-8")[:max(limit, 0)].decode("utf-8", "ignore")
    end = max(head.rfind(" "), head.rfind("\n"))
    return head[:end].rstrip() if end > 0 else ""


def _brief_text(text: str, chat_id: str) -> str:
    secs = _sections(text)
    kept = list(range(len(secs)))
    dropped: list[str] = []

    def render() -> str:
        body = "\n\n".join(secs[i][1] for i in kept)
        if dropped:
            body += "\n\nLeft out to keep this short (read a section when you need it):\n" + "\n".join(
                f'- {t}: ducky_get_plan(chat_id="{chat_id}", section="{t}")' for t in dropped)
        return body

    while _size(render()) > BRIEF_BYTES:
        soft = [i for i in kept if secs[i][0] is not None and not _HARD.search(secs[i][0])]
        if not soft:
            break
        kept.remove(soft[-1])
        dropped.insert(0, secs[soft[-1]][0] or "")
    brief = render()
    over = _size(brief) - BRIEF_BYTES
    if over > 0 and kept and secs[kept[0]][0] is None:
        # Only the untitled opening is left to shorten; hard sections stay whole even past the cap.
        intro = secs[kept[0]][1]
        cut = _cut_words(intro, _size(intro) - over - 80)
        secs[kept[0]] = (None, f'{cut} …(the rest: ducky_get_plan(chat_id="{chat_id}"))')
        brief = render()
    return brief


def spec_brief(plan: dict[str, Any]) -> str:
    """The spec block for a member's task text ("" when the plan has no description)."""
    text = _spec_text(plan)
    if not text:
        return ""
    brief = _brief_text(text, str(plan.get("chat_id") or ""))
    return ("Spec from your lead, for the whole team (keep its folders, file names and field names "
            f"exactly):\n{brief}\n\n")
