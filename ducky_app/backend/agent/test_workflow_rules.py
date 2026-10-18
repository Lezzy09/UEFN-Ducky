"""The workflow rule every agent gets: check saved workflows once per request, never make one
unasked. Oct 18 2026: agents said "no matching workflow" on every plan step and made workflows
from templates nobody asked for."""

from __future__ import annotations

from backend.agent.hard_rules import AGENT_HARD_RULES


def test_agents_check_once_per_request_and_never_make_workflows_unasked() -> None:
    rules = AGENT_HARD_RULES
    assert "once for that request" in rules and "plan steps" in rules
    assert "Never make a workflow unless asked" in rules
    assert "a template that fits → `create_workflow_from_template`" not in rules
    assert "Workflows first" not in rules and "(HARD)" not in rules.split("### Saved workflows")[1].split("###")[0]


def test_the_chat_prompt_says_the_same() -> None:
    from pathlib import Path

    text = (Path(__file__).with_name("prompt.py")).read_text(encoding="utf-8")
    assert "Workflows first (HARD)" not in text
    assert "Never make a workflow (`save_workflow`, `create_workflow_from_template`) unless the person asked" in text
