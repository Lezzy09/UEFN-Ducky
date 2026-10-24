"""spec_brief: whole sections, hard rules kept, under 4 KB, pointers for what was left out."""

from __future__ import annotations

from frontend.ui_web.team_brief import spec_brief

_FILLER = ("Each tool answers with the plugin's own JSON shape and names the Google account it used, "
           "so a member never guesses which mailbox or drive a call touched. ")

SECRETS = ("## Secrets (hard rule)\n"
           "- No secret in git, no .env, no screenshots of tokens, no client secret in a test fixture.\n"
           "- OAuth tokens live only in the plugin's encrypted store; logs print the account email, never a token.")

GOOGLE_SPEC = "\n\n".join([
    "Google plugin 1.1: Gmail, Drive and Calendar tools for agents, one account picker.",
    "# Google plugin plan",
    "## Goal\n" + _FILLER * 6,
    "## Folders\n- `plugins/google/gmail/`, `plugins/google/drive/`, `plugins/google/calendar/`.\n" + _FILLER * 4,
    SECRETS,
    "## Interfaces\n- `google_status() -> {accounts: [...], default}`\n- `gmail_list(query, limit)`\n" + _FILLER * 3,
    "## Tools\n" + _FILLER * 8,
    "## Limits\n" + _FILLER * 6,
    "## Tests\n" + _FILLER * 6,
])


def _plan(body: str) -> dict:
    return {"chat_id": "lead-1", "overview": "", "body_markdown": body}


def test_google_spec_keeps_secrets_whole_and_fits() -> None:
    assert len(GOOGLE_SPEC) > 5000
    brief = spec_brief(_plan(GOOGLE_SPEC))
    assert len(brief.encode("utf-8")) < 4096
    assert SECRETS in brief
    assert "## Interfaces" in brief and "gmail_list(query, limit)" in brief
    assert '- Tests: ducky_get_plan(chat_id="lead-1", section="Tests")' in brief
    assert '- Limits: ducky_get_plan(chat_id="lead-1", section="Limits")' in brief
    assert "## Tests" not in brief  # dropped whole, not cut
    kept = brief.split("\n", 1)[1].split("\n\nLeft out")[0]
    for chunk in kept.split("\n\n## "):  # every kept section is whole, word for word
        assert chunk.strip() in GOOGLE_SPEC
    assert brief.rstrip().endswith('section="Tests")')


def test_short_spec_is_unchanged() -> None:
    spec = "## Goal\nShip it.\n\n## Secrets\n- No .env in git."
    brief = spec_brief(_plan(spec))
    assert spec in brief and "Left out" not in brief


def test_spec_without_headings_ends_on_a_word() -> None:
    brief = spec_brief(_plan("word " * 2000))
    assert len(brief.encode("utf-8")) < 4096
    assert "word …(the rest: ducky_get_plan(chat_id=\"lead-1\"))" in brief


def test_empty_plan_gives_nothing() -> None:
    assert spec_brief(_plan("")) == ""
