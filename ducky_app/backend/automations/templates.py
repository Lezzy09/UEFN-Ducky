"""Workflow templates: builtin, plugin (plugin.json), and custom (AppData JSON)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from backend.automations.pipeline_templates import BUILTIN_CATEGORIES, CATEGORY_ORDER, PIPELINE_TEMPLATES
from backend.automations.store import normalize_graph
from frontend.app_paths import resolve_app_data_dir

CUSTOM_PREFIX = "custom:"
_ID_RE = re.compile(r"^custom:[a-z0-9]{8,32}$")


def _announce_templates_changed() -> None:
    try:
        from frontend.ui_web.agent_modes import push_ui_event

        push_ui_event({"type": "templates_changed"})
    except Exception:
        pass


def list_custom() -> list[dict[str, Any]]:
    folder = _dir()
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        row = _read(path)
        if row:
            out.append(row)
    return out


def save_custom(
    name: str,
    *,
    description: str = "",
    icon: str = "⚡",
    graph: Any = None,
    template_id: str = "",
    category: str = "",
) -> dict[str, Any]:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Template name is required")
    tid = (template_id or "").strip()
    if tid:
        if not _ID_RE.match(tid):
            raise ValueError("Only custom:… templates can be edited")
    else:
        tid = f"{CUSTOM_PREFIX}{uuid.uuid4().hex[:12]}"
    row = {
        "id": tid,
        "name": cleaned[:64],
        "label": cleaned[:64],
        "description": str(description or "")[:240],
        "icon": (icon or "⚡").strip()[:16] or "⚡",
        "kind": "custom",
        "category": _category(category, "Yours"),
        "graph": normalize_graph(graph),
    }
    dest = _dir(for_write=True) / f"{tid.split(':', 1)[-1]}.json"
    dest.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    _announce_templates_changed()
    return row


def delete_custom(template_id: str) -> bool:
    tid = (template_id or "").strip()
    if not _ID_RE.match(tid):
        return False
    path = _dir() / f"{tid.split(':', 1)[-1]}.json"
    if not path.is_file():
        return False
    path.unlink()
    _announce_templates_changed()
    return True


_PRIVATE_PROMPT = (
    "Load skill_read_subskill('ducky', 'publish_private'). Do only Upload to "
    "Private Version. When 'Private version has been created!' is up, copy the "
    "island code, press OK to close the popup, and put the code in your reply."
)
_MEMORY_PROMPT = (
    "Load skill_read_subskill('ducky', 'publish_private'). Do Launch Memory "
    "Calculation. First set the Launch Session menu to Launch on this PC if "
    "another platform is selected. If 'Private version has been created!' "
    "appears, copy the code, put it in your reply, and press OK so the client "
    "can start the calculation. Report the memory result when it returns."
)


_TYCOON_PLAYTEST_PROMPT = (
    "A play session is already running with a player in it. You are play-testing a "
    "tycoon island. Use the tester tools only (session_status, actor_state_snapshot, "
    "actor_state_diff, get_editor_log, device_graph_snapshot, simulate_device_event, "
    "verse_test_results) — never restart UEFN, stop the session, or edit Verse in this run. "
    "Check in order: 1) the player spawned on a pad and the starting money / HUD value is "
    "the expected one; 2) the first purchase (buy button or dropper pad) is affordable from "
    "the start and fires — a '[Tycoon]' log line or a device trace; 3) income ticks up "
    "while the player idles for 30 seconds; 4) dropped items reach the collector / cash-in "
    "point; 5) a second tier or rebirth exists and is reachable. Reply with PASS or FAIL "
    "per item, the evidence (log lines, snapshot diffs), and one fix suggestion per FAIL."
)

_TYCOON_LOG_HINT = (
    "Your Verse must Print a '[Tycoon] …' line for the event: purchase lines mention "
    "purchase, bought or buy; income lines mention income, earned or tick."
)


def _launch_prefix(starter: str = "start.manual") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check UEFN → is it running? → Wait for UEFN (yes) / Open UEFN project (no).

    Both wires must be joined to the template's next node (ids ``w`` and ``o``).
    Nothing here launches an editor that is already up.
    """
    nodes: list[dict[str, Any]] = [
        {"id": "s", "type": starter, "x": 0, "y": 120, "config": {}},
        {"id": "c", "type": "uefn.check", "x": 240, "y": 120, "config": {}},
        {
            "id": "b",
            "type": "flow.branch",
            "x": 480,
            "y": 120,
            "label": "UEFN running?",
            "config": {"mode": "data", "field": "running", "op": "equals", "equals": "true"},
        },
        {"id": "w", "type": "uefn.wait_ready", "x": 760, "y": 0, "config": {"timeout": 180}},
        {"id": "o", "type": "uefn.open_project", "x": 760, "y": 240, "config": {"project": "", "timeout": 300}},
    ]
    edges: list[dict[str, Any]] = [
        {"source": "s", "target": "c", "kind": "main"},
        {"source": "c", "target": "b", "kind": "main"},
        {"source": "b", "target": "w", "kind": "true"},
        {"source": "b", "target": "o", "kind": "false"},
    ]
    return nodes, edges


