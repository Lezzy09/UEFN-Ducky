"""Stop team stops the members, never the team's lead."""

from types import SimpleNamespace

import frontend.ui_web.panel_api  # noqa: F401  (loads panel_api_chats without the import cycle)
from frontend.ui_web import agent_modes, group_orchestrator, project_chats
from frontend.ui_web.panel_api_chats import PanelApiChatsMixin


def test_group_stop_cancels_the_members_but_not_the_lead(monkeypatch) -> None:
    team = SimpleNamespace(id="team", is_group=True, leader_conv_id="lead")
    rows = [{"member_conv_id": "lead"}, {"member_conv_id": "a"}, {"member_conv_id": "b"}]
    monkeypatch.setattr(project_chats, "load_conversation", lambda cid, **kw: team if cid == "team" else None)
    monkeypatch.setattr(group_orchestrator, "is_group_conversation", lambda conv: conv.is_group)
    monkeypatch.setattr(group_orchestrator, "group_and_nested_ids", lambda gid: [gid])
    monkeypatch.setattr(group_orchestrator, "group_members", lambda conv: rows)
    monkeypatch.setattr(group_orchestrator, "cancel_group_run", lambda gid: None)
    monkeypatch.setattr(agent_modes, "is_agent_running", lambda cid: True)
    api = PanelApiChatsMixin()
    cancelled: list[str] = []
    api.cancel_agent = cancelled.append
    res = api.group_stop("team")
    assert cancelled == ["a", "b"]
    assert {k: res[k] for k in ("ok", "stopped", "groups", "stopped_ids")} == {
        "ok": True, "stopped": 2, "groups": 1, "stopped_ids": ["a", "b"]}
    assert api.group_stop("a")["ok"] is False  # not a group
