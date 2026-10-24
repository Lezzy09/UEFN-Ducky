"""git_lock_cleanup — a killed git's locks go, a live git's locks stay."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.coding_agents import git_lock_cleanup as glc


class _NoSuchProcess(Exception):
    pass


class _AccessDenied(Exception):
    pass


class _Proc:
    def __init__(self, name: str, cwd: str | Exception):
        self.info = {"name": name}
        self._name, self._cwd = name, cwd

    def name(self) -> str:
        return self._name

    def cwd(self) -> str:
        if isinstance(self._cwd, Exception):
            raise self._cwd
        return self._cwd


def _fake_psutil(by_pid: dict[int, _Proc], alive: list[_Proc]):
    def process(pid: int) -> _Proc:
        if pid not in by_pid:
            raise _NoSuchProcess(pid)
        return by_pid[pid]

    return SimpleNamespace(Process=process, process_iter=lambda attrs=None: list(alive),
                           NoSuchProcess=_NoSuchProcess, AccessDenied=_AccessDenied)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git" / "refs" / "heads" / "feature").mkdir(parents=True)
    (repo / "src").mkdir()
    for lock in ("index.lock", "HEAD.lock", "refs/heads/main.lock", "refs/heads/feature/x.lock"):
        (repo / ".git" / lock).write_text("", encoding="utf-8")
    return repo


def test_killed_git_leaves_no_locks(tmp_path):
    repo = _repo(tmp_path)
    killed = _fake_psutil({41: _Proc("git.exe", str(repo / "src")), 42: _Proc("node.exe", str(repo))}, alive=[])
    repos = glc.repos_of([41, 42, 99], psutil_mod=killed)
    assert repos == {repo.resolve()}
    removed = glc.clean(repos, psutil_mod=killed)
    assert len(removed) == 4
    assert glc.lock_files(repo) == []


def test_live_git_in_the_repo_keeps_the_lock(tmp_path):
    repo = _repo(tmp_path)
    other = _fake_psutil({}, alive=[_Proc("git.exe", str(tmp_path)), _Proc("git.exe", str(repo / "src"))])
    assert glc.clean({repo}, psutil_mod=other) == []
    assert (repo / ".git" / "index.lock").is_file()


def test_unreadable_git_counts_as_inside(tmp_path):
    repo = _repo(tmp_path)
    denied = _fake_psutil({}, alive=[_Proc("git.exe", _AccessDenied())])
    assert glc.clean({repo}, psutil_mod=denied) == []
    assert (repo / ".git" / "index.lock").is_file()


def test_gone_git_does_not_block(tmp_path):
    repo = _repo(tmp_path)
    gone = _fake_psutil({}, alive=[_Proc("git.exe", _NoSuchProcess()), _Proc("python.exe", _AccessDenied())])
    assert len(glc.clean({repo}, psutil_mod=gone)) == 4


def test_worktree_locks_live_in_its_gitdir(tmp_path):
    main = _repo(tmp_path)
    wt_gitdir = main / ".git" / "worktrees" / "wt"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "commondir").write_text("../..", encoding="utf-8")
    (wt_gitdir / "index.lock").write_text("", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")
    assert glc.repo_top(wt) == wt.resolve()
    locks = {p.name for p in glc.lock_files(wt)}
    assert {"index.lock", "HEAD.lock", "main.lock", "x.lock"} <= locks
