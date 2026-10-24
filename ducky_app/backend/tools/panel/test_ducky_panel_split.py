"""Plan step tools and terminal tools moved out of ducky_panel.py, registered as before."""
import subprocess
import sys
from pathlib import Path

PLAN_TOOLS = ["ducky_get_plan", "ducky_plan_add_node", "ducky_plan_delete_node",
              "ducky_plan_move_node", "ducky_plan_update_node"]
TERMINAL_TOOLS = ["ducky_terminal_close", "ducky_terminal_list", "ducky_terminal_open",
                  "ducky_terminal_read_output", "ducky_terminal_run"]


def _registered_in_fresh_process(first_import: str) -> list[str]:
    # A fresh process, so the moved modules may be imported before ducky_panel.
    code = (f"import {first_import}\nimport backend.tools\nfrom backend.server import mcp\n"
            "print('\\n'.join(sorted(mcp._tool_manager._tools)))")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3],
                         capture_output=True, text=True, timeout=120, check=True)
    return out.stdout.split()


def test_moved_tools_live_in_their_modules_and_ducky_panel_reexports_them():
    import backend.tools  # noqa: F401
    from backend.server import mcp
    from backend.tools.panel import ducky_panel, ducky_panel_plans, ducky_panel_terminal

    tools = mcp._tool_manager._tools
    for names, module in ((PLAN_TOOLS, ducky_panel_plans), (TERMINAL_TOOLS, ducky_panel_terminal)):
        for name in names:
            assert tools[name].fn is getattr(module, name), name
            assert getattr(ducky_panel, name) is getattr(module, name), name


def test_registered_names_do_not_depend_on_import_order():
    via_panel = _registered_in_fresh_process("backend.tools.panel.ducky_panel")
    via_plans = _registered_in_fresh_process("backend.tools.panel.ducky_panel_plans")
    via_terminal = _registered_in_fresh_process("backend.tools.panel.ducky_panel_terminal")
    assert via_panel == via_plans == via_terminal
    assert set(PLAN_TOOLS + TERMINAL_TOOLS) <= set(via_panel)


def test_plan_tools_follow_ducky_panel_patches(monkeypatch):
    from backend.tools.panel import ducky_panel, ducky_panel_plans

    monkeypatch.setattr(ducky_panel, "_project_root", lambda: "patched-root")
    monkeypatch.setattr(ducky_panel, "_resolve_plan_chat_id", lambda cid="": "patched-chat")
    assert ducky_panel_plans._project_root() == "patched-root"
    assert ducky_panel_plans._resolve_plan_chat_id("") == "patched-chat"
