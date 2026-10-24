"""Core tool names start with their group, so an agent can tell a tool's area from its name."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

GROUPS = (
    "workspace_", "uefn_", "verse_", "ducky_", "web_", "sandbox_", "skill_",
    "project_memory_", "changeset_",
)

# Names from before the rule. Shrink it; never add to it.
ALLOWED_UNPREFIXED = frozenset({
    # Workflows
    "add_workflow_folder", "clear_workflow_runs", "copy_workflow", "copy_workflow_folder",
    "create_workflow_from_template", "delete_workflow", "delete_workflow_template",
    "edit_workflow_node_code", "emit_workflow_trigger", "export_workflow_folder", "find_workflows",
    "get_workflow", "get_workflow_node_code", "import_workflow_bundle", "list_workflow_nodes",
    "list_workflow_templates", "list_workflow_versions", "list_workflows", "move_workflow_folder",
    "restore_workflow_version", "run_workflow", "run_workflow_node", "save_workflow",
    "save_workflow_template", "set_workflow_folder", "show_workflow", "stop_workflow",
    "test_workflow_node", "tour_workflow", "workflow_code_api",
    # Editor / listener / Verse digests
    "dismiss_uefn_modal", "execute_python", "get_editor_log", "get_log", "get_verse_api",
    "list_verse_devices", "list_verse_digests", "list_verse_modules", "list_verse_types",
    "listener_command", "ping", "reload_listener", "search_verse_digest", "shutdown",
    # IDE helpers
    "clipboard_get_text", "code_detect_project", "code_list_errors", "code_open_file", "view_image",
    # UEFN editor tool that registers in core; editor tools keep their names (skills and plugins call them).
    "get_actor_properties",
})


def _registered() -> set[str]:
    import backend.tools  # noqa: F401 — registers the core tools
    from backend.server import mcp

    return set(mcp._tool_manager._tools)


def _core_registered() -> set[str]:
    # A fresh process: other tests import editor tool modules into the shared server.
    code = "import backend.tools\nfrom backend.server import mcp\nprint('\\n'.join(mcp._tool_manager._tools))"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, timeout=120, check=True)
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def unprefixed(names: set[str]) -> list[str]:
    return sorted(n for n in names if not n.startswith(GROUPS) and n not in ALLOWED_UNPREFIXED)


def test_every_core_tool_name_starts_with_a_group() -> None:
    assert unprefixed(_core_registered()) == [], "prefix new tools with a group (see GROUPS)"


def test_a_new_unprefixed_tool_fails() -> None:
    assert unprefixed({"make_thing", "workspace_make_thing", "list_workflows"}) == ["make_thing"]


def test_alias_tools_are_hidden_but_callable(monkeypatch) -> None:
    from backend.agent import tools as agent_tools
    from backend.tools.panel import ducky_panel as panel

    names = _registered()
    for alias, target in panel.HIDDEN_ALIAS_TOOLS.items():
        assert alias not in names and target in names, alias
    from backend.server import mcp

    listed = {t.name for t in asyncio.run(mcp.list_tools())}
    assert not listed & set(panel.HIDDEN_ALIAS_TOOLS)

    seen: list[tuple[str, dict]] = []

    async def fake_execute(name, args, **_kw):
        seen.append((name, args))
        return agent_tools.ToolCallResult(ok=True, tool=name, data='{"ok": true}')

    async def fake_get_tools(**kw):
        seen.append(("ducky_get_tools", kw))
        return '{"ok": true}'

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    monkeypatch.setattr(panel, "ducky_get_tools", fake_get_tools)
    asyncio.run(panel.ducky_call_tool("ducky_recycle_subagent", {"conv_id": "c1"}))
    asyncio.run(panel.ducky_call_tool("ducky_find_tools", {"query": "meshy"}))
    assert seen[0] == ("ducky_recycle_member", {"conv_id": "c1"})
    assert seen[1][0] == "ducky_get_tools" and seen[1][1]["pattern"] == "meshy"
