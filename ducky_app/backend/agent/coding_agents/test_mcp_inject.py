"""Per-run MCP argv so Cursor does not reuse one bridge across duckies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent.coding_agents.mcp_inject import bootstrap_system_prompt, stamp_mcp_identity
from backend.workspace.identity import RunContext


def test_stamp_mcp_identity_uniques_argv_and_inner_bridge() -> None:
    ctx = RunContext(run_id="run-a", conv_id="chat-a", ducky_name="Hacker")
    uefn = {
        "command": "node",
        "args": ["host.mjs"],
        "env": {"DUCKY_BRIDGE_ARGV": json.dumps(["UEFN-Ducky.exe", "bridge", "--port", "9"])},
    }
    stamp_mcp_identity(uefn, ctx, "chat-a")
    assert uefn["args"][-2:] == ["--ducky-run-id", "run-a"]
    assert json.loads(uefn["env"]["DUCKY_BRIDGE_ARGV"])[-2:] == ["--ducky-run-id", "run-a"]
    assert uefn["env"]["DUCKY_RUN_ID"] == "run-a"
    assert uefn["env"]["DUCKY_CONV_ID"] == "chat-a"


def test_two_runs_get_different_argv() -> None:
    a = stamp_mcp_identity({"args": ["bridge"], "env": {}}, RunContext(run_id="1"))
    b = stamp_mcp_identity({"args": ["bridge"], "env": {}}, RunContext(run_id="2"))
    assert a["args"] != b["args"]


def test_bootstrap_includes_chat_report_template() -> None:
    text = bootstrap_system_prompt(
        project_root="/tmp/p",
        listener_online=False,
        conv_id="chat-a",
    )
    assert "## Chat replies" in text
    assert "## Inventory" in text
    assert "> **Loose end:**" in text
    # The report shape forbids echoing written files back into chat.
    assert "link them instead" in text
    assert "select:mcp__uefn__<tool>" in text
    assert "Settings" in text


def test_bootstrap_sends_file_reads_to_ducky_tools_not_the_shell() -> None:
    text = bootstrap_system_prompt(project_root="/tmp/p", listener_online=False, conv_id="chat-a")
    assert "## Ducky tools only" in text
    # Codex runs tools from a code runner and reads other projects by absolute path.
    assert "tools.mcp__uefn__workspace_search" in text
    assert "other Ducky projects" in text
    for shell_read in ("Get-Content", "Select-String", "rg", "git grep"):
        assert shell_read in text


@pytest.mark.parametrize("native_skills", [False, True])
@pytest.mark.parametrize("listener_online", [False, True])
def test_every_agent_bootstrap_uses_ducky_tools_only(native_skills, listener_online) -> None:
    # runner builds this common prompt before dispatching to any CLI adapter.
    text = bootstrap_system_prompt(
        project_root="/tmp/project",
        listener_online=listener_online,
        conv_id="chat-a",
        native_skills=native_skills,
    )
    for tool in ("`workspace_edit_file`", "`ducky_terminal_open`", "`ducky_terminal_run(session_id, command)`",
                 "`ducky_terminal_read_output(session_id)`", "`view_image`", "`web_search`",
                 "`ducky_spawn_chat`", "`ducky_ask_user`"):
        assert tool in text
    assert "never edit a file with Codex `apply_patch`" in text
    assert "background: true" in text
    assert "Never edit files by running a script or command that rewrites them." in text
    # The old split (own shell for builds, own edit tool in other projects) is gone.
    assert "Use the shell for builds" not in text
    assert "your own edit" not in text


def test_team_plan_skill_requires_the_same_tools() -> None:
    app_root = Path(__file__).resolve().parents[3]
    skill = (app_root / "frontend/skill_packs/ducky/SKILL.md").read_text(encoding="utf-8")
    team_rules = " ".join(skill.split("### Team plans", 1)[1].split())
    assert "Ducky's tools only" in team_rules
    assert "`workspace_*` edit tools" in team_rules
    assert "`ducky_terminal_run`" in team_rules
    assert "their own edit tool" not in team_rules
