from __future__ import annotations

import pytest

from backend import process_role
from backend.agent.coding_agents import proc_exec


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(process_role.ENV, raising=False)
    monkeypatch.delenv("UEFN_DUCKY_MCP_BRIDGE", raising=False)


def test_no_env_is_the_app() -> None:
    assert process_role.role() == "app"
    assert process_role.is_app()


def test_the_bridge_flag_is_a_tool_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UEFN_DUCKY_MCP_BRIDGE", "1")
    assert process_role.role() == "tool_server"


def test_the_role_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UEFN_DUCKY_MCP_BRIDGE", "1")
    monkeypatch.setenv(process_role.ENV, "agent_host")
    assert process_role.role() == "agent_host"
    monkeypatch.setenv(process_role.ENV, "nonsense")
    assert process_role.role() == "tool_server"


def test_set_role_tool_server_sets_the_bridge_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    process_role.set_role("tool_server")
    import os

    assert os.environ["UEFN_DUCKY_MCP_BRIDGE"] == "1"
    with pytest.raises(ValueError):
        process_role.set_role("window")


def test_a_cli_never_inherits_the_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(process_role.ENV, "agent_host")
    env = proc_exec.cli_env({"DUCKY_CONV_ID": "c1"})
    assert process_role.ENV not in env
    assert env["DUCKY_CONV_ID"] == "c1"
