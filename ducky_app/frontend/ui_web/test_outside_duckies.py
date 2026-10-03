"""Project-only Duckies lists still include chats made with no island open."""

from __future__ import annotations

import types

from frontend.ui_web import panel_api as pa
from frontend.ui_web.panel_api_chats import PanelApiChatsMixin


def _conv(cid: str):
    return types.SimpleNamespace(
        id=cid,
        title=cid,
        sort_order=0,
        updated=0,
        ducky_style="",
        ducky_name="",
        profile_id="",
        ducky_personality="",
        tts_voice="",
        tts_speed=0,
        file_path="",
        model="",
        provider="",
        coding_agent="ducky",
        thinking_effort="",
        terminal_session_id="",
        folder_id="",
        parent_conv_id="",
        is_group=False,
        leader_conv_id="",
        group_members=[],
        tool_call_count=0,
        file_count=0,
    )


def test_project_list_includes_outside_duckies(monkeypatch):
    roots: list[str | None] = []

    def fake_list(root=None):
        roots.append(root)
        if root == "":
            return [_conv("outside")]
        return [_conv("island")]

    monkeypatch.setattr(pa, "list_all_conversation_metadata", fake_list)
    monkeypatch.setattr(
        "frontend.ui_web.project_chats.project_slug",
        lambda root: "_no_project" if not (root or "").strip() else "Island_abc",
    )
    monkeypatch.setattr(pa.PanelSettings, "load", staticmethod(lambda: types.SimpleNamespace(uefn_project_root="C:/island")))
    monkeypatch.setattr(pa.PanelApi, "_sidebar_context_tokens", staticmethod(lambda _c: 0))

    rows = PanelApiChatsMixin().list_all_conversations(False)
    assert [row["id"] for row in rows] == ["island", "outside"]
    assert "" in roots


def test_global_agents_create_has_no_island(monkeypatch):
    from frontend.ui_web import project_chats

    monkeypatch.setattr(project_chats, "project_root_for_slug", lambda slug: None)
    island = r"C:\island"
    assert project_chats.create_project_root("_no_project", island) == ""
    assert project_chats.create_project_root(project_chats.project_slug(island), island) is None
    try:
        project_chats.create_project_root("missing", island)
    except ValueError as exc:
        assert "Unknown project" in str(exc)
    else:
        raise AssertionError("missing project should fail")


def test_outside_project_does_not_duplicate(monkeypatch):
    roots: list[str | None] = []

    def fake_list(root=None):
        roots.append(root)
        return [_conv("outside")]

    monkeypatch.setattr(pa, "list_all_conversation_metadata", fake_list)
    monkeypatch.setattr(
        "frontend.ui_web.project_chats.project_slug",
        lambda root: "_no_project" if not (root or "").strip() else "Island_abc",
    )
    monkeypatch.setattr(pa.PanelSettings, "load", staticmethod(lambda: types.SimpleNamespace(uefn_project_root="")))
    monkeypatch.setattr(pa.PanelApi, "_sidebar_context_tokens", staticmethod(lambda _c: 0))

    rows = PanelApiChatsMixin().list_all_conversations(False)
    assert [row["id"] for row in rows] == ["outside"]
    assert "" not in roots
