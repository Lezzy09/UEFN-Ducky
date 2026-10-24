"""Remove git lock files a forced kill left behind.

A ``git commit`` killed mid-write leaves ``.git/index.lock`` (or ``HEAD.lock`` / a branch
ref lock) and every later commit in that repo fails with "Another git process seems to
be running". Before ``proc_exec`` kills an agent's tree it notes the repos its ``git``
processes work in (``repos_of``); after the kill ``clean`` removes those repos' locks,
but only when no live git process anywhere could still be using that repo. A process
whose folder can't be read counts as "maybe inside": the lock stays.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _is_git(name: str) -> bool:
    return os.path.splitext(str(name or "").lower())[0] == "git"


def repo_top(start: str | os.PathLike) -> Path | None:
    """Folder holding ``.git`` at or above ``start`` (no git call: the process may be dying)."""
    try:
        cur = Path(start).resolve()
    except OSError:
        return None
    for folder in (cur, *cur.parents):
        if (folder / ".git").exists():
            return folder
    return None


def _git_dirs(repo: Path) -> list[Path]:
    """The repo's git dir, plus the common dir for a worktree (``.git`` is a file there)."""
    dot = repo / ".git"
    if dot.is_dir():
        return [dot]
    try:
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []
    if not line.startswith("gitdir:"):
        return []
    gitdir = Path(line[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (repo / gitdir).resolve()
    dirs = [gitdir]
    try:
        common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        dirs.append((gitdir / common).resolve())
    except OSError:
        pass
    return dirs


def lock_files(repo: Path) -> list[Path]:
    found: list[Path] = []
    for gd in _git_dirs(repo):
        for name in ("index.lock", "HEAD.lock"):
            if (gd / name).is_file():
                found.append(gd / name)
        heads = gd / "refs" / "heads"
        if heads.is_dir():
            found.extend(p for p in heads.rglob("*.lock") if p.is_file())
    return found


def repos_of(pids, psutil_mod=None) -> set[Path]:
    """Repos the ``git`` processes among ``pids`` work in. Call before the kill."""
    psutil = psutil_mod or _psutil()
    repos: set[Path] = set()
    if psutil is None:
        return repos
    for pid in pids:
        try:
            proc = psutil.Process(int(pid))
            if not _is_git(proc.name()):
                continue
            top = repo_top(proc.cwd())
        except Exception:  # gone, or no access: nothing to record
            continue
        if top is not None:
            repos.add(top)
    return repos


def _inside(path: Path, repo: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except (ValueError, OSError):
        return False


def _repo_busy(repo: Path, psutil) -> bool:
    """True when a live git process is (or may be) working inside ``repo``."""
    for proc in psutil.process_iter(["name"]):
        try:
            if not _is_git(proc.info.get("name") or ""):
                continue
            cwd = proc.cwd()
        except psutil.NoSuchProcess:
            continue
        except Exception:  # AccessDenied and friends: maybe inside, keep the lock (D15)
            return True
        if _inside(Path(cwd), repo):
            return True
    return False


def clean(repos, psutil_mod=None, wait_s: float = 0.0) -> list[dict]:
    """Remove the locks of ``repos`` no live git process uses. Returns what was removed.

    ``wait_s``: how long a just-killed git may take to vanish before its repo counts as busy.
    """
    psutil = psutil_mod or _psutil()
    removed: list[dict] = []
    if psutil is None:
        return removed
    for repo in repos:
        locks = lock_files(Path(repo))
        if not locks:
            continue
        deadline = time.monotonic() + wait_s
        busy = _repo_busy(Path(repo), psutil)
        while busy and time.monotonic() < deadline:
            time.sleep(0.1)
            busy = _repo_busy(Path(repo), psutil)
        if busy:
            continue
        now = time.time()
        for lock in locks:
            try:
                age = max(0.0, now - lock.stat().st_mtime)
                lock.unlink()
            except OSError:
                continue
            removed.append({"repo": str(repo), "lock": str(lock), "age_s": round(age, 1)})
    for item in removed:
        _record(item)
    return removed


def clean_in_background(repos) -> None:
    """``clean`` off the caller's thread (the cancel path must not wait on dying processes)."""
    if not repos:
        return
    import threading

    threading.Thread(target=clean, args=(set(repos),), kwargs={"wait_s": 3.0},
                     daemon=True, name="git-lock-cleanup").start()


def _psutil():
    try:
        import psutil

        return psutil
    except ImportError:
        return None


def _record(item: dict) -> None:
    try:
        from backend.store.repos import events
        from backend.util.privacy import scrub

        repo = scrub(item["repo"])
        events.insert("git_lock_removed", ts=time.time(), source="proc_exec",
                      message=f"removed {Path(item['lock']).name} in {repo} ({item['age_s']:.0f} s old)",
                      payload={"repo": repo, "lock": scrub(item["lock"]), "age_s": item["age_s"]})
    except Exception:  # noqa: BLE001 — a report never breaks the kill path
        pass
