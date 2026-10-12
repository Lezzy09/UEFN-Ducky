"""A team seats existing ducky profiles; it never makes new ones (the Duckies page filled with copies)."""

from __future__ import annotations

import json
from types import SimpleNamespace


def _as(monkeypatch, conv_id: str, chain: list[str]) -> None:
    from backend.agent.coding_agents import plans
    from backend.workspace import identity

    monkeypatch.setattr(identity, "resolve_context", lambda: SimpleNamespace(conv_id=conv_id))
    monkeypatch.setattr(plans, "_chat_and_group_ids", lambda cid, root: chain)


def test_a_team_agent_cannot_create_or_duplicate_profiles(monkeypatch):
    from backend.tools.panel import panel_profiles as profiles
    from frontend import agent_profiles

    made: list[object] = []
    monkeypatch.setattr(agent_profiles, "save_agent_profile", lambda p: made.append(p) or {"id": "new", **p})
    monkeypatch.setattr(agent_profiles, "duplicate_agent_profile", lambda pid: made.append(pid) or {"id": "copy"})
    monkeypatch.setattr(profiles, "_notify_changed", lambda: None)

    _as(monkeypatch, "lead", ["lead", "group"])
    for result in (profiles.ducky_profile_create("Island Kit Gateway"), profiles.ducky_profile_duplicate("tester")):
        out = json.loads(result)
        assert not out["ok"] and "ducky_list_duckies" in out["error"]
    assert made == []

    _as(monkeypatch, "solo", ["solo"])  # a chat outside any team may still make one
    assert json.loads(profiles.ducky_profile_create("My helper"))["ok"]
    assert len(made) == 1