def _after_launch(
    tail: list[dict[str, Any]],
    tail_edges: list[dict[str, Any]],
    *,
    starter: str = "start.manual",
) -> dict[str, Any]:
    """Launch prefix + ``tail`` whose first node receives both prefix wires."""
    nodes, edges = _launch_prefix(starter)
    first = str(tail[0]["id"])
    edges += [{"source": "w", "target": first, "kind": "main"}, {"source": "o", "target": first, "kind": "main"}]
    return {"nodes": nodes + tail, "edges": edges + tail_edges}


_START_GAME = {
    "id": "g",
    "type": "uefn.game.start",
    "x": 1040,
    "y": 120,
    "config": {"skip_if_playing": True, "wait_player": 90},
}


BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "builtin:playtest-start",
        "name": "Play test: open UEFN and start the game",
        "label": "Play test: open UEFN and start the game",
        "description": (
            "Check UEFN first. Running: wait for the listener. Closed: open the project. "
            "Then start the session (skipped when one is already playing) and wait for a player."
        ),
        "icon": "🎮",
        "kind": "builtin",
        "graph": _after_launch(
            [
                dict(_START_GAME),
                {"id": "f", "type": "pipeline.finish", "x": 1300, "y": 120, "config": {"message": "Game session is running and a player is in."}},
            ],
            [{"source": "g", "target": "f", "kind": "main"}],
        ),
    },
    {
        "id": "builtin:stop-game",
        "name": "Stop the game session",
        "label": "Stop the game session",
        "description": "End the play session. Does nothing when nothing is playing or UEFN is closed.",
        "icon": "⏹",
        "kind": "builtin",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start.manual", "x": 0, "y": 0, "config": {}},
                {"id": "x", "type": "uefn.game.stop", "x": 240, "y": 0, "config": {}},
                {"id": "f", "type": "pipeline.finish", "x": 480, "y": 0, "config": {"message": "Game session stopped."}},
            ],
            "edges": [{"source": "s", "target": "x", "kind": "main"}, {"source": "x", "target": "f", "kind": "main"}],
        },
    },
    {
        "id": "builtin:tycoon-first-purchase",
        "name": "Tycoon test: compile, play, first purchase",
        "label": "Tycoon test: compile, play, first purchase",
        "description": (
            "Open or reuse UEFN, compile Verse (stops on errors), start the game, wait for a "
            "player, then wait for the first '[Tycoon] purchase' log line. " + _TYCOON_LOG_HINT
        ),
        "icon": "🏭",
        "kind": "builtin",
        "graph": _after_launch(
            [
                {"id": "v", "type": "tool.call", "x": 1040, "y": 120, "config": {"name": "workspace_compile_verse", "arguments": {}}},
                {
                    "id": "vb",
                    "type": "flow.branch",
                    "x": 1300,
                    "y": 120,
                    "label": "Verse errors?",
                    "config": {"mode": "data", "field": "data.hints", "op": "exists"},
                },
                {"id": "fe", "type": "pipeline.finish", "x": 1580, "y": 0, "config": {"message": "Verse has compile errors — fix them before the play test."}},
                {**_START_GAME, "x": 1580, "y": 240},
                {
                    "id": "e",
                    "type": "uefn.log.expect",
                    "x": 1840,
                    "y": 240,
                    "config": {"regex": r"\[Tycoon\].*(purchase|bought|buy)", "timeout": 120},
                },
                {"id": "f", "type": "pipeline.finish", "x": 2100, "y": 240, "config": {"message": "First purchase seen in the log."}},
            ],
            [
                {"source": "v", "target": "vb", "kind": "main"},
                {"source": "vb", "target": "fe", "kind": "true"},
                {"source": "vb", "target": "g", "kind": "false"},
                {"source": "g", "target": "e", "kind": "main"},
                {"source": "e", "target": "f", "kind": "main"},
            ],
        ),
    },
    {
        "id": "builtin:tycoon-income-loop",
        "name": "Tycoon test: income keeps ticking",
        "label": "Tycoon test: income keeps ticking",
        "description": (
            "Open or reuse UEFN, start the game, wait for a player, idle 30 seconds, then "
            "expect a '[Tycoon] income' log line. " + _TYCOON_LOG_HINT
        ),
        "icon": "💰",
        "kind": "builtin",
        "graph": _after_launch(
            [
                dict(_START_GAME),
                {"id": "i", "type": "flow.wait", "x": 1300, "y": 120, "config": {"seconds": 30}},
                {
                    "id": "e",
                    "type": "uefn.log.expect",
                    "x": 1560,
                    "y": 120,
                    "config": {"regex": r"\[Tycoon\].*(income|earned|tick)", "timeout": 60},
                },
                {"id": "f", "type": "pipeline.finish", "x": 1820, "y": 120, "config": {"message": "Income ticked while the player idled."}},
            ],
            [
                {"source": "g", "target": "i", "kind": "main"},
                {"source": "i", "target": "e", "kind": "main"},
                {"source": "e", "target": "f", "kind": "main"},
            ],
        ),
    },
    {
        "id": "builtin:tycoon-ducky-playtest",
        "name": "Tycoon play test by a ducky",
        "label": "Tycoon play test by a ducky",
        "description": (
            "Open or reuse UEFN, start the game, wait for a player, then a ducky checks the "
            "tycoon loop (spawn, first purchase, income, collector, next tier) and reports PASS/FAIL."
        ),
        "icon": "🦆",
        "kind": "builtin",
        "graph": _after_launch(
            [
                dict(_START_GAME),
                {
                    "id": "a",
                    "type": "pipeline.agent",
                    "x": 1300,
                    "y": 120,
                    "config": {"ducky": "", "timeout_sec": 900, "prompt": _TYCOON_PLAYTEST_PROMPT},
                },
                {"id": "f", "type": "pipeline.finish", "x": 1560, "y": 120, "config": {}},
            ],
            [
                {"source": "g", "target": "a", "kind": "main"},
                {"source": "a", "target": "f", "kind": "main"},
            ],
            starter="start.chat",
        ),
    },
    {
        "id": "builtin:open-uefn-project",
        "name": "Open UEFN project",
        "label": "Open UEFN project",
        "description": "Launch UEFN from closed and wait for your island. Choose a saved project on the Open UEFN project node.",
        "icon": "📂",
        "kind": "builtin",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}},
                {"id": "o", "type": "uefn.open_project", "x": 280, "y": 0, "config": {"project": "", "timeout": 180}},
                {"id": "f", "type": "pipeline.finish", "x": 560, "y": 0, "config": {}},
            ],
            "edges": [{"source": "s", "target": "o", "kind": "main"}, {"source": "o", "target": "f", "kind": "main"}],
        },
    },
    {
        "id": "builtin:restart-uefn",
        "name": "Restart UEFN into project",
        "label": "Restart UEFN into project",
        "description": "Close UEFN and reopen the current project, then wait until connected.",
        "icon": "↻",
        "kind": "builtin",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start.manual", "x": 0, "y": 0, "config": {}},
                {"id": "r", "type": "uefn.restart", "x": 220, "y": 0, "config": {"timeout": 180}},
            ],
            "edges": [{"source": "s", "target": "r", "kind": "main"}],
        },
    },
    {
        "id": "builtin:publish-private",
        "name": "Upload private version to code",
        "label": "Upload private version to code",
        "description": "Project > Upload to Private Version, press Copy, press OK, post the code.",
        "icon": "↑",
        "kind": "builtin",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}},
                {"id": "w", "type": "uefn.wait_ready", "x": 200, "y": 0, "config": {"timeout": 180}},
                {
                    "id": "a",
                    "type": "pipeline.agent",
                    "x": 420,
                    "y": 0,
                    "config": {
                        "ducky": "verse-coder",
                        "timeout_sec": 900,
                        "prompt": _PRIVATE_PROMPT,
                    },
                },
                {"id": "f", "type": "pipeline.finish", "x": 660, "y": 0, "config": {}},
            ],
            "edges": [
                {"source": "s", "target": "w", "kind": "main"},
                {"source": "w", "target": "a", "kind": "main"},
                {"source": "a", "target": "f", "kind": "main"},
            ],
        },
    },
    {
        "id": "builtin:memory-calculation",
        "name": "Launch memory calculation",
        "label": "Launch memory calculation",
        "description": (
            "Set Launch on this PC, then Project > Launch Memory Calculation. "
            "If a private-code popup appears, Copy, post the code, and press OK."
        ),
        "icon": "▦",
        "kind": "builtin",
        "graph": {
            "nodes": [
                {"id": "s", "type": "start.chat", "x": 0, "y": 0, "config": {}},
                {"id": "w", "type": "uefn.wait_ready", "x": 200, "y": 0, "config": {"timeout": 180}},
                {
                    "id": "a",
                    "type": "pipeline.agent",
                    "x": 420,
                    "y": 0,
                    "config": {
                        "ducky": "verse-coder",
                        "timeout_sec": 900,
                        "prompt": _MEMORY_PROMPT,
                    },
                },
                {"id": "f", "type": "pipeline.finish", "x": 660, "y": 0, "config": {}},
            ],
            "edges": [
                {"source": "s", "target": "w", "kind": "main"},
                {"source": "w", "target": "a", "kind": "main"},
                {"source": "a", "target": "f", "kind": "main"},
            ],
        },
    },
]


