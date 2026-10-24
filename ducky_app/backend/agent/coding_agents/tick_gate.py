"""Tick gate: a group member can't complete a plan step while its lane has uncommitted files.

``check_tick(chat_id, node)`` is called by the plan store when a member sets a step to
completed; it returns None (tick) or the refusal text. Only laned chats (group members) are
gated: the lead and solo chats resolve no lane and always pass. A lane outside git passes.
Swarm plans commit locally and push once at the end, so only uncommitted files count here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.workspace import lanes as lane_rules

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_SHOWN = 20


def _git(cwd: Path, *args: str) -> bytes | None:
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.quotepath=off", "-C", str(cwd), *args],
            capture_output=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _toplevel(path: Path) -> Path | None:
    while not path.is_dir():
        if path.parent == path:
            return None
        path = path.parent
    out = _git(path, "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8", "replace").strip()) if out else None


def _bases(lane: Sequence[str]) -> list[Path]:
    """Folders a lane covers: the open project for relative globs, the literal prefix of full ones."""
    roots = lane_rules.project_roots()
    out: list[Path] = []
    for glob in lane:
        if lane_rules._is_abs(glob):
            try:
                out.append(Path(lane_rules.literal_prefix(glob)))
            except lane_rules.LaneGlobError:  # its project left the list: covers nothing now
                continue
        elif roots:
            out.append(Path(roots[0]))
    return list(dict.fromkeys(out))


def _shown(full: str) -> str:
    """Project-relative inside the open project (what the lane globs say), full path elsewhere."""
    roots = lane_rules.project_roots()
    root = roots[0] if roots else ""
    if root and lane_rules._inside(full, root) and len(full) > len(root):
        return full[len(root) + 1:]
    return full


def _in_lane(lane: Sequence[str], full: str) -> bool:
    return lane_rules.in_lane(lane, _shown(full))


def _repo_files(lane: Sequence[str], *git_args: str, parse_status: bool = False) -> list[str]:
    seen: list[str] = []
    for top in dict.fromkeys(t for t in map(_toplevel, _bases(lane)) if t is not None):
        out = _git(top, *git_args)
        if out is None:
            continue
        parts = iter(out.split(b"\0"))
        for entry in parts:
            if not entry:
                continue
            rel = entry.decode("utf-8", "replace")
            if parse_status:
                code, rel = rel[:2], rel[3:]
                if "R" in code or "C" in code:
                    next(parts, None)  # -z: the rename's old path follows as its own entry
            full = f"{top.as_posix().rstrip('/')}/{rel.rstrip('/')}"
            if _in_lane(lane, full):
                seen.append(_shown(full))
    return list(dict.fromkeys(seen))


def lane_dirty_files(lanes: Sequence[str]) -> list[str]:
    """Uncommitted files (modified, staged, untracked, deleted) inside these lane globs,
    across every git repo the lane covers. Lanes outside git have none."""
    return _repo_files(lanes, "status", "--porcelain=v1", "-z", "--untracked-files=all", parse_status=True)


def check_tick(chat_id: str, node: Mapping[str, Any] | None = None) -> str | None:
    """None when the step may be completed, else why not. ``node`` is the step being ticked."""
    del node
    lane = lane_rules.resolve_lane(chat_id)
    if not lane:  # lead, solo chat, or read-only member: nothing of theirs to commit
        return None
    dirty = lane_dirty_files(lane)
    if dirty:
        listed = ", ".join(dirty[:MAX_SHOWN]) + (f", …and {len(dirty) - MAX_SHOWN} more" if len(dirty) > MAX_SHOWN else "")
        return (
            f"Can't tick: {len(dirty)} file{'s' if len(dirty) != 1 else ''} in your lane "
            f"{'aren' if len(dirty) != 1 else 'isn'}'t committed: {listed}. Commit them (stage these files by "
            "name), then tick the step again."
        )
    return None
