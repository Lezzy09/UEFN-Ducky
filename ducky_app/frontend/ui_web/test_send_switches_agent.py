"""A send carries the composer's backend so a stale chat row never pairs Codex with a Claude id."""

from __future__ import annotations

from types import SimpleNamespace

import frontend.ui_web.panel_api as pa
from frontend.ui_web.panel_api_chats import _sync_composer_selection


def _stub(monkeypatch, **fields):
    from backend.agent.coding_agents import base

    monkeypatch.setattr(base, "contributed_coding_agents", lambda: frozenset({"codex", "claude_code"}))
    conv = SimpleNamespace(id="c1", **fields)
    saved: list[object] = []
    monkeypatch.setattr(pa, "load_conversation", lambda _cid: conv)
    monkeypatch.setattr(pa, "save_conversation", saved.append)
    return conv, saved


def test_send_overrides_a_stale_codex_row_with_the_picked_agent(monkeypatch):
    conv, saved = _stub(monkeypatch, coding_agent="codex", model="gpt-6-astra", provider="")
    _sync_composer_selection("c1", "claude-opus-5-5", "claude_code")
    assert (conv.coding_agent, conv.model, conv.provider) == ("claude_code", "claude-opus-5-5", "")
    assert saved == [conv]


def test_switch_to_external_agent_clears_api_provider(monkeypatch):
    conv, _ = _stub(monkeypatch, coding_agent="ducky", model="gpt-5", provider="openai")
    _sync_composer_selection("c1", "claude-opus-5-5", "claude_code")
    assert conv.provider == ""


def test_matching_selection_does_not_save(monkeypatch):
    _, saved = _stub(monkeypatch, coding_agent="codex", model="gpt-6-astra", provider="")
    _sync_composer_selection("c1", "gpt-6-astra", "codex")
    assert saved == []


def test_old_clients_without_agent_keep_the_stored_agent(monkeypatch):
    conv, _ = _stub(monkeypatch, coding_agent="codex", model="gpt-6-astra", provider="")
    _sync_composer_selection("c1", "gpt-6-astra-mini", "")
    assert (conv.coding_agent, conv.model) == ("codex", "gpt-6-astra-mini")