def _category(raw: Any, fallback: str) -> str:
    text = " ".join(str(raw or "").split())[:40]
    return text or fallback


def categories() -> list[str]:
    """The picker's shelves, in order (custom categories people typed come after)."""
    return list(CATEGORY_ORDER)


def list_templates() -> list[dict[str, Any]]:
    """Builtin templates and ready-made pipelines, then plugin contrib (enabled only),
    then user custom. Each says its category and the plugins it needs."""
    out: list[dict[str, Any]] = []
    try:
        from backend.uefn_plugins.host import get_ui_contributions
        from backend.uefn_plugins.store import get_enabled_plugin_ids

        enabled = set(get_enabled_plugin_ids())
        contrib = get_ui_contributions()
    except Exception:
        contrib, enabled = {}, None
    for row in [*PIPELINE_TEMPLATES, *BUILTIN_TEMPLATES]:
        name = str(row.get("label") or row.get("name") or row.get("id"))
        graph = normalize_graph(row.get("graph"))
        required = _template_requires(row, graph)
        missing = [p for p in required if enabled is not None and p not in enabled]
        out.append(
            {
                "id": str(row["id"]),
                "name": name,
                "label": name,
                "description": str(row.get("description") or ""),
                "icon": str(row.get("icon") or "⚡"),
                "kind": "builtin",
                "category": _category(row.get("category") or BUILTIN_CATEGORIES.get(str(row["id"])), "UEFN"),
                "graph": graph,
                "requires_plugins": required,
                "missing_plugins": missing,
                "ready": not missing,
            }
        )
    enabled = enabled or set()
    for row in contrib.get("automations_templates") or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("plugin_id") or "")
        if pid and pid not in enabled:
            continue
        tid = str(row.get("id") or "").strip()
        if not tid:
            continue
        name = str(row.get("label") or row.get("name") or tid)
        graph = normalize_graph(row.get("graph"))
        required = _template_requires(row, graph)
        missing = [p for p in required if p not in enabled]
        out.append(
            {
                "id": f"plugin:{pid}:{tid}" if pid else tid,
                "name": name,
                "label": name,
                "description": str(row.get("description") or ""),
                "icon": str(row.get("icon") or "⚡"),
                "kind": "plugin",
                "plugin_id": pid,
                "category": _category(row.get("category"), "Plugins"),
                "graph": graph,
                "requires_plugins": required,
                "missing_plugins": missing,
                "ready": not missing,
            }
        )
    out.extend(list_custom())
    return out


