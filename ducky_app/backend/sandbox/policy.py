"""What a sandbox never runs, and the approval card for what it does run.

A sandbox is a tidy workspace, not a jail: its programs get their own profile folders
and stop with it, but a program can still write elsewhere on disk if it tries. So the
commands that change the whole PC, outlive the sandbox, or ship something are refused
outright, whatever the chat allowed.
"""

from __future__ import annotations

import json
import re
from typing import Any

_REFUSED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(runas|sudo|gsudo)\b|-Verb\s+RunAs", re.I),
     "Admin rights are never used in a sandbox."),
    (re.compile(r"\bmsiexec\b|\bwinget\b|\bchoco(latey)?\b|\.msi\b|\bAdd-AppxPackage\b", re.I),
     "System installers change the whole PC. Install portably instead: sandbox_setup, pip or npm "
     "inside the sandbox, or a zip into its work folder."),
    (re.compile(r"\breg(\.exe)?\s+(add|delete|import|copy)\b|\bNew-ItemProperty\b.*HK|\bSet-ItemProperty\b.*HK", re.I),
     "Registry changes outlive the sandbox."),
    (re.compile(r"\bsetx\b|SetEnvironmentVariable", re.I),
     "PATH and environment changes outlive the sandbox (it already has its own environment)."),
    (re.compile(r"\bschtasks\b|Register-ScheduledTask|\bNew-Service\b|\bsc(\.exe)?\s+(create|config)\b", re.I),
     "Scheduled tasks and services outlive the sandbox."),
    (re.compile(r"Set-ExecutionPolicy|\bbcdedit\b|\bdiskpart\b|\bformat\s+[a-z]:|\bshutdown\b|\bRestart-Computer\b", re.I),
     "System settings are never changed from a sandbox."),
    (re.compile(
        r"publish_app\.py|\brelease\.py\b[^\n]*--publish|\brelease\.sh\b|\bdeploy\.sh\b|deploy[/\\]prod"
        r"|\bnpm\s+publish\b|\bgh\s+release\b|\btwine\s+upload\b|\bcargo\s+publish\b"
        r"|\bfly(ctl)?\s+deploy\b|\bvercel\b[^\n]*--prod|marketplace_upload|uds_app_release", re.I),
     "A sandbox ends at commit and push: releasing, publishing and deploying are the owner's."),
    (re.compile(r"\bgit\s+push\b", re.I),
     "Push from the project (its git), never from a sandbox copy."),
)


def refusal(command: str) -> str:
    """Why ``command`` never runs in a sandbox, or ''."""
    text = command or ""
    for pattern, why in _REFUSED:
        if pattern.search(text):
            return why
    return ""


def ask_to_run(conv_id: str, what: str, detail: str) -> str:
    """The Allow card in the calling agent's chat. Returns "once", "sandbox", or why not.

    No card when the chat already allows sandbox commands (or everything). Called in the
    process the agent's call arrived in, so the card lands in that agent's chat."""
    from backend.tools.panel import permission_prompt as prompts

    if prompts.allows_sandbox(conv_id):
        return "sandbox"
    from backend.tools.panel.panel_ui import ducky_ask_user

    raw = ducky_ask_user(
        [
            {
                "id": "sandbox_run",
                "prompt": f"Run this in the chat's sandbox? {what}",
                "detail": detail[:1500],
                "options": [
                    {"id": "once", "label": "Allow once", "description": "Just this one. Ask again next time."},
                    {"id": "sandbox", "label": "Allow sandbox commands in this chat",
                     "description": "Commands and programs inside this chat's sandbox run without asking. "
                                    "Admin, system installs, releases and pushes stay refused."},
                    {"id": "deny", "label": "Don't run", "description": "Nothing runs."},
                ],
            }
        ],
        title="Sandbox",
    )
    try:
        out: Any = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return "The approval card could not be shown."
    if not isinstance(out, dict):
        return "The approval card could not be shown."
    if out.get("error"):
        return str(out["error"])
    row = (out.get("answers") or {}).get("sandbox_run") or {}
    picked = {str(x) for x in (row.get("selected") or [])}
    if "sandbox" in picked:
        prompts.allow_sandbox(conv_id)
        return "sandbox"
    if "once" in picked:
        return "once"
    return "The person chose not to run it."
