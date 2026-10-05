"""Approval cards for coding agents (Claude Code's ``--permission-prompt-tool``).

Claude Code runs headless (``-p``). Without a prompt tool, every call its permission
mode does not already allow (a shell command, a write outside the project, a web fetch)
is denied on the spot, and the agent just reports an error. The Anthropic plugin points
``--permission-prompt-tool`` at ``ducky_permission_prompt``, which turns each of those
into an Allow/Deny card in the agent's chat (the ``ducky_ask_user`` path) and answers
Claude Code with ``{"behavior": "allow", "updatedInput": ...}`` or
``{"behavior": "deny", "message": ...}``.

Reads (Read/Glob/Grep/LS) never ask. "Always allow <command> in this chat" is remembered for
the chat (its own ``workspace_state`` row, so saving the chat can't drop it) for plain commands only; a command chained with
``;``/``&&``/``|`` or spanning lines is never remembered on its own, and pushes, force/reset/
clean, deletes, PR/release actions and build/publish/deploy scripts are never remembered that
way. "Allow everything in this chat" (rule ``*``) stops every card in that chat and in the
chats it starts (sub-agents, group members, workflow duckies), those too. The one thing it
never runs: a push or publish of a local-only AI plugin (the owner's rule), which is refused.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any

from backend.server import mcp

_ALLOW_ONCE = "once"
_ALLOW_ALWAYS = "always"
_ALLOW_ALL = "all"
_DENY = "deny"
_QUESTION_ID = "agent_permission"
_ALL_RULE = "*"

_SHELL_TOOLS = frozenset({"Bash", "PowerShell"})
_FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
# Change nothing, so they never ask.
_READ_ONLY_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead"})

# Never remembered: each one asks, with the reason on the card.
_RISKY: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (r"\bgit\s+push\b", "Pushes commits to a remote."),
        (r"\bgit\s+reset\s+--hard\b", "Discards local changes."),
        (r"\bgit\s+clean\b", "Deletes untracked files."),
        (r"\bgit\s+branch\s+-D\b", "Deletes a branch."),
        (r"\bgit\s+(rebase|filter-branch|filter-repo)\b", "Rewrites history."),
        (r"\bgit\s+commit\b.*--amend\b", "Rewrites the last commit."),
        (r"\bgit\s+(checkout|restore)\s+(--\s|\.)", "Discards local changes."),
        (r"\bgit\s+stash\s+(drop|clear)\b", "Deletes stashed changes."),
        (r"\bgit\b.*\s(-f|--force|--force-with-lease)\b", "Forces a git operation."),
        (r"(^|\s)--force\b", "Forces the operation."),
        (r"\bgh\s+(pr\s+(create|merge|close|review)|release|repo\s+(create|delete|edit)|issue\s+(create|close|comment)|api)\b",
         "Changes something on GitHub."),
        (r"\brm\s+-[a-z]*[rf]", "Deletes files."),
        (r"\b(Remove-Item|rmdir|rd)\b", "Deletes files."),
        (r"\bdel\s", "Deletes files."),
        (r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b", "Publishes a package."),
        (r"publish|release\.py|build_exes\.py|make_release_installer|\bdeploy\b", "Builds, publishes or deploys."),
        (r"\b(Stop-Process|taskkill|shutdown)\b", "Stops processes or the machine."),
        (r"\b(curl|wget|Invoke-WebRequest|iwr)\b.*\|\s*(sh|bash|iex|Invoke-Expression)\b", "Runs a downloaded script."),
    )
)

# Local-only AI provider plugins: never sent anywhere (user rule).
_LOCAL_ONLY_PLUGIN_RE = re.compile(r"uefn-plugin-(ollama|anthropic|openai|kimi|spacexai|google)\b", re.IGNORECASE)
_CHAIN_RE = re.compile(r"(;|&&|\|\||\||`|\$\(|>|<|\n)")


def _conv_id() -> str:
    from backend.tools.panel.panel_ui import _resolve_ask_user_conv_id

    return _resolve_ask_user_conv_id()


def _project_root() -> str:
    raw = (os.environ.get("DUCKY_PROJECT_ROOT") or "").strip()
    if raw:
        return raw
    try:
        from frontend.settings import PanelSettings

        return PanelSettings.load().uefn_project_root.strip()
    except Exception:
        return ""


def _command_of(tool_input: dict[str, Any]) -> str:
    return str(tool_input.get("command") or "").strip()


def _command_key(command: str) -> str:
    """Rule key for a plain command: program + subcommand (``git status``, ``npm run test``)."""
    try:
        words = shlex.split(command, posix=False)
    except ValueError:
        words = command.split()
    plain: list[str] = []
    for word in words:
        if word.startswith(("'", '"')):
            break  # a quoted script or message body is not part of the rule
        if word and not word.startswith("-"):
            plain.append(word)
    words = plain
    if not words:
        return ""
    head = os.path.basename(words[0]).lower().removesuffix(".exe")
    take = 3 if head in {"npm", "pnpm", "yarn", "uv", "py", "python", "python3"} and len(words) > 2 else 2
    return " ".join([head, *words[1:take]]).strip()


def _risk(command: str) -> str:
    for pattern, reason in _RISKY:
        if pattern.search(command):
            return reason
    return ""


def describe(tool_name: str, tool_input: dict[str, Any], *, project_root: str = "") -> dict[str, Any]:
    """What the card shows, and the rule key "always allow" would remember ('' = never)."""
    name = (tool_name or "").strip() or "tool"
    if name in _SHELL_TOOLS:
        command = _command_of(tool_input)
        reason = _risk(command)
        chained = bool(_CHAIN_RE.search(command))
        warning = reason
        local_only = bool(_never_runs(command, project_root))
        if local_only:
            warning = "This is a local-only AI plugin. It must never be pushed or published."
        key = "" if reason or chained or not command else f"{name}:{_command_key(command)}"
        desc = str(tool_input.get("description") or "").strip()
        return {
            "prompt": f"Allow the agent to run this command?{f' ({desc})' if desc else ''}",
            "detail": command or "(empty command)",
            "warning": warning,
            "risky": bool(reason) or not command,
            "local_only": local_only,
            "rule": key,
            "rule_label": _command_key(command) if key else "",
        }
    if name in _FILE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "").strip()
        folder = os.path.dirname(path) if path else ""
        return {
            "prompt": f"Allow the agent to {'create' if name == 'Write' else 'edit'} this file?",
            "detail": path or json.dumps(tool_input, ensure_ascii=False)[:2000],
            "warning": "Outside the project folder." if path and project_root and not _is_under(path, project_root) else "",
            "risky": False,
            "rule": f"{name}:{folder.lower()}" if folder else "",
            "rule_label": f"edits in {folder}" if folder else "",
        }
    detail = str(tool_input.get("url") or tool_input.get("query") or "") or json.dumps(tool_input, ensure_ascii=False)[:2000]
    return {
        "prompt": f"Allow the agent to use {name}?",
        "detail": detail,
        "warning": "",
        "risky": False,
        "rule": name,
        "rule_label": name,
    }


def _is_under(path: str, root: str) -> bool:
    try:
        full = os.path.realpath(os.path.abspath(path))
        base = os.path.realpath(os.path.abspath(root))
        return os.path.commonpath([full, base]) == base
    except ValueError:
        return False


def _load_conv(conv_id: str):
    if not conv_id:
        return None
    try:
        from frontend.chat_store import load_conversation

        return load_conversation(conv_id)
    except Exception:
        return None


# Remembered approvals live in their own row per chat, not on the chat record: the app
# saves its in-memory chat during a turn, which would wipe a rule written here mid-turn.
_RULES_TABLE = "workspace_state"


def _rules_key(conv_id: str) -> str:
    return f"agent_allow:{conv_id}"


def _rules_in_db() -> bool:
    try:
        from backend.store.switch import use_db

        return use_db(_RULES_TABLE)
    except Exception:
        return False


def _rules(conv_id: str) -> list[str]:
    """What this chat said to always allow ("*" = everything that isn't risky)."""
    if not conv_id:
        return []
    if _rules_in_db():
        try:
            from backend.store.repos import kv

            doc = kv.get_doc(_RULES_TABLE, _rules_key(conv_id))
            return [str(r) for r in doc if str(r).strip()] if isinstance(doc, list) else []
        except Exception:
            return []
    conv = _load_conv(conv_id)  # files store: on the chat itself
    return list(getattr(conv, "agent_allow_rules", None) or []) if conv is not None else []


def _started_by(conv_id: str) -> str:
    """The chat that started this one: a sub-agent's parent, a group member's leader."""
    doc: dict[str, Any] | None = None
    try:
        from backend.store.repos import chats

        doc = chats.conv_get(conv_id, with_messages=False)
    except Exception:
        doc = None
    if doc is None:
        conv = _load_conv(conv_id)
        if conv is None:
            return ""
        doc = {"parent_conv_id": getattr(conv, "parent_conv_id", ""), "leader_conv_id": getattr(conv, "leader_conv_id", "")}
    return str(doc.get("parent_conv_id") or doc.get("leader_conv_id") or "").strip()


def allows_everything(conv_id: str) -> bool:
    """"Allow everything" was picked in this chat, or in a chat that started it."""
    seen: list[str] = []
    cid = (conv_id or "").strip()
    while cid and cid not in seen and len(seen) < 8:
        if _ALL_RULE in _rules(cid):
            return True
        seen.append(cid)
        cid = _started_by(cid)
    return False


def _never_runs(command: str, project_root: str) -> str:
    """Refused even under "allow everything": pushing or publishing a local-only AI plugin."""
    if _LOCAL_ONLY_PLUGIN_RE.search(f"{command} {project_root}") and re.search(r"\bgit\s+push\b|publish", command, re.IGNORECASE):
        return "This is a local-only AI plugin: it is never pushed or published. Leave it on this PC."
    return ""


def _remember(conv_id: str, rule: str) -> None:
    if not conv_id or not rule:
        return
    rules = _rules(conv_id)
    if rule in rules:
        return
    rules = (rules + [rule])[-200:]
    if _rules_in_db():
        try:
            from backend.store.repos import kv

            kv.set_doc(_RULES_TABLE, _rules_key(conv_id), rules)
        except Exception:
            pass
        return
    conv = _load_conv(conv_id)
    if conv is None:
        return
    conv.agent_allow_rules = rules
    try:
        from frontend.chat_store import save_conversation

        save_conversation(conv)
    except Exception:
        pass


def _ask(card: dict[str, Any], tool_name: str) -> tuple[str, str]:
    """Show the card: (once / always / all / deny, or an error string; the user's typed note)."""
    from backend.tools.panel.panel_ui import ducky_ask_user

    options = [{"id": _ALLOW_ONCE, "label": "Allow once", "description": "Run it this time. Ask again next time."}]
    if card.get("rule"):
        options.append(
            {
                "id": _ALLOW_ALWAYS,
                "label": f"Always allow {card['rule_label']} in this chat",
                "description": "Don't ask again for this in this chat.",
            }
        )
    if not card.get("local_only"):
        options.append(
            {
                "id": _ALLOW_ALL,
                "label": "Allow everything in this chat",
                "description": "Never ask again in this chat or the agents it starts: pushes, deletes and publishes run too.",
            }
        )
    options.append({"id": _DENY, "label": "Deny", "description": "Don't run it. The agent is told you said no."})
    question: dict[str, Any] = {
        "id": _QUESTION_ID,
        "prompt": card["prompt"],
        "detail": card.get("detail") or "",
        "options": options,
        "allow_free_text": True,
    }
    if card.get("warning"):
        question["warning"] = card["warning"]
    raw = ducky_ask_user([question], title=f"Approval needed: {tool_name}")
    try:
        out = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return "Could not show the approval card.", ""
    if not isinstance(out, dict):
        return "Could not show the approval card.", ""
    if out.get("error"):
        return str(out["error"]), ""
    row = (out.get("answers") or {}).get(_QUESTION_ID) or {}
    selected = {str(item) for item in (row.get("selected") or [])}
    note = str(row.get("text") or "").strip()
    for choice in (_DENY, _ALLOW_ALL, _ALLOW_ALWAYS, _ALLOW_ONCE):
        if choice in selected:
            return choice, note
    # Skipped, or typed a reply instead of picking: that is a "no" (with the reason, if any).
    return _DENY, note


def decide(tool_name: str, tool_input: dict[str, Any], *, conv_id: str = "", project_root: str = "") -> dict[str, Any]:
    """Claude Code permission result for one tool call (asks the user unless remembered)."""
    tool_input = dict(tool_input or {})
    if (tool_name or "").strip() in _READ_ONLY_TOOLS:
        return {"behavior": "allow", "updatedInput": tool_input}
    card = describe(tool_name, tool_input, project_root=project_root)
    rule = str(card.get("rule") or "")
    if allows_everything(conv_id):
        refused = _never_runs(_command_of(tool_input), project_root) if (tool_name or "").strip() in _SHELL_TOOLS else ""
        if refused:
            return {"behavior": "deny", "message": refused}
        return {"behavior": "allow", "updatedInput": tool_input}
    if not card.get("risky") and rule and rule in _rules(conv_id):
        return {"behavior": "allow", "updatedInput": tool_input}
    answer, note = _ask(card, tool_name or "tool")
    if answer == _ALLOW_ALL:
        _remember(conv_id, _ALL_RULE)
        return {"behavior": "allow", "updatedInput": tool_input}
    if answer == _ALLOW_ALWAYS:
        _remember(conv_id, rule)
        return {"behavior": "allow", "updatedInput": tool_input}
    if answer == _ALLOW_ONCE:
        return {"behavior": "allow", "updatedInput": tool_input}
    if answer == _DENY:
        message = "The user denied this in the approval card. Don't retry it; ask what to do instead."
        if note:
            message = f"The user denied this and said: {note}"
        return {"behavior": "deny", "message": message}
    return {"behavior": "deny", "message": f"No approval: {answer}"}


@mcp.tool()
def ducky_permission_prompt(tool_name: str, input: dict[str, Any] | None = None, tool_use_id: str = "") -> str:  # noqa: A002 - Claude Code's field name
    """Claude Code permission hook: shows an Allow/Deny card in the chat. Agents never call it.

    Claude Code (``--permission-prompt-tool``) calls this when a tool needs approval and
    reads back ``{"behavior": "allow", "updatedInput": {...}}`` or
    ``{"behavior": "deny", "message": "..."}``.
    """
    del tool_use_id
    result = decide(tool_name, input or {}, conv_id=_conv_id(), project_root=_project_root())
    return json.dumps(result, ensure_ascii=False)
