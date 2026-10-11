""""Ask before changes" holds for every agent that changes files through Ducky's tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.panel import permission_prompt as prompts
from backend.workspace import identity
from backend.workspace.identity import RunContext
from backend.workspace.writer import ProjectWriter, WriteDenied


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "Content").mkdir()
    return tmp_path


@pytest.fixture
def asks(monkeypatch):
    """The chat is set to Ask before changes; records each card and answers ``answer[0]``."""
    cards: list[tuple[str, str, str, tuple[str, ...]]] = []
    answer = [True]
    monkeypatch.setattr(prompts, "permission_mode", lambda conv_id: prompts.MODE_ASK)

    def approve(conv_id, agent, op, paths):
        cards.append((conv_id, agent, op, tuple(paths)))
        return answer[0]

    monkeypatch.setattr(prompts, "approve_agent_change", approve)
    return cards, answer


def _as(agent: str):
    return identity.bind(RunContext(run_id="r1", conv_id="chat1", coding_agent=agent))


def test_codex_edit_waits_for_the_card_and_a_no_writes_nothing(project, asks) -> None:
    cards, answer = asks
    w = ProjectWriter.for_root(str(project))
    token = _as("codex")
    try:
        w.write_text("Content/a.txt", "one", tool="workspace_write_file")
        answer[0] = False
        with pytest.raises(WriteDenied, match="did not approve"):
            w.write_text("Content/b.txt", "two", tool="workspace_write_file")
        with pytest.raises(WriteDenied):
            w.path_op("delete", "Content/a.txt", tool="workspace_delete_file", perform=lambda: None)
    finally:
        identity.reset(token)
    assert (project / "Content" / "a.txt").read_text() == "one"
    assert not (project / "Content" / "b.txt").exists()
    assert [c[1:3] for c in cards] == [("codex", "write"), ("codex", "write"), ("codex", "delete")]


def test_ducky_and_people_are_not_asked_here(project, asks) -> None:
    cards, _answer = asks
    w = ProjectWriter.for_root(str(project))
    token = _as("ducky")  # Ducky's own agent asks before it calls the tool
    try:
        w.write_text("Content/a.txt", "x", tool="workspace_write_file")
    finally:
        identity.reset(token)
    w.write_text("Content/b.txt", "y")  # a person
    assert cards == []


def test_other_modes_never_ask(project, asks, monkeypatch) -> None:
    cards, _answer = asks
    monkeypatch.setattr(prompts, "permission_mode", lambda conv_id: prompts.MODE_EDITS)
    w = ProjectWriter.for_root(str(project))
    token = _as("cursor")
    try:
        w.write_text("Content/a.txt", "x", tool="workspace_write_file")
    finally:
        identity.reset(token)
    assert cards == []


def test_the_card_names_the_agent(monkeypatch) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(prompts, "_ask", lambda card, tool: (seen.append(card), ("once", ""))[1])
    monkeypatch.setattr(prompts, "_rules", lambda conv_id: [])
    assert prompts.approve_agent_change("chat1", "codex", "write", ("Content/a.txt",)) is True
    assert prompts.approve_agent_change("chat1", "claude_code", "move", ("Content/a.txt", "Content/b.txt")) is True
    assert seen[0]["prompt"] == "Allow Codex to edit this file?" and seen[0]["detail"] == "Content/a.txt"
    assert seen[1]["prompt"] == "Allow Claude Code to move this file?"