_NODE_PLUGIN = {
    "discord.send": "discord",
    "discord.message": "discord",
}


def _template_requires(row: dict[str, Any], graph: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for raw in row.get("requires_plugins") or []:
        pid = str(raw or "").strip()
        if pid and pid not in seen:
            seen.append(pid)
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        pid = _NODE_PLUGIN.get(ntype) or _media_plugin(node)
        if not pid and ntype == "tool.call":
            cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
            name = str(cfg.get("name") or "")
            if name.startswith("meshy_"):
                pid = "meshy"
            elif name.startswith("blender_"):
                pid = "blender"
            elif name.startswith("studio3d_"):
                pid = "studio3d"
            elif name.startswith("discord_"):
                pid = "discord"
        if pid and pid not in seen:
            seen.append(pid)
    return seen


def _media_plugin(node: dict[str, Any]) -> str:
    """The plugin an image / 3D / Blender / UEFN node runs on: its picked backend's, else
    the first one (the default it was designed with, not whatever is set up on this PC)."""
    ntype = str(node.get("type") or "")
    if ntype.startswith("blender."):
        return "blender"
    if ntype == "uefn.import":
        return "uefn"
    from backend.automations.media import table

    rows = table(ntype)
    if not rows:
        return ""
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    wanted = str(cfg.get("backend") or "")
    if wanted == "agent":
        return ""  # any gateway or agent: no one plugin is required
    row = next((r for r in rows if r["id"] == wanted), rows[0])
    return str(row.get("plugin_id") or "")


def _dir(*, for_write: bool = False) -> Path:
    path = resolve_app_data_dir(for_write=for_write) / "automation_templates"
    if for_write:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tid = str(data.get("id") or "").strip()
    if not _ID_RE.match(tid):
        return None
    name = str(data.get("name") or data.get("label") or "").strip()
    if not name:
        return None
    return {
        "id": tid,
        "name": name,
        "label": name,
        "description": str(data.get("description") or ""),
        "icon": str(data.get("icon") or "⚡"),
        "kind": "custom",
        "category": _category(data.get("category"), "Yours"),
        "graph": normalize_graph(data.get("graph")),
    }
