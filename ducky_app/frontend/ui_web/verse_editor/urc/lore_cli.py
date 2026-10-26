"""Read-only island sync state via UEFN's ``lore.exe`` CLI (status, history, revision diff, locks).

Never syncs, pushes, commits or stages. Text output only (lore 0.8.6 has no JSON flag).
Lore prints paths relative to the CWD, so every command runs with cwd = the island root.
Parsing is pure (``parse_*``, ``compare_histories``); ``_run_lore`` is the only subprocess
call (tests patch it).

Sync state is measured against the remote ``main`` branch, not ``lore status``'s "Remote
revision": after an editor save UEFN moves the island to a personal ``main-<id>`` branch and
pushes its autosave there, so status reads "in sync" while ``main`` still lacks the change.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from frontend.ui_web.verse_editor.urc.detect_urc import detect_lore_executable

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
# The shared branch every PC checks in to.
REMOTE_BRANCH = "main"
# Revisions walked (first parent) to find where local and remote main histories meet.
_HISTORY_DEPTH = 200

_BRANCH_RE = re.compile(r"^On branch (\S+) revision (\d+) -> ([0-9a-f]+)")
_ENTRY_RE = re.compile(r"^([A-Z]) (.+)$")
_FIELD_RE = re.compile(r"^(Revision|Signature|Merge|Creator)\s*:\s*(.+)$")
# Epic display names pad with invisible fillers (Hangul filler U+3164 and kin): "Michㅤㅤou".
_FILLERS = re.compile("[ᅟᅠㅤﾠ​-‍⠀]+")
# ``lore lock query``: "<rel> by <name> on branch <id>"; ``lore lock status``: "... on <date>".
_LOCK_RE = re.compile(r"^(.+) by (.+?) on (?:branch \S+|\w{3}, .+)$")
# ``lore auth info``: "ID: <hex>" / "Name: <display name>".
_AUTH_RE = re.compile(r"^(ID|Name):\s*(.*)$")
_ME_TTL_S = 600.0  # the signed-in account rarely changes: one ``auth info`` per 10 min
_me_cache: dict[str, tuple[float, dict[str, str]]] = {}
_me_lock = threading.Lock()
# Per-user editor collections, never shared between PCs.
_EXCLUDED_PREFIX = "content/developers/"


def _norm(path: str) -> str:
    return path.strip().replace("\\", "/")


def parse_entry(line: str) -> tuple[str, str] | None:
    """``A Content/Foo.uasset`` → ``("A", "Content/Foo.uasset")``. Directories keep their ``/``."""
    m = _ENTRY_RE.match(line.rstrip())
    if not m:
        return None
    path = m.group(2)
    if " -> " in path:  # move/copy: the new location is what the remote lacks
        path = path.split(" -> ", 1)[1]
    return m.group(1), _norm(path)


def parse_status(text: str) -> dict[str, Any]:
    """Parse ``lore status``: repository, local branch/head, and working-tree changes.

    Entries under "Untracked files:" go to ``untracked``; every other change section (staged,
    dirty) goes to ``staged`` as ``(code, rel)`` pairs. Its "Remote revision" / "Local branch is
    …" lines track the current (maybe personal) branch, so they are ignored.
    """
    out: dict[str, Any] = {
        "repository": "",
        "local_branch": "",
        "local_revision": None,
        "local_signature": "",
        "staged": [],
        "untracked": [],
    }
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Repository "):
            out["repository"] = line.split(" ", 1)[1].strip()
        elif m := _BRANCH_RE.match(line):
            out["local_branch"] = m.group(1)
            out["local_revision"] = int(m.group(2))
            out["local_signature"] = m.group(3)
        elif line.endswith(":") and not _ENTRY_RE.match(line):
            section = "untracked" if line.lower().startswith("untracked") else "staged"
        elif section and (entry := parse_entry(raw)):
            out[section].append(entry)
    return out


def parse_history(text: str) -> list[dict[str, Any]]:
    """``lore history`` (full format) → ``[{revision, signature, merges, creator, message}]``,
    newest first.

    The list follows first parents; ``merges`` holds the other parent(s) a check-in merged in
    (UEFN merges the personal autosave branch into ``main``). ``creator`` is the Epic display
    name as lore prints it, ``message`` the first line of the check-in description.
    """
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        m = _FIELD_RE.match(raw.strip())
        if not m:
            if out and raw[:1].isspace() and raw.strip() and not out[-1]["message"]:
                out[-1]["message"] = raw.strip()
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "Revision":
            out.append({"revision": int(val) if val.isdigit() else None, "signature": "", "merges": [],
                        "creator": "", "message": ""})
        elif out and key == "Signature":
            out[-1]["signature"] = val
        elif out and key == "Creator":
            out[-1]["creator"] = val
        elif out:
            out[-1]["merges"].extend(val.split())
    return out


def display_name(name: str) -> str:
    """An Epic display name without its invisible padding: "Michㅤㅤou" → "Mich ou"."""
    return " ".join(_FILLERS.sub(" ", name or "").split())


def parse_locks(text: str) -> list[dict[str, str]]:
    """``lore lock query`` / ``lore lock status`` → ``[{rel, owner_raw}]`` (``owner_raw`` as lore
    prints it, invisible padding included). Header lines ("Locks found:", "Files locked for
    edit:") and anything else are skipped."""
    out: list[dict[str, str]] = []
    for raw in text.splitlines():
        m = _LOCK_RE.match(raw.strip())
        if m:
            out.append({"rel": _norm(m.group(1)), "owner_raw": m.group(2).strip()})
    return out


def parse_auth_info(text: str) -> dict[str, str]:
    """``lore auth info`` → ``{id, name}`` (``name`` raw, padding included; "" when missing)."""
    out = {"id": "", "name": ""}
    for raw in text.splitlines():
        m = _AUTH_RE.match(raw.strip())
        if m:
            out["id" if m.group(1) == "ID" else "name"] = m.group(2).strip()
    return out


def _reachable(history: list[dict[str, Any]]) -> set[str]:
    return {sig for rev in history for sig in (rev["signature"], *rev["merges"]) if sig}


def compare_histories(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> dict[str, Any]:
    """Local head vs remote main head → {merge_base, behind, ahead, in_sync}.

    merge_base = newest local first-parent revision the remote reaches ("" when none in range).
    behind = remote head not in the local ancestry; ahead = local head not reachable from remote.
    """
    local_head = local[0]["signature"] if local else ""
    remote_head = remote[0]["signature"] if remote else ""
    remote_set = _reachable(remote)
    base = next((rev["signature"] for rev in local if rev["signature"] in remote_set), "")
    behind = bool(remote_head) and remote_head not in _reachable(local)
    ahead = bool(local_head) and base != local_head
    return {"merge_base": base, "behind": behind, "ahead": ahead, "in_sync": not behind and not ahead}


def incoming(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remote main's first-parent revisions the local head lacks, newest first:
    ``[{revision, signature, creator, message, own}]``. ``own``: the check-in merges a revision
    the local history already has (this PC's own autosave checked in to main), so it brings
    nothing made elsewhere."""
    local_set = _reachable(local)
    out: list[dict[str, Any]] = []
    for rev in remote:
        if rev["signature"] in local_set:
            break
        out.append({
            "revision": rev["revision"],
            "signature": rev["signature"],
            "creator": display_name(rev.get("creator", "")),
            "message": rev.get("message", ""),
            "own": any(sig in local_set for sig in rev["merges"]),
        })
    return out


def parse_revision_diff(text: str) -> list[tuple[str, str]]:
    """``lore revision diff`` lines → ``(code, rel)`` pairs. Directories are listed without ``/``."""
    return [e for line in text.splitlines() if (e := parse_entry(line))]


def _excluded(rel: str) -> bool:
    return (rel.lower().rstrip("/") + "/").startswith(_EXCLUDED_PREFIX)


def to_pending_files(project_root: str, entries: list[tuple[str, str]]) -> list[str]:
    """Absolute forward-slash paths of files that exist on disk, deduped, in order.

    Deletes (``D``) and anything missing on disk are dropped: there is no file to send.
    An untracked ``dir/`` expands to the files under it (lore lists only the folder). Bare
    directory lines from ``revision diff`` are skipped: it lists their files too.
    """
    root = Path(project_root)
    seen: set[str] = set()
    out: list[str] = []

    def add(p: Path) -> None:
        rel = p.relative_to(root).as_posix()
        if _excluded(rel):
            return
        abs_path = p.as_posix()
        if abs_path not in seen:
            seen.add(abs_path)
            out.append(abs_path)

    for code, rel in entries:
        if code == "D" or not rel or rel.startswith("../") or _excluded(rel):
            continue
        p = root / rel.rstrip("/")
        if rel.endswith("/"):
            for child in sorted(p.rglob("*")) if p.is_dir() else []:
                if child.is_file():
                    add(child)
        elif p.is_file():
            add(p)
    return out


def _run_lore(project_root: str, args: list[str], timeout: float) -> tuple[bool, str]:
    """Run ``lore.exe -P --repository <root> <args>``. Returns (ok, stdout or error)."""
    detected = detect_lore_executable()
    if not detected.get("available"):
        return False, str(detected.get("error") or "lore.exe not found")
    cmd = [str(detected["path"]), "-P", "--repository", project_root, *args]
    kwargs: dict[str, object] = {
        "cwd": project_root,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, **kwargs)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired:
        return False, f"lore {args[0]} timed out after {timeout:g}s"
    except OSError as exc:
        return False, f"lore {args[0]} failed: {exc}"
    stdout = proc.stdout or ""
    if proc.returncode != 0 or stdout.lstrip().startswith("[Error]"):
        err = (proc.stderr or stdout).strip().splitlines()
        return False, (err[0] if err else f"lore {args[0]} exited {proc.returncode}")
    return True, stdout


def _failed(error: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, **extra, "error": error}


def _state(project_root: str, timeout: float) -> tuple[dict[str, Any] | None, str]:
    """status + local history + remote main history → parsed state (with ``merge_base``)."""
    if not (Path(project_root) / ".lore").is_dir():
        return None, "not a Lore repository (no .lore folder)"
    ok, out = _run_lore(project_root, ["status"], timeout)
    if not ok:
        return None, out
    st = parse_status(out)
    if not st["local_signature"]:
        return None, "lore status shows no current revision"
    depth = str(_HISTORY_DEPTH)
    ok, local_out = _run_lore(project_root, ["history", depth, "--revision", st["local_signature"]], timeout)
    if not ok:
        return None, local_out
    ok, remote_out = _run_lore(project_root, ["--remote", "history", depth, "--branch", REMOTE_BRANCH], timeout)
    if not ok:
        return None, remote_out
    remote = parse_history(remote_out)
    if not remote:
        return None, f"remote branch {REMOTE_BRANCH} has no revisions"
    local = parse_history(local_out)
    cmp = compare_histories(local, remote)
    if not cmp["merge_base"]:
        return None, f"no revision shared with remote {REMOTE_BRANCH} in the last {depth}"
    st.update(
        cmp,
        remote_branch=REMOTE_BRANCH,
        remote_revision=remote[0]["revision"],
        remote_signature=remote[0]["signature"],
        incoming=incoming(local, remote),
    )
    return st, ""


def _head(project_root: str, args: list[str], timeout: float) -> dict:
    if not (Path(project_root) / ".lore").is_dir():
        return _failed("not a Lore repository (no .lore folder)")
    ok, out = _run_lore(project_root, args, timeout)
    if not ok:
        return _failed(out)
    if args == ["status"]:
        st = parse_status(out)
        rev, sig = st["local_revision"], st["local_signature"]
    else:
        hist = parse_history(out)
        rev, sig = (hist[0]["revision"], hist[0]["signature"]) if hist else (None, "")
    if not sig:
        return _failed("lore shows no revision")
    return {"ok": True, "revision": rev, "signature": sig, "error": ""}


def remote_head(project_root: str, *, timeout: float = 30.0) -> dict:
    """{ok, revision, signature, error}: the head of remote ``main``, one lore call (~1 s)."""
    return _head(project_root, ["--remote", "history", "1", "--branch", REMOTE_BRANCH], timeout)


def local_head(project_root: str, *, timeout: float = 30.0) -> dict:
    """{ok, revision, signature, error}: the island's current revision (``lore status``)."""
    return _head(project_root, ["status"], timeout)


def repo_state(project_root: str, *, timeout: float = 60.0) -> dict:
    """{ok, available, repository, branch, local_revision:int|None, remote_revision:int|None,
    behind:bool, ahead:bool, in_sync:bool, staged:[rel paths], untracked:[rel paths], error:str}
    (+ local_branch, remote_branch="main", local_signature, remote_signature, merge_base, and
    ``incoming``: the remote revisions the local head lacks, see :func:`incoming`).
    ``branch`` = ``local_branch``; remote and behind/ahead/in_sync are vs remote ``main``.
    ok=False with error when lore.exe is missing, the folder has no .lore, or lore
    fails/times out. ``timeout`` applies to each of the 3 lore calls."""
    available = bool(detect_lore_executable().get("available"))
    if not available:
        return _failed("lore.exe not found — install Fortnite/UEFN or set LORE_CLI_LOCATION", available=False)
    st, err = _state(project_root, timeout)
    if st is None:
        return _failed(err, available=True)
    return {
        "ok": True,
        "available": True,
        **st,
        "branch": st["local_branch"],
        "staged": [rel for _, rel in st["staged"]],
        "untracked": [rel for _, rel in st["untracked"]],
        "error": "",
    }


def pending_paths(project_root: str, *, timeout: float = 60.0) -> dict:
    """{ok, paths:[absolute file paths, forward slashes], error} — every file not yet on remote
    ``main``: working-tree changes (staged + untracked) plus files changed between the merge base
    of (local head, remote main head) and the local head (autosave commits, pushed to a personal
    branch or not). Only files that exist on disk are listed: deletes are dropped, untracked
    directories expand to their files. Content/Developers/** is excluded.
    ``timeout`` applies to each lore call (up to 4)."""
    st, err = _state(project_root, timeout)
    if st is None:
        return _failed(err, paths=[])
    committed: list[tuple[str, str]] = []
    if st["ahead"]:
        args = ["revision", "diff", st["merge_base"], "--target", st["local_signature"]]
        ok, out = _run_lore(project_root, args, timeout)
        if not ok:
            return _failed(out, paths=[])
        committed = parse_revision_diff(out)
    try:
        paths = to_pending_files(project_root, [*st["staged"], *st["untracked"], *committed])
    except (OSError, ValueError) as exc:
        return _failed(f"listing pending files failed: {exc}", paths=[])
    return {"ok": True, "paths": paths, "error": ""}


def whoami(project_root: str, *, timeout: float = 30.0) -> dict[str, str]:
    """{id, name}: the Epic account lore is signed in with on this PC (``lore auth info``, local,
    ~0.3 s), cached :data:`_ME_TTL_S`. Empty strings when lore can't say. Never raises."""
    now = time.monotonic()
    with _me_lock:
        hit = _me_cache.get(project_root)
        if hit and now - hit[0] < _ME_TTL_S:
            return dict(hit[1])
    ok, out = _run_lore(project_root, ["auth", "info"], timeout)
    me = parse_auth_info(out) if ok else {"id": "", "name": ""}
    if me["name"]:
        with _me_lock:
            _me_cache[project_root] = (now, me)
    return dict(me)


def _same_owner(owner_raw: str, me_raw: str) -> bool:
    if not me_raw:
        return False
    return owner_raw.strip() == me_raw.strip() or display_name(owner_raw) == display_name(me_raw)


def locks(project_root: str, *, timeout: float = 60.0) -> dict:
    """{ok, locks:[{path, rel, owner, owner_raw, mine}], me, error}: the files locked on remote
    ``main`` (UEFN locks a file as soon as an actor is modified, until check-in or revert), one
    ``lore lock query --branch main`` (~1.1 s) plus a cached ``lore auth info``.

    ``path`` is absolute with forward slashes, ``owner`` the display name without padding.
    ``mine``: the lock owner is the account lore is signed in with here (:func:`whoami`,
    compared by display name: lore prints no owner id). When that account is unknown, ok=False
    (locks still listed, all ``mine=False``) so nobody mistakes this PC's own locks for another's.
    Never raises."""
    try:
        if not (Path(project_root) / ".lore").is_dir():
            return _failed("not a Lore repository (no .lore folder)", locks=[], me="")
        ok, out = _run_lore(project_root, ["lock", "query", "--branch", REMOTE_BRANCH], timeout)
        if not ok:
            return _failed(out, locks=[], me="")
        me_raw = whoami(project_root, timeout=min(timeout, 30.0))["name"]
        root = Path(project_root)
        rows = [
            {
                "path": (root / lk["rel"]).as_posix(),
                "rel": lk["rel"],
                "owner": display_name(lk["owner_raw"]),
                "owner_raw": lk["owner_raw"],
                "mine": _same_owner(lk["owner_raw"], me_raw),
            }
            for lk in parse_locks(out)
        ]
        me = display_name(me_raw)
        if not me:
            return _failed("lore auth info names no signed-in account", locks=rows, me="")
        return {"ok": True, "locks": rows, "me": me, "error": ""}
    except Exception as exc:  # noqa: BLE001 — never raises
        return _failed(f"lock query failed: {exc}", locks=[], me="")
