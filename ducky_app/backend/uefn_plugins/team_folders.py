"""Plugins that keep their own folders: a ``team_folders`` entry in plugin.json shares a
folder with a team, with no plugin code.

A declaration::

    {"id": "scenes", "root": "{LOCALAPPDATA}/UEFN-Ducky/forge/scenes", "unit": "*",
     "lock": "unit", "last": ["scene.json"], "ignore": ["**/*.tmp"], "after_pull": "reload"}

- ``root``: ``{LOCALAPPDATA}/UEFN-Ducky/...`` or ``{PROJECT}/...`` (the open island).
- ``unit`` (what locks and presence are about): ``*`` each top-level folder, and each
  loose file; ``.`` the whole folder (of that project, for a ``{PROJECT}`` root);
  ``file`` every file.
- ``lock``: ``unit`` (the first change takes the unit's lock) or ``none``.
- ``last``: globs relative to the unit, applied after the unit's other files.
- ``ignore``: globs relative to the root, never shared.
- ``after_pull``: ``notify`` or ``reload``.
- ``on_locked``: ``readonly`` (default: files of a unit someone else holds are read-only)
  or ``quarantine`` (writes are allowed, never sent, and the bar offers Keep mine as a
  copy or Discard mine).
- ``merge``: globs relative to the unit; such files that are valid JSON merge three ways
  (a per-file merge base) instead of making the whole unit a conflict. Never over 32 MiB.

Each folder has a copy per scope: Local, ``scopes/_pc/<plugin>/folders/<id>/`` (this PC,
every account), and one per team, ``scopes/<account>/<space>/<plugin>/folders/<id>/``; a
``{PROJECT}`` root keeps one subfolder per project id in each. The plugin's own folder
becomes an NTFS junction to the copy in use (it works across the app and the MCP bridge
processes). Folder files are plaintext on the PC (:data:`PLAINTEXT_NOTE`).

- Adopt once, on the first team link: the folder moves into the Local copy (a rename on
  the same volume, else a verified copy first, then a rename aside) and a junction
  replaces it, while the plugin's calls are held back as for a re-point. A move cut short
  is put right by the next bind. A junction is only ever removed with ``os.rmdir`` on the
  junction; nothing here deletes through one.
- Refused, with the reason: roots on a network or non-NTFS volume, inside OneDrive, and
  ``{PROJECT}`` roots inside a UEFN revision control workspace (``.lore`` / ``.urc`` at
  the project root) unless that workspace's ignore file leaves them out.
- A switch to a team pulls the team's copy first, with the junction still on the current
  copy; an empty team copy is bound only after the first share (:func:`switch`).
- A re-point waits for the plugin's running calls in every process (call markers), and
  calls that start meanwhile wait for it, then bumps its reload epoch so a process that
  loaded it reloads it before its next call.
- Capture (:func:`scan`): a stat scan against ``folder_files`` (ignored globs pruned,
  sha256 only for changed files); a unit is ready after 3 s quiet with no ``*.tmp``. A
  file renamed in place (case or Unicode form only) stays the same item.
- Core reads plugin files sharing delete access (:func:`open_read`): while it hashes or
  copies one, the plugin may still move or delete it. Files go out from a copy core makes
  first (:func:`snapshot`), so an upload never holds a plugin's file open.
- Apply (:func:`apply_unit`): other files, then ``last``, then deletes; each file temp →
  ``os.replace`` → ``os.utime`` with the origin's ``mtime_ns``. A unit changed here is
  never overwritten. Read-only attributes keep others' units and stale bases unedited.
- File operations under the copies use ``\\\\?\\`` paths, so long paths work.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from backend.store.repos import folder_files as repo
from backend.uefn_plugins.ledger import person

_log = logging.getLogger(__name__)

TOKENS = ("{LOCALAPPDATA}", "{PROJECT}")
UNITS = ("*", ".", "file")
LOCKS = ("unit", "none")
AFTER_PULL = ("notify", "reload")
ON_LOCKED = ("readonly", "quarantine")
FIELDS = ("id", "root", "unit", "lock", "last", "ignore", "after_pull", "on_locked", "merge")
MAX_FOLDERS = 8
MAX_GLOBS = 64
MAX_ROOT = 200
QUIET_S = 3.0
CALL_WAIT_S = 30.0
AGENT_WINDOW_S = 10.0  # a folder change this soon after one of the plugin's calls is the caller's
MERGE_MAX_BYTES = 32 * 1024 * 1024
FILE_MAX_BYTES = 4 * 1024 ** 3  # the most one file of a team folder can be (the Store refuses bigger ones)
TOO_BIG = "Over 4 GB, the most one file in a team folder can be: "  # then the file's name
CLASH = " differ only by upper/lower case or accents."  # after the names
APP_DIR = "UEFN-Ducky"
LOCAL_ACCOUNT = repo.LOCAL_ACCOUNT
PERSONAL = "personal"
# The app's own folders under %LOCALAPPDATA%/UEFN-Ducky: never a plugin's to declare.
CORE_DIRS = frozenset({
    "scopes", "uefn_plugins", "skill_packs", "ai_plugins", "mcp_plugins", "snapshots", "legacy", "listener",
    "backups", "exports", "imports", "plugin_local", "coding_agents", "webview2_browser", "chats", "workspace",
    "ducky.db", "ducky.db-wal", "ducky.db-shm", "uefn_plugin_cache", "uefn_plugin_prefs",
})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_BAD_SEGMENT = re.compile(r'[<>:"\\|?*\x00-\x1f]')
HELD_STATES = ("refused", "conflict", "quarantined", "locked_out", "blocked", "refetch")
PLAINTEXT_NOTE = ("This plugin's files are stored as it writes them on each member's PC; on the server and in "
                  "transit they are encrypted.")
REFUSE_URC = "Carried by this island's UEFN revision control"
REFUSE_NETWORK = "This folder is on a network drive. Team folders work only on this PC's own drives."
REFUSE_VOLUME = "This folder is on a {fs} drive. Team folders need an NTFS drive."
REFUSE_ONEDRIVE = "This folder is synced by OneDrive. Move it out of OneDrive to share it with a team."
REFUSE_SAME_ISLAND = ("Another project on this PC ({name}) is the same island, so their folders can't be told "
                      "apart. Share this folder from one of them.")
TEST_RUNNING = "A test of {plugin} is running. Try again when it finishes."
PULLING = "Getting {team}'s files… {pct}%"  # the bar while a switch pulls the team's copy first
MOVE_WAIT_S = 600.0  # a call waits at most this long for a move of its plugin's folders
# Core's own files in a copy: downloads waiting to land and backups during an apply (never
# a plugin's save in progress), and folders of a move into the Local copy.
IN_TAG = ".ducky-in-"
BAK_TAG = ".ducky-bak-"
STAGING = ".ducky-moving-"
ADOPTING = ".ducky-adopting-"
_LONG = "\\\\?\\"
_LONG_UNC = "\\\\?\\UNC\\"


class FolderError(OSError):
    """A folder operation that can't go ahead; the message says why, in plain words."""


class Busy(FolderError):
    """The plugin still has a call running after the wait."""


# --------------------------------------------------------------------------- declarations


@dataclass(frozen=True)
class Folder:
    id: str
    root: str
    unit: str = "*"
    lock: str = "unit"
    last: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    after_pull: str = "notify"
    on_locked: str = "readonly"
    merge: tuple[str, ...] = ()

    @property
    def project(self) -> bool:
        return self.root.startswith("{PROJECT}/")


def _root_errors(root: Any, where: str) -> list[str]:
    usage = f'{where} "root" must start with {{LOCALAPPDATA}}/UEFN-Ducky/ or {{PROJECT}}/, e.g. ' \
            '"{LOCALAPPDATA}/UEFN-Ducky/<plugin>/data".'
    if not isinstance(root, str) or not root:
        return [usage]
    token, sep, rest = root.partition("/")
    if token not in TOKENS or not sep or not rest:
        return [usage]
    if len(root) > MAX_ROOT:
        return [f'{where} "root" is over {MAX_ROOT} characters: use a shorter path.']
    segments = rest.split("/")
    for seg in segments:
        if not seg or seg in (".", "..") or _BAD_SEGMENT.search(seg) or seg != seg.rstrip(" ."):
            return [f'{where} "root" {root!r} has a bad part {seg!r}: use plain folder names separated by /, '
                    'without .. or \\.']
    if token == "{LOCALAPPDATA}":
        if segments[0].casefold() != APP_DIR.casefold() or len(segments) < 2:
            return [f'{where} "root" {root!r} must be inside {{LOCALAPPDATA}}/UEFN-Ducky/, e.g. '
                    '"{LOCALAPPDATA}/UEFN-Ducky/<plugin>/data".']
        if segments[1].casefold() in CORE_DIRS:
            return [f'{where} "root" {root!r} is one of the app\'s own folders: use a folder of the plugin\'s own, '
                    'e.g. "{LOCALAPPDATA}/UEFN-Ducky/<plugin>/data".']
    return []


def _glob_errors(name: str, value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(g, str) for g in value):
        return [f'{where} "{name}" must be a list of globs, e.g. ["*/history.json", "**/*.tmp"].']
    if len(value) > MAX_GLOBS:
        return [f'{where} "{name}" has {len(value)} globs: {MAX_GLOBS} at most.']
    for glob in value:
        if not glob or glob.startswith("/") or "\\" in glob or ".." in glob.split("/") or len(glob) > 200:
            return [f'{where} "{name}" glob {glob!r} isn\'t a relative glob: use / between parts, no .. and no '
                    'leading /, e.g. "*/history.json" or "**/*.tmp".']
    return []


def _choice_error(entry: dict[str, Any], name: str, allowed: tuple[str, ...], where: str) -> list[str]:
    if name not in entry or entry[name] in allowed:
        return []
    return [f'{where} "{name}" is {entry[name]!r}: use {" or ".join(repr(a).replace(chr(39), chr(34)) for a in allowed)}.']


def _entry(entry: Any, index: int) -> tuple[list[str], Folder | None]:
    if not isinstance(entry, dict):
        return [f'plugin.json "team_folders" entry {index + 1} must be an object with "id", "root" and "unit".'], None
    fid = entry.get("id")
    where = f'plugin.json "team_folders" {fid!r}' if isinstance(fid, str) and fid else \
        f'plugin.json "team_folders" entry {index + 1}'
    errors: list[str] = []
    unknown = sorted(str(k) for k in entry if k not in FIELDS)
    if unknown:
        errors.append(f'{where} has unknown {", ".join(repr(k) for k in unknown)}: use {", ".join(FIELDS)}.')
    if not isinstance(fid, str) or not _ID_RE.match(fid):
        errors.append(f'{where} "id" must be 1-32 of a-z, 0-9, _ and -, starting with a letter or digit.')
    errors += _root_errors(entry.get("root"), where)
    if entry.get("unit") not in UNITS:
        errors.append(f'{where} "unit" is {entry.get("unit")!r}: use "*" (each top-level folder or file), "." '
                      '(the whole folder) or "file" (every file).')
    errors += _choice_error(entry, "lock", LOCKS, where)
    errors += _choice_error(entry, "after_pull", AFTER_PULL, where)
    errors += _choice_error(entry, "on_locked", ON_LOCKED, where)
    for name in ("last", "ignore", "merge"):
        errors += _glob_errors(name, entry.get(name), where)
    if errors:
        return errors, None
    return [], Folder(
        id=fid, root=entry["root"], unit=entry["unit"], lock=entry.get("lock", "unit"),
        last=tuple(entry.get("last") or ()), ignore=tuple(entry.get("ignore") or ()),
        after_pull=entry.get("after_pull", "notify"), on_locked=entry.get("on_locked", "readonly"),
        merge=tuple(entry.get("merge") or ()),
    )


def _overlap(a: str, b: str) -> bool:
    x, y = a.casefold().rstrip("/") + "/", b.casefold().rstrip("/") + "/"
    return x.startswith(y) or y.startswith(x)


def _check(manifest: dict[str, Any]) -> tuple[list[str], list[Folder]]:
    if "team_folders" not in manifest:
        return [], []
    raw = manifest.get("team_folders")
    if not isinstance(raw, list):
        return ['plugin.json "team_folders" must be a list of folders: [{"id": "scenes", "root": '
                '"{LOCALAPPDATA}/UEFN-Ducky/<plugin>/scenes", "unit": "*"}].'], []
    errors: list[str] = []
    if len(raw) > MAX_FOLDERS:
        errors.append(f'plugin.json "team_folders" has {len(raw)} folders: {MAX_FOLDERS} at most.')
    good: list[Folder] = []
    for i, entry in enumerate(raw[:MAX_FOLDERS]):
        errs, folder = _entry(entry, i)
        errors += errs
        if folder is None:
            continue
        if any(f.id == folder.id for f in good):
            errors.append(f'plugin.json "team_folders" has two folders with "id" {folder.id!r}: give each its own.')
            continue
        clash = next((f for f in good if _overlap(f.root, folder.root)), None)
        if clash is not None:
            errors.append(f'plugin.json "team_folders" {folder.id!r} and {clash.id!r} overlap: one root is inside '
                          'the other. Declare each folder once.')
            continue
        good.append(folder)
    if raw and manifest.get("data_sharing") is False:
        errors.append('plugin.json has "team_folders" but "data_sharing": false: nothing is shared, so remove one.')
        good = []
    return errors, good


def declaration_errors(manifest: dict[str, Any]) -> list[str]:
    """What is wrong with a manifest's ``team_folders``, each with the fix."""
    return _check(manifest)[0]


def declarations(manifest: dict[str, Any]) -> list[Folder]:
    """The valid folders of a manifest (none while ``data_sharing`` is false)."""
    return _check(manifest)[1]


_DECLS: dict[str, tuple[float, tuple[Folder, ...]]] = {}  # manifest path → (mtime, folders)


def plugin_folders(plugin: str) -> list[Folder]:
    """The installed plugin's declared folders (read per call, cached by the manifest's mtime)."""
    from backend.uefn_plugins.store import PLUGIN_MANIFEST, load_plugin_manifest, plugin_dir

    try:
        path = plugin_dir(plugin) / PLUGIN_MANIFEST
        mtime = path.stat().st_mtime
    except (OSError, ValueError):
        return []
    hit = _DECLS.get(str(path))
    if hit is None or hit[0] != mtime:
        hit = (mtime, tuple(declarations(load_plugin_manifest(plugin) or {})))
        _DECLS[str(path)] = hit
    return list(hit[1])


def folder_of(plugin: str, folder_id: str) -> Folder | None:
    return next((f for f in plugin_folders(plugin) if f.id == folder_id), None)


# --------------------------------------------------------------------------- names + globs


def norm_name(name: str) -> str:
    """How names compare and hash: NFC, then casefolded (NTFS and other PCs see ``Scene``,
    ``scene`` and a decomposed ``é`` as one name)."""
    return unicodedata.normalize("NFC", str(name)).casefold()


@functools.lru_cache(maxsize=1024)
def _glob_body(pattern: str) -> str:
    p, i, out = norm_name(pattern), 0, []
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        elif p[i] == "[" and p.find("]", i + 2) > i:
            j = p.find("]", i + 2)
            body = p[i + 1:j]
            body = "^" + body[1:] if body.startswith("!") else body
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=1024)
def _glob_re(pattern: str) -> re.Pattern[str]:
    return re.compile(_glob_body(pattern))


def matches(patterns: Iterable[str], rel: str) -> bool:
    """Whether ``rel`` ('/'-separated) matches any glob: anchored at the start, ``*`` and
    ``?`` within one part, ``**`` across parts. Case and Unicode form never matter."""
    name = norm_name(rel)
    return any(_glob_re(p).fullmatch(name) for p in patterns)


def _dir_ignored(patterns: Iterable[str], rel: str) -> bool:
    patterns = tuple(patterns)
    return matches(patterns, rel) or matches(patterns, rel + "/")


def _gitignore(text: str) -> list[tuple[bool, bool, re.Pattern[str]]]:
    """``.gitignore``-style lines → (negated, folders only, pattern) rules."""
    rules: list[tuple[bool, bool, re.Pattern[str]]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        neg = s.startswith("!")
        s = s[1:] if neg else s
        s = s[1:] if s.startswith("\\") else s
        dir_only = s.endswith("/")
        core = s.rstrip("/")
        anchored = "/" in core
        core = core.lstrip("/")
        if not core:
            continue
        body = _glob_body(core)
        rules.append((neg, dir_only, re.compile(body if anchored else f"(?:.*/)?{body}")))
    return rules


def _git_ignored(rules: list[tuple[bool, bool, re.Pattern[str]]], rel: str, *, is_dir: bool = True) -> bool:
    """Whether ``rel`` is left out by the rules: the last matching rule wins, and a folder
    left out leaves out everything in it."""
    parts = [p for p in norm_name(rel).split("/") if p]
    for i in range(1, len(parts) + 1):
        sub, sub_dir = "/".join(parts[:i]), i < len(parts) or is_dir
        verdict = False
        for neg, dir_only, rx in rules:
            if (not dir_only or sub_dir) and rx.fullmatch(sub):
                verdict = not neg
        if verdict:
            return True
    return False


# --------------------------------------------------------------------------- paths


def _lp(path: Any) -> str:
    """``path`` as a ``\\\\?\\`` path on Windows, so long paths work."""
    s = os.fspath(path)
    if os.name != "nt" or s.startswith(_LONG):
        return s
    s = os.path.abspath(s)
    if s.startswith("\\\\"):
        return _LONG_UNC + s[2:]
    return _LONG + s


def _plain(path: Any) -> str:
    s = os.fspath(path)
    if s.startswith(_LONG_UNC):
        return "\\\\" + s[len(_LONG_UNC):]
    if s.startswith(_LONG):
        return s[len(_LONG):]
    return s


def _key(path: Any) -> str:
    """For comparing two paths."""
    return os.path.normcase(os.path.normpath(_plain(path)))


def _inside(path: Any, root: Any) -> bool:
    p, r = _key(path), _key(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def _exists(path: Any) -> bool:
    return os.path.lexists(_lp(path))


def _is_junction(path: Any) -> bool:
    try:
        return os.path.isjunction(_lp(path))
    except OSError:
        return False


def _is_link(path: Any) -> bool:
    return _is_junction(path) or os.path.islink(_lp(path))


def junction_target(path: Any) -> str | None:
    """Where the junction at ``path`` points (None: not a junction)."""
    if not _is_junction(path):
        return None
    try:
        return _plain(os.readlink(_lp(path)))
    except OSError:
        return None


def _existing(path: Any) -> str:
    p = os.path.abspath(_plain(path))
    while not os.path.lexists(_lp(p)):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _mkdirs(path: Any) -> None:
    """``os.makedirs`` for ``\\\\?\\`` paths (which ``os.makedirs`` can't walk)."""
    p = os.path.abspath(_plain(path))
    missing: list[str] = []
    while not os.path.isdir(_lp(p)):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for d in reversed(missing):
        try:
            os.mkdir(_lp(d))
        except FileExistsError:
            pass


def _entries(path: Any) -> list[os.DirEntry[str]]:
    """The entries of a folder ([] when it isn't one)."""
    try:
        with os.scandir(_lp(path)) as it:
            return list(it)
    except OSError:
        return []


def _empty_dir(path: Any) -> bool:
    try:
        with os.scandir(_lp(path)) as it:
            return next(it, None) is None
    except OSError:
        return False


def _readonly(path: Any) -> bool:
    try:
        return bool(os.stat(_lp(path), follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
    except (OSError, AttributeError):
        return False


def set_readonly(path: Any, on: bool) -> None:
    """``FILE_ATTRIBUTE_READONLY`` on or off (a save that writes a temp file and replaces
    this one fails up front while it is on)."""
    os.chmod(_lp(path), stat.S_IREAD if on else stat.S_IREAD | stat.S_IWRITE)


def _unlink(path: Any) -> None:
    try:
        os.unlink(_lp(path))
    except PermissionError:
        set_readonly(path, False)
        os.unlink(_lp(path))


def remove_tree(path: Any) -> bool:
    """Delete a folder: read-only files too, and a junction or link inside is removed
    itself (``os.rmdir`` on it), never followed. Returns whether everything went."""
    p = _lp(path)
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if _is_junction(p):
        try:
            os.rmdir(p)
            return True
        except OSError:
            return False
    if os.path.islink(p) or not stat.S_ISDIR(st.st_mode):
        try:
            _unlink(p)
            return True
        except OSError:
            return False
    ok = True
    try:
        with os.scandir(p) as it:
            entries = list(it)
    except OSError:
        return False
    for e in entries:
        try:
            if e.is_junction():
                os.rmdir(e.path)
            elif e.is_symlink():
                os.unlink(e.path)
            elif e.is_dir(follow_symlinks=False):
                ok = remove_tree(e.path) and ok
            else:
                _unlink(e.path)
        except OSError:
            ok = False
    try:
        os.rmdir(p)
    except OSError:
        ok = False
    return ok


@functools.lru_cache(maxsize=1)
def _create_file() -> Any:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k32.CreateFileW
    fn.restype = wintypes.HANDLE
    fn.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                   wintypes.HANDLE)
    return fn


def open_read(path: Any) -> Any:
    """A file opened for reading so the plugin may still rename or delete it meanwhile
    (``FILE_SHARE_DELETE``; Python's ``open`` leaves it out, and then a save that moves or
    deletes the old file fails while core reads). Windows still refuses a replace onto a
    file anyone has open, so core's reads stay short."""
    p = _lp(path)
    if os.name != "nt":
        return open(p, "rb")  # noqa: SIM115 — the caller closes it
    import ctypes
    import msvcrt

    handle = _create_file()(p, 0x80000000, 0x7, None, 3, 0x08000080, None)  # GENERIC_READ, share all, OPEN_EXISTING
    if handle is None or handle == ctypes.c_void_p(-1).value:
        err = ctypes.get_last_error()
        raise OSError(None, ctypes.FormatError(err).strip(), _plain(p), err)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    return os.fdopen(fd, "rb")


def read_bytes(path: Any) -> bytes:
    with open_read(path) as f:
        return f.read()


def _sha_file(path: Any) -> str:
    h = hashlib.sha256()
    with open_read(path) as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_hashed(src: Any, dst: Any) -> str:
    """Copy one file's content (read as :func:`open_read` does) and return its sha256."""
    h = hashlib.sha256()
    with open_read(src) as fin, open(_lp(dst), "wb") as fout:
        for chunk in iter(lambda: fin.read(1024 * 1024), b""):
            h.update(chunk)
            fout.write(chunk)
    return h.hexdigest()


def _walk_files(base: Any) -> Iterator[tuple[str, os.DirEntry[str]]]:
    """(relpath, entry) of every file under ``base``; a link inside is a FolderError."""
    stack = [("", _lp(base))]
    while stack:
        rel, d = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                r = f"{rel}/{e.name}" if rel else e.name
                if e.is_junction() or e.is_symlink():
                    raise FolderError(f"{_plain(e.path)} is a link to another folder. Move it out first.")
                if e.is_dir(follow_symlinks=False):
                    stack.append((r, e.path))
                else:
                    yield r, e


def _copy_verified(src: Any, dst: Any) -> None:
    """Copy one file with its mtime (to the 100 ns), then check size and sha256."""
    _mkdirs(os.path.dirname(_plain(dst)))
    copy_hashed(src, dst)
    shutil.copystat(_lp(src), _lp(dst))
    a, b = os.stat(_lp(src)), os.stat(_lp(dst))
    if a.st_size != b.st_size or _sha_file(src) != _sha_file(dst):
        raise FolderError(f"Copying {_plain(src)} didn't give the same file. Nothing was moved.")


def _same_content(a: Any, b: Any) -> bool:
    try:
        return os.stat(_lp(a)).st_size == os.stat(_lp(b)).st_size and _sha_file(a) == _sha_file(b)
    except OSError:
        return False


def _free_name(path: str, label: str) -> str:
    """``<stem> (<label>).<ext>`` beside ``path``, numbered while that is taken."""
    folder, name = os.path.split(path)
    stem, dot, ext = name.rpartition(".")
    if not (dot and stem):
        stem, ext = name, ""
    n = 1
    while True:
        tag = label if n == 1 else f"{label} {n}"
        candidate = os.path.join(folder, f"{stem} ({tag})" + (f".{ext}" if ext else ""))
        if not os.path.lexists(candidate):
            return candidate
        n += 1


def _same_volume(a: Any, b: Any) -> bool:
    try:
        return os.stat(_lp(_existing(a))).st_dev == os.stat(_lp(_existing(b))).st_dev
    except OSError:
        return False


def _in_use(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", 0) in (5, 32, 33)


def _move_dir(src: Path, dst: Path) -> str:
    """Move a folder to a path that doesn't exist yet: a rename on the same volume, else
    copy, verify and delete. Returns ``rename`` or ``copy``."""
    _mkdirs(dst.parent)
    if _same_volume(src, dst.parent):
        try:
            os.rename(_lp(src), _lp(dst))
            return "rename"
        except OSError as exc:
            if getattr(exc, "winerror", 0) != 17:  # ERROR_NOT_SAME_DEVICE: copy below
                if _in_use(exc):
                    raise FolderError(f"A file in {_plain(src)} is in use. Close it and try again.") from exc
                raise
    # Renamed aside first: a folder with a file open can't be renamed, so nothing is half copied.
    staging = src.with_name(f"{src.name}.ducky-moving-{uuid.uuid4().hex[:8]}")
    try:
        os.rename(_lp(src), _lp(staging))
    except OSError as exc:
        raise FolderError(f"A file in {_plain(src)} is in use. Close it and try again.") from exc
    try:
        _mkdirs(dst)
        for rel, entry in _walk_files(staging):
            _copy_verified(entry.path, os.path.join(_lp(dst), *rel.split("/")))
    except BaseException:
        remove_tree(dst)
        os.rename(_lp(staging), _lp(src))
        raise
    if not remove_tree(staging):
        _log.warning("team folders: %s was copied but its old copy couldn't all be deleted", _plain(staging))
    return "copy"


def _absorb(src: Path, dst: Path, *, keep_both: bool = False) -> int:
    """Every file of the folder ``src`` goes into ``dst`` (replacing a file of the same
    name), then ``src`` goes. ``keep_both``: a file ``dst`` already has with other content
    stays, and the one from ``src`` is kept beside it as ``<name> (conflict)``. Returns how
    many files moved."""
    _mkdirs(dst)
    moved = 0
    same = _same_volume(src, dst)
    for rel, entry in list(_walk_files(src)):
        target = os.path.join(_lp(dst), *rel.split("/"))
        _mkdirs(os.path.dirname(target))
        if keep_both and os.path.lexists(target):
            if _same_content(entry.path, target):
                _unlink(entry.path)
                continue
            target = _free_name(target, "conflict")
        elif os.path.lexists(target) and _readonly(target):
            set_readonly(target, False)
        if same:
            os.replace(entry.path, target)
        else:
            _copy_verified(entry.path, target)
            _unlink(entry.path)
        moved += 1
    remove_tree(src)
    return moved


def _copy_tree(src: Path, dst: Path) -> dict[str, tuple[int, int]]:
    """Copy every file of ``src`` into ``dst`` (verified, with mtimes). Returns ``{rel:
    (size, mtime_ns)}`` of each file as it was copied."""
    seen: dict[str, tuple[int, int]] = {}
    _mkdirs(dst)
    for rel, entry in _walk_files(src):
        st = entry.stat(follow_symlinks=False)
        _copy_verified(entry.path, os.path.join(_lp(dst), *rel.split("/")))
        seen[rel] = (st.st_size, st.st_mtime_ns)
    return seen


def _catch_up(src: Path, dst: Path, seen: dict[str, tuple[int, int]]) -> None:
    """``dst`` was copied from ``src`` (``seen``): what changed in ``src`` since goes too, a
    file added or changed is copied and one deleted goes."""
    now: set[str] = set()
    for rel, entry in _walk_files(src):
        now.add(rel)
        st = entry.stat(follow_symlinks=False)
        if seen.get(rel) != (st.st_size, st.st_mtime_ns):
            target = os.path.join(_lp(dst), *rel.split("/"))
            if os.path.lexists(target) and _readonly(target):
                set_readonly(target, False)
            _copy_verified(entry.path, target)
    for rel in set(seen) - now:
        target = os.path.join(_lp(dst), *rel.split("/"))
        if os.path.lexists(target):
            _unlink(target)


def _rename_aside(root: Path, staging: Path) -> None:
    """The plugin's folder moves aside on its own volume (one rename: a folder with a file
    open can't move, and then nothing has)."""
    try:
        os.rename(_lp(root), _lp(staging))
    except OSError as exc:
        raise FolderError(f"A file in {_plain(root)} is in use. Close it and try again.") from exc


def _siblings(path: Path, tag: str) -> list[Path]:
    prefix = norm_name(path.name + tag)
    return [Path(_plain(e.path)) for e in _entries(path.parent)
            if norm_name(e.name).startswith(prefix) and e.is_dir(follow_symlinks=False) and not e.is_junction()]


def _adopt_into(root: Path, local: Path) -> str:
    """The plugin's folder becomes Local's copy with a junction in its place (the caller
    holds the plugin's calls back). Its folder is never missing for longer than a rename:
    on another volume it is copied first while the plugin still uses it, then moved aside
    and the junction made, then what changed meanwhile follows. A Local copy already there
    keeps its files; one of the folder's that differs is kept beside it (``(conflict)``)."""
    if not _exists(root):
        _make_junction(root, local)
        return "made"
    if _empty_dir(local):
        os.rmdir(_lp(local))
    staging = root.with_name(f"{root.name}{STAGING}{uuid.uuid4().hex[:8]}")
    if _exists(local):
        _rename_aside(root, staging)
        try:
            _make_junction(root, local)
        except BaseException:
            os.rename(_lp(staging), _lp(root))
            raise
        _absorb(staging, local, keep_both=True)
        return "absorbed"
    _mkdirs(local.parent)
    if _same_volume(root, local.parent):
        try:
            os.rename(_lp(root), _lp(local))
        except OSError as exc:
            if getattr(exc, "winerror", 0) != 17:  # ERROR_NOT_SAME_DEVICE: copy below
                if _in_use(exc):
                    raise FolderError(f"A file in {_plain(root)} is in use. Close it and try again.") from exc
                raise
        else:
            _junction_after_move(root, local)
            return "rename"
    temp = local.with_name(f"{local.name}{ADOPTING}{uuid.uuid4().hex[:8]}")
    try:
        seen = _copy_tree(root, temp)
        _rename_aside(root, staging)
    except BaseException:
        remove_tree(temp)
        raise
    try:
        os.rename(_lp(temp), _lp(local))
        _make_junction(root, local)
        _catch_up(staging, local, seen)
    except BaseException:
        if _is_junction(root):
            os.rmdir(_lp(root))
        if not _exists(root):
            os.rename(_lp(staging), _lp(root))
        remove_tree(local)
        remove_tree(temp)
        raise
    if not remove_tree(staging):
        _log.warning("team folders: %s was copied but its old copy couldn't all be deleted", _plain(staging))
    return "copy"


def _junction_after_move(root: Path, local: Path) -> None:
    """The junction in place of a folder just renamed into ``local``. A folder the plugin
    made again meanwhile joins ``local`` (its files kept beside any that differ)."""
    try:
        _make_junction(root, local)
    except FileExistsError:
        if not os.path.isdir(_lp(root)) or _is_junction(root):
            raise
        _absorb(root, local, keep_both=True)
        _make_junction(root, local)


def _recover_move(plugin: str, root: Path, local: Path) -> None:
    """A move into the Local copy that was cut short (the app closed or crashed): the copy
    made first goes, and a folder moved aside comes back. Where the junction was made
    already its files join the Local copy, and where the plugin made its folder again they
    join that; a file that differs is kept beside the other (``(conflict)``), never lost.
    Never while a move of the plugin's folders is under way."""
    if moving(plugin):
        return
    for temp in _siblings(local, ADOPTING):
        remove_tree(temp)
    for staging in _siblings(root, STAGING):
        if _is_junction(root):
            _absorb(staging, Path(junction_target(root) or local), keep_both=True)
        elif not _exists(root):
            os.rename(_lp(staging), _lp(root))
        else:
            _absorb(root, staging, keep_both=True)
            os.rename(_lp(staging), _lp(root))
        _log.info("team folders: a cut-short move of %s was put right", _plain(root))


# --------------------------------------------------------------------------- roots + refusals


def local_appdata() -> Path:
    from frontend.app_paths import local_app_data_base

    return local_app_data_base()


def app_root() -> Path:
    from frontend.app_paths import resolve_app_data_dir

    return resolve_app_data_dir()


def current_project_root() -> str:
    try:
        from frontend.settings import PanelSettings

        return str(PanelSettings.load().uefn_project_root or "").strip()
    except Exception:  # noqa: BLE001 — no project then
        return ""


def project_id_for(project_root: str) -> str:
    """The id a project's folder copies are kept under: the island's content mount (the
    GUID core matches projects by, else its name), made safe as a folder name."""
    raw = ""
    try:
        from frontend.project_kind import island_mount_name

        raw = island_mount_name(project_root)
    except Exception:  # noqa: BLE001
        raw = ""
    raw = raw or Path(str(project_root)).name
    safe = re.sub(r"[^a-z0-9._-]", "_", norm_name(raw)).strip("._")[:64]
    return safe or hashlib.sha256(_key(project_root).encode("utf-8")).hexdigest()[:16]


def resolve_root(folder: Folder, project_root: str = "") -> Path | None:
    """The plugin's own folder for ``folder`` now (None: a ``{PROJECT}`` root with no project)."""
    token, _, rest = folder.root.partition("/")
    if token == "{PROJECT}":
        if not project_root:
            return None
        return Path(project_root).joinpath(*rest.split("/"))
    return local_appdata().joinpath(*rest.split("/"))


def _volume(path: Any) -> tuple[str, bool]:
    """(file system, remote) of the volume holding ``path``; ('', False) when it can't be told."""
    if os.name != "nt":
        return "", False
    s = _existing(path)
    if s.startswith("\\\\"):
        return "", True
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetVolumePathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        k32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
        k32.GetVolumeInformationW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPDWORD,
                                              wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPWSTR, wintypes.DWORD)
        vol = ctypes.create_unicode_buffer(1024)
        if not k32.GetVolumePathNameW(s, vol, 1024):
            return "", False
        remote = k32.GetDriveTypeW(vol.value) == 4  # DRIVE_REMOTE
        fs = ctypes.create_unicode_buffer(64)
        ok = k32.GetVolumeInformationW(vol.value, None, 0, None, None, None, fs, 64)
        return (fs.value if ok else ""), remote
    except Exception:  # noqa: BLE001 — unknown is never a refusal
        return "", False


def _onedrive_roots() -> list[str]:
    """Folders OneDrive syncs on this PC (its environment variables and its accounts)."""
    roots = [os.environ.get(k, "") for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    if os.name == "nt":
        try:
            import winreg

            for base, value in ((r"Software\Microsoft\OneDrive\Accounts", "UserFolder"),
                                (r"Software\SyncEngines\Providers\OneDrive", "MountPoint")):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                                    roots.append(str(winreg.QueryValueEx(sub, value)[0]))
                            except OSError:
                                continue
                except OSError:
                    continue
        except ImportError:
            pass
    return sorted({r for r in roots if r})


def _urc_carried(folder: Folder, root: Path, project_root: str) -> bool:
    """A ``{PROJECT}`` root inside a UEFN revision control workspace that its ignore file
    doesn't leave out."""
    if not folder.project or not project_root:
        return False
    proj = Path(project_root)
    if not any(_exists(proj / marker) for marker in (".lore", ".urc")):
        return False
    rules: list[tuple[bool, bool, re.Pattern[str]]] = []
    for name in (".loreignore", ".urcignore"):
        try:
            rules += _gitignore((proj / name).read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            continue
    rel = folder.root.partition("/")[2]
    return not _git_ignored(rules, rel, is_dir=True)


def refusal(folder: Folder, root: Path | None, project_root: str = "") -> str:
    """Why ``folder`` can't be shared with a team from this PC ('' when it can)."""
    if root is None:
        return ""
    for where in (root, app_root()):
        fs, remote = _volume(where)
        if remote:
            return REFUSE_NETWORK
        if fs and fs.upper() != "NTFS":
            return REFUSE_VOLUME.format(fs=fs)
    if any(_inside(root, od) for od in _onedrive_roots()):
        return REFUSE_ONEDRIVE
    if _urc_carried(folder, root, project_root):
        return REFUSE_URC
    return ""


# --------------------------------------------------------------------------- copies


def local_copy(plugin: str, folder: Folder | str, project_id: str = "") -> Path:
    """Local's copy of a folder (``folder``: the declaration or its id)."""
    base = app_root() / "scopes" / LOCAL_ACCOUNT / plugin / "folders" / (folder if isinstance(folder, str) else folder.id)
    return base / project_id if project_id else base


def copy_dir(scope: dict[str, Any], plugin: str, folder: Folder, project_id: str = "") -> Path:
    """The copy of ``folder`` a scope reads: Local's for Local, else the scope's own."""
    if scope["kind"] == "personal":
        return local_copy(plugin, folder, project_id)
    from backend.uefn_plugins import scopes

    base = scopes.plugin_dir(scope, plugin) / "folders" / folder.id
    return base / project_id if project_id else base


def team_copy(account: str, space: str, plugin: str, folder: Folder, project_id: str = "") -> Path:
    return copy_dir({"kind": "shared", "account": account, "id": space}, plugin, folder, project_id)


def unit_of(folder: Folder, rel: str, project_id: str = "") -> str:
    """The unit of a file at ``rel`` (relative to the bound folder)."""
    if folder.unit == ".":
        u = ""
    elif folder.unit == "file":
        u = rel
    else:
        u = rel.split("/", 1)[0]
    if project_id:
        return f"{project_id}/{u}" if u else project_id
    return u or "."


def _unit_local(unit: str, project_id: str) -> str:
    """A unit's name inside the bound folder ('' for a whole-folder unit)."""
    if project_id:
        return unit[len(project_id) + 1:] if unit.startswith(project_id + "/") else ""
    return "" if unit == "." else unit


def _stored(rel: str, project_id: str) -> str:
    return f"{project_id}/{rel}" if project_id else rel


def _bound_rel(relpath: str, project_id: str) -> str:
    return relpath[len(project_id) + 1:] if project_id and relpath.startswith(project_id + "/") else relpath


def _within_unit(folder: Folder, rel: str) -> str:
    """``rel`` relative to its unit (what ``last`` and ``merge`` globs see)."""
    if folder.unit == "*" and "/" in rel:
        return rel.split("/", 1)[1]
    if folder.unit == "file":
        return rel.rsplit("/", 1)[-1]
    return rel


def _core_temp(name: str) -> bool:
    """One of core's own files in a copy (a download waiting to land, a backup during an
    apply): never shared, and never a plugin's save in progress."""
    n = norm_name(name)
    return n.endswith(".tmp") and (IN_TAG in n or BAK_TAG in n)


def _disk_files(base: Path, folder: Folder,
                leftovers: list[str] | None = None) -> tuple[dict[str, os.stat_result], set[str]]:
    """(``{rel: stat}`` of every file not ignored, rels of ``*.tmp`` files) under ``base``.
    Ignored folders are pruned; links are never followed; a ``*.tmp`` file is a save in
    progress, never a file to share. Core's own files are left out (``leftovers`` gets them)."""
    out: dict[str, os.stat_result] = {}
    tmp: set[str] = set()
    if not os.path.isdir(_lp(base)):
        return out, tmp
    stack = [("", _lp(base))]
    while stack:
        rel, d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            r = f"{rel}/{e.name}" if rel else e.name
            try:
                if e.is_junction() or e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if not _dir_ignored(folder.ignore, r):
                        stack.append((r, e.path))
                    continue
                if _core_temp(e.name):
                    if leftovers is not None:
                        leftovers.append(r)
                    continue
                if norm_name(e.name).endswith(".tmp"):
                    tmp.add(r)
                    continue
                if matches(folder.ignore, r):
                    continue
                out[r] = e.stat(follow_symlinks=False)
            except OSError:
                continue
    return out, tmp


def local_units(plugin: str, folder: Folder, project_id: str = "", *, root: Path | None = None) -> list[dict[str, Any]]:
    """The units of the Local copy with their sizes (what a first share can copy). Before
    the folder is adopted, its files are still at ``root``."""
    base = local_copy(plugin, folder, project_id)
    if not os.path.isdir(_lp(base)) and root is not None and os.path.isdir(_lp(root)) and not _is_link(root):
        base = root
    files, _tmp = _disk_files(base, folder)
    units: dict[str, dict[str, Any]] = {}
    for rel, st in files.items():
        unit = unit_of(folder, rel, project_id)
        row = units.setdefault(unit, {"folder": folder.id, "unit": unit,
                                      "name": _unit_local(unit, project_id) or "(whole folder)", "files": 0, "bytes": 0})
        row["files"] += 1
        row["bytes"] += int(st.st_size)
    return sorted(units.values(), key=lambda r: norm_name(r["unit"]))


# --------------------------------------------------------------------------- junctions


def _make_junction(link: Path, target: Path) -> None:
    import _winapi

    _mkdirs(target)
    _mkdirs(link.parent)
    _winapi.CreateJunction(os.path.abspath(_plain(target)), _lp(link))


def _point(link: Path, target: Path) -> bool:
    """The junction at ``link`` points at ``target`` (made, or re-pointed with ``os.rmdir`` on
    the junction). Returns whether it changed."""
    if _is_junction(link):
        if _key(junction_target(link) or "") == _key(target):
            _mkdirs(target)
            return False
        os.rmdir(_lp(link))
    elif _exists(link):
        raise FolderError(f"{_plain(link)} is in the way of the plugin's folder.")
    _make_junction(link, target)
    return True


def repair(link: Path, target: Path) -> str:
    """Make ``link`` the junction to ``target`` whatever it is now: missing (made), a junction
    elsewhere or broken (re-pointed), or a real folder the plugin put back in its place (its
    files become changes in ``target``, then the junction comes back). Returns what was
    done: ``ok``, ``made``, ``repointed`` or ``absorbed``."""
    if _is_junction(link):
        return "repointed" if _point(link, target) else "ok"
    if not _exists(link):
        _make_junction(link, target)
        return "made"
    if not os.path.isdir(_lp(link)):
        raise FolderError(f"{_plain(link)} is a file where the plugin's folder belongs. Move it, then try again.")
    _absorb(link, target)
    _make_junction(link, target)
    return "absorbed"


# --------------------------------------------------------------------------- running calls (every process)

_MINE: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("team_folder_calls", default=frozenset())
_MOVER: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("team_folder_moves", default=frozenset())


@contextlib.contextmanager
def call_marker(plugin: str, *, actor: str = "user", ducky: str = ""):
    """A call of ``plugin`` runs in this process: its marker row says so to a re-point in any
    process until the call returns. A call that starts while the plugin's folders are being
    moved (in any process) waits for the move first, without holding it up. A marker that
    can't be written never fails the call."""
    try:
        key = repo.call_add(plugin, os.getpid(), actor=actor, ducky=ducky)
        if plugin not in _MOVER.get() and moving(plugin):
            repo.calls_drop([key])
            _wait_moved(plugin)
            key = repo.call_add(plugin, os.getpid(), actor=actor, ducky=ducky)
    except Exception:  # noqa: BLE001
        _log.debug("recording the call marker of %s failed", plugin, exc_info=True)
        yield ""
        return
    token = _MINE.set(_MINE.get() | {key})
    try:
        yield key
    finally:
        _MINE.reset(token)
        try:
            repo.call_done(key, plugin, actor=actor, ducky=ducky)
        except Exception:  # noqa: BLE001 — a dead marker is dropped by the next wait
            _log.debug("dropping the call marker of %s failed", plugin, exc_info=True)


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = wintypes.DWORD()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def live_calls(plugin: str) -> list[dict[str, Any]]:
    """The plugin's calls running now in any process, except the caller's own. Markers of
    processes that are gone are dropped."""
    mine = _MINE.get()
    live: list[dict[str, Any]] = []
    dead: list[str] = []
    for key, doc in repo.calls(plugin).items():
        if key in mine:
            continue
        if _pid_alive(int(doc.get("pid") or 0)):
            live.append({**doc, "key": key})
        else:
            dead.append(key)
    repo.calls_drop(dead)
    return live


def wait_calls(plugin: str, timeout: float = CALL_WAIT_S, *, poll: float = 0.05) -> bool:
    """Wait up to ``timeout`` seconds for the plugin's running calls to return."""
    deadline = time.monotonic() + max(0.0, timeout)
    while live_calls(plugin):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


def _label(plugin: str) -> str:
    try:
        from backend.uefn_plugins.spaces import plugin_label

        return plugin_label(plugin) or plugin
    except Exception:  # noqa: BLE001
        return plugin


def _quiesce(plugin: str, wait_s: float, must: bool) -> None:
    if not wait_calls(plugin, wait_s) and not must:
        raise Busy(f"{_label(plugin)} is still busy with a call. Try again when it finishes.")


def moving(plugin: str) -> bool:
    """A caller in some process is moving the plugin's folders now (rows of processes that
    are gone are dropped)."""
    live, dead = False, []
    for key, doc in repo.movers(plugin).items():
        if _pid_alive(int(doc.get("pid") or 0)):
            live = True
        else:
            dead.append(key)
    repo.calls_drop(dead)
    return live


def _wait_moved(plugin: str, timeout: float = MOVE_WAIT_S, *, poll: float = 0.05) -> None:
    deadline = time.monotonic() + max(0.0, timeout)
    while moving(plugin) and time.monotonic() < deadline:
        time.sleep(poll)


@contextlib.contextmanager
def _fence(plugin: str, wait_s: float, must: bool):
    """The plugin's folders move inside the block: calls that start meanwhile wait (in any
    process, :func:`call_marker`) and the running ones are waited for first (``must``: go
    ahead after the wait anyway, else :class:`Busy`). A fence inside one is the same fence."""
    if plugin in _MOVER.get():
        yield
        return
    key = repo.moving_add(plugin, os.getpid())
    token = _MOVER.set(_MOVER.get() | {plugin})
    try:
        _quiesce(plugin, wait_s, must)
        yield
    finally:
        _MOVER.reset(token)
        repo.calls_drop([key])


def _repoint(plugin: str, moves: list[tuple[Path, Path]], *, wait_s: float = CALL_WAIT_S, must: bool = False,
             why: str = "") -> int:
    """Point each junction at its new copy once the plugin's calls are done (``must``: go
    ahead after the wait anyway), then bump its reload epoch, all before calls that waited
    for the move go on. Returns how many changed."""
    pending = [(link, target) for link, target in moves
               if not (_is_junction(link) and _key(junction_target(link) or "") == _key(target))]
    for _link, target in moves:
        _mkdirs(target)
    if not pending:
        return 0
    with _fence(plugin, wait_s, must):
        for link, target in pending:
            repair(link, target)
        repo.reload_bump(plugin, why)
    return len(pending)


# --------------------------------------------------------------------------- binding


@dataclass
class Binding:
    """One declared folder as it applies now."""

    folder: Folder
    root: Path | None  # the plugin's own folder (None: a {PROJECT} root with no project open)
    project_id: str = ""
    refused: str = ""


def resolve(plugin: str, *, project_root: str | None = None) -> list[Binding]:
    """Each declared folder of ``plugin`` for the open project (or ``project_root``)."""
    proj = current_project_root() if project_root is None else project_root
    out: list[Binding] = []
    for folder in plugin_folders(plugin):
        if folder.project and not proj:
            out.append(Binding(folder, None))
            continue
        pid = project_id_for(proj) if folder.project else ""
        root = resolve_root(folder, proj)
        out.append(Binding(folder, root, pid, refusal(folder, root, proj) or _same_island(plugin, folder, root, pid)))
    return out


def _same_island(plugin: str, folder: Folder, root: Path | None, project_id: str) -> str:
    """Why a ``{PROJECT}`` folder can't be shared from here: another project on this PC has
    the same id (a copied island keeps its id) and its folder is in use, so both would read
    and write one copy."""
    if not folder.project or root is None:
        return ""
    link = repo.link_get(plugin, folder.id, project_id)
    if link is None or _key(link["root"]) == _key(root) or not _exists(link["root"]):
        return ""
    depth = len(folder.root.partition("/")[2].split("/"))
    other = Path(link["root"]).parents[depth - 1]
    return REFUSE_SAME_ISLAND.format(name=other.name)


def _adopted(plugin: str, b: Binding) -> bool:
    if b.root is None:
        return False
    if _is_junction(b.root):
        return True
    link = repo.link_get(plugin, b.folder.id, b.project_id)
    return link is not None and _key(link["root"]) == _key(b.root)


def adopt(plugin: str, b: Binding, *, wait_s: float = CALL_WAIT_S, must: bool = False) -> dict[str, Any]:
    """Once, on the first team link: the plugin's folder moves into the Local copy and a
    junction to it takes its place (the plugin sees the same files). Same volume: a
    rename; another volume: copy and verify while the plugin keeps its folder, then a
    rename aside, the junction, and what changed meanwhile. It happens once the plugin's
    calls are done, and calls that start meanwhile wait (as for a re-point). The link row
    is written first, so a move cut short is put right by the next bind. Nothing happens
    to a folder already adopted."""
    if b.root is None:
        return {"ok": True, "adopted": False}
    if b.refused:
        raise FolderError(b.refused)
    local = local_copy(plugin, b.folder, b.project_id)
    _recover_move(plugin, b.root, local)
    link = repo.link_get(plugin, b.folder.id, b.project_id)
    how = "none"
    if _is_junction(b.root):
        how = "already"
    elif _exists(b.root) and not os.path.isdir(_lp(b.root)):
        raise FolderError(f"{_plain(b.root)} is a file where the plugin's folder belongs. Move it, then try again.")
    else:
        fresh = link is None or _key(link["root"]) != _key(b.root)  # none yet, or a project that moved
        if fresh:
            repo.link_put(plugin, b.folder.id, b.project_id, root=str(b.root), target=str(local),
                          account=LOCAL_ACCOUNT, space=PERSONAL)
        try:
            with _fence(plugin, wait_s, must):
                how = _adopt_into(b.root, local)
        except BaseException:
            if fresh and not _is_junction(b.root):
                repo.link_delete(plugin, b.folder.id, b.project_id)
            raise
    if link is None or how != "already":
        target = junction_target(b.root) or str(local)
        mine = _inside(target, local)
        repo.link_put(plugin, b.folder.id, b.project_id, root=str(b.root), target=target,
                      account=LOCAL_ACCOUNT if mine else (link or {}).get("account_id", ""),
                      space=PERSONAL if mine else (link or {}).get("space_id", ""))
    return {"ok": True, "adopted": how}


def _ready(account: str, space: str, plugin: str, b: Binding) -> bool:
    return bool(repo.copy_get(account, space, plugin, b.folder.id, b.project_id)["ready"])


def _target(scope: dict[str, Any], plugin: str, b: Binding) -> tuple[Path, str, str]:
    """(copy, account, space) the junction of ``b`` points at for ``scope``: a team's copy
    only once it may be bound (never for a refused folder), else Local's."""
    team = scope["kind"] == "shared" and not b.refused and _ready(scope["account"], scope["id"], plugin, b)
    if team or scope["kind"] == "sandbox":
        return copy_dir(scope, plugin, b.folder, b.project_id), scope["account"], scope["id"]
    return local_copy(plugin, b.folder, b.project_id), LOCAL_ACCOUNT, PERSONAL


def _migrate_link(plugin: str, scope: dict[str, Any]) -> bool:
    """A plugin linked to a team before this PC kept its folders in a team copy (never
    pulled or sent): it goes back on Local, and the bar offers to copy Local into the team."""
    if scope["kind"] != "shared":
        return False
    account, space = scope["account"], scope["id"]
    if repo.ever_synced(account, space, plugin):
        return False
    if any(c["ready"] for c in repo.copies(account, space, plugin)):
        return False
    from backend.store.repos import plugin_data

    plugin_data.link_set(account, plugin, PERSONAL)
    for folder in plugin_folders(plugin):
        repo.copy_put(account, space, plugin, folder.id, "", offer=1)
    _log.info("team folders: %s was linked to a team copy never pulled here; it is on Local again", plugin)
    return True


def offers(plugin: str) -> list[dict[str, Any]]:
    """Teams the bar offers to copy ``plugin``'s Local folders into (see :func:`_migrate_link`)."""
    from backend.uefn_plugins import scopes

    account = scopes.account_id()
    out: dict[str, dict[str, Any]] = {}
    for c in repo.copies(account, plugin=plugin):
        if c["offer"]:
            out.setdefault(c["space_id"], {"space": c["space_id"], "label": _space_label(account, c["space_id"])})
    return list(out.values())


def _space_label(account: str, space: str) -> str:
    try:
        from backend.store.repos import plugin_data

        return str(plugin_data.sync_get(account, space)["label"] or space)
    except Exception:  # noqa: BLE001
        return space


def bind_plugin(plugin: str, *, project_root: str | None = None, wait_s: float = CALL_WAIT_S) -> dict[str, Any]:
    """Point every folder of ``plugin`` at the copy it reads now, repairing what broke
    (before the plugin loads, on a reload, a project switch or an account change). A team
    copy is used only once it may be bound; until then, and for Local, Local's copy. A
    folder never adopted stays the plugin's own until its first team link, unless the
    team's copy is ready here. Never moves data between copies."""
    folders = plugin_folders(plugin)
    if not folders:
        return {"ok": True, "folders": []}
    if sandboxed(plugin):
        return {"ok": True, "folders": [], "sandboxed": True}
    from backend.uefn_plugins import scopes

    scope = scopes.active_scope(plugin)
    if _migrate_link(plugin, scope):
        scope = scopes.active_scope(plugin)
    out: list[dict[str, Any]] = []
    moves: list[tuple[Path, Path]] = []
    rows: list[tuple[Binding, Path, str, str]] = []
    bindings = resolve(plugin, project_root=project_root)
    for b in bindings:
        if b.root is None:
            out.append({"folder": b.folder.id, "state": "no_project"})
            continue
        target, account, space = _target(scope, plugin, b)
        adopted = _adopted(plugin, b)
        if not adopted and space == PERSONAL:
            out.append({"folder": b.folder.id, "state": "refused" if b.refused else "own", "reason": b.refused})
            continue
        try:
            if adopted:
                _recover_move(plugin, b.root, local_copy(plugin, b.folder, b.project_id))
            else:
                adopt(plugin, b, wait_s=wait_s, must=True)
        except OSError as exc:
            out.append({"folder": b.folder.id, "state": "error", "reason": str(exc)})
            continue
        moves.append((b.root, target))
        rows.append((b, target, account, space))
    if scope["kind"] != "shared":
        for b in _other_links_to_local(plugin, bindings):
            local = local_copy(plugin, b.folder, b.project_id)
            moves.append((b.root, local))
            rows.append((b, local, LOCAL_ACCOUNT, PERSONAL))
    try:
        _repoint(plugin, moves, wait_s=wait_s, must=True, why="bind")
    except (FolderError, OSError) as exc:
        return {"ok": False, "error": str(exc), "folders": out}
    for b, target, account, space in rows:
        repo.link_put(plugin, b.folder.id, b.project_id, root=str(b.root), target=str(target), account=account,
                      space=space)
        out.append({"folder": b.folder.id, "state": "team" if space != PERSONAL else "local",
                    "reason": b.refused, "target": str(target)})
    return {"ok": True, "folders": out}


def _other_links_to_local(plugin: str, bindings: Iterable[Binding]) -> list[Binding]:
    """Junctions of the plugin's projects not open now that point at a team's copy. Going to
    Local (a switch, signing out) takes them back to Local too, so no project folder on this
    PC still shows a team's files or takes writes into a copy nothing scans."""
    have = {(b.folder.id, b.project_id) for b in bindings if b.root is not None}
    out: list[Binding] = []
    for lk in repo.links(plugin):
        folder = folder_of(plugin, lk["folder_id"])
        root = Path(lk["root"])
        if folder is None or (folder.id, lk["project_id"]) in have or not _is_junction(root):
            continue
        if _key(junction_target(root) or "") != _key(local_copy(plugin, folder, lk["project_id"])):
            out.append(Binding(folder, root, lk["project_id"]))
    return out


def _has_files(base: Path, folder: Folder) -> bool:
    return bool(_disk_files(base, folder)[0])


def first_share_units(plugin: str, bindings: Iterable[Binding]) -> list[dict[str, Any]]:
    return [u for b in bindings for u in local_units(plugin, b.folder, b.project_id)]


def _lacking_units(plugin: str, scope: dict[str, Any], b: Binding) -> list[dict[str, Any]]:
    """Local's units of ``b`` that the scope's copy doesn't have (what "Copy Local into" can add)."""
    have = {unit_of(b.folder, rel, b.project_id)
            for rel in _disk_files(copy_dir(scope, plugin, b.folder, b.project_id), b.folder)[0]}
    return [u for u in local_units(plugin, b.folder, b.project_id) if u["unit"] not in have]


def switch(plugin: str, scope_id: str, *, project_root: str | None = None,
           pull: Callable[[], tuple[bool, str]] | None = None, push: Callable[[], tuple[bool, str]] | None = None,
           first_share: dict[str, Any] | None = None, wait_s: float = CALL_WAIT_S) -> dict[str, Any]:
    """The folder part of moving ``plugin`` to Local (``personal``) or a team.

    To a team: a refused folder refuses the switch with its reason; each folder is
    adopted (its junction on the copy in use); ``pull()`` brings the team's copy to
    completion while the junction still points at the current copy, and a failed pull
    fails the switch with nothing else changed. A team copy with files may be bound. An
    empty one needs the first share: without ``first_share`` the answer is
    ``{needs: "first_share", units, note}``; ``{"units": [...]}`` copies those Local units
    into the team copy (units it has stay as they are) and ``push()`` sends them before
    binding; ``{"start_empty": true}`` binds it empty. ``{"pick": true}`` (the bar's "Copy
    Local into <team>") asks the same with the Local units the team's copy lacks, even
    when it has files. Then, once the plugin's calls are done, the junctions point at the
    copies and the plugin's reload epoch moves on (``ok``). Going to Local takes the
    junctions of the plugin's other projects back to Local too. The caller links the plugin.
    """
    from backend.uefn_plugins import scopes

    folders = plugin_folders(plugin)
    if not folders:
        return {"ok": True, "folders": []}
    account = scopes.account_id()
    if scope_id != PERSONAL and (account == scopes.LOCAL or not scopes.valid_space_id(scope_id)):
        return {"ok": False, "error": "Sign in to share a plugin's data" if account == scopes.LOCAL else
                "invalid space id"}
    scope = scopes.personal_scope(account) if scope_id == PERSONAL else scopes.shared_scope(account, scope_id)
    bindings = [b for b in resolve(plugin, project_root=project_root) if b.root is not None]
    moves: list[tuple[Path, Path]] = []
    if scope["kind"] == "shared":
        refused = {b.folder.id: b.refused for b in bindings if b.refused}
        if refused:
            return {"ok": False, "error": next(iter(refused.values())), "refused": refused}
        try:
            for b in bindings:
                adopt(plugin, b, wait_s=wait_s)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if pull is not None:
            ok, why = pull()
            if not ok:
                return {"ok": False, "error": why or f"{scope['label']}'s files didn't arrive. Nothing changed."}
            for b in bindings:
                repo.copy_put(account, scope_id, plugin, b.folder.id, b.project_id, pulled_at=time.time())
            for folder in folders:  # pulled even with no project open: never moved back to Local
                repo.copy_put(account, scope_id, plugin, folder.id, "", pulled_at=time.time())
        waiting: list[Binding] = []
        for b in bindings:
            if _ready(account, scope_id, plugin, b):
                continue
            if _has_files(copy_dir(scope, plugin, b.folder, b.project_id), b.folder):
                repo.copy_put(account, scope_id, plugin, b.folder.id, b.project_id, ready=1)
            else:
                waiting.append(b)
        share = first_share or {}
        chosen = {str(u) for u in share.get("units") or ()}
        if (waiting or share.get("pick")) and not (chosen or share.get("start_empty")):
            asked = bindings if share.get("pick") else waiting
            units = [u for b in asked for u in _lacking_units(plugin, scope, b)]
            if waiting or units:
                partial = any(b not in waiting for b in asked)  # the team has some of the files already
                return {"ok": False, "needs": "first_share", "team": scope["label"], "note": PLAINTEXT_NOTE,
                        "units": units, **({"partial": True} if partial else {})}
        copied = 0
        try:
            for b in bindings:
                units = [u["unit"] for u in local_units(plugin, b.folder, b.project_id) if u["unit"] in chosen]
                if units:
                    copied += copy_local_into(plugin, b.folder, account, scope_id, units, b.project_id)["copied"]
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if copied and push is not None:
            ok, why = push()
            if not ok:
                return {"ok": False, "error": why or f"Your files didn't reach {scope['label']}. Nothing changed."}
        for b in waiting:
            repo.copy_put(account, scope_id, plugin, b.folder.id, b.project_id, ready=1,
                          pushed_at=time.time() if copied else 0.0, offer=0)
        for b in bindings:
            moves.append((b.root, copy_dir(scope, plugin, b.folder, b.project_id)))
    else:
        bindings += _other_links_to_local(plugin, bindings)
        moves = [(b.root, local_copy(plugin, b.folder, b.project_id)) for b in bindings if _adopted(plugin, b)]
    try:
        changed = _repoint(plugin, moves, wait_s=wait_s, must=False, why="switch")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    for link, target in moves:
        b = next(x for x in bindings if x.root == link)
        shared = scope["kind"] == "shared"
        repo.link_put(plugin, b.folder.id, b.project_id, root=str(link), target=str(target),
                      account=account if shared else LOCAL_ACCOUNT, space=scope_id if shared else PERSONAL)
    if scope["kind"] == "shared":
        for c in repo.copies(account, scope_id, plugin):
            if c["offer"]:
                repo.copy_put(account, scope_id, plugin, c["folder_id"], c["project_id"], offer=0)
    return {"ok": True, "changed": changed, "folders": [b.folder.id for b in bindings]}


# --------------------------------------------------------------------------- plugin tests


def sandboxed(plugin: str) -> bool:
    """A test of ``plugin`` has its folders now (a flag left by a process that is gone is dropped)."""
    doc = repo.sandbox_get(plugin)
    if not doc:
        return False
    if _pid_alive(int(doc.get("pid") or 0)):
        return True
    repo.sandbox_delete(plugin)
    return False


def sandbox_begin(plugin: str, scope: dict[str, Any], *, wait_s: float = CALL_WAIT_S) -> int:
    """A test of ``plugin`` starts: its folders point at the test's throwaway copies (empty)
    once its other calls are done. A folder never shared yet is adopted first, so the test
    never writes into the real one (one that can't be, refuses the test with the reason).
    A junction is every process's: while the test runs, the plugin's calls from outside
    it are refused (:func:`backend.uefn_plugins.scopes.write_group`), and nothing is
    captured from its folders. Returns how many folders moved."""
    bindings = [b for b in resolve(plugin) if b.root is not None]
    if not bindings and not repo.links(plugin):
        return 0
    with _fence(plugin, wait_s, False):
        for b in bindings:
            if _adopted(plugin, b):
                continue
            if b.refused:
                raise FolderError(f"{_label(plugin)}'s folder can't be swapped for a test copy: {b.refused}")
            adopt(plugin, b, wait_s=0.0, must=True)
        moves: list[tuple[Path, Path]] = []
        back: list[list[str]] = []
        for lk in repo.links(plugin):
            folder = folder_of(plugin, lk["folder_id"])
            if folder is not None and _is_junction(lk["root"]):
                moves.append((Path(lk["root"]), copy_dir(scope, plugin, folder, lk["project_id"])))
                back.append([lk["root"], junction_target(lk["root"]) or lk["target"]])
        if not moves:
            return 0
        repo.sandbox_put(plugin, {"pid": os.getpid(), "scope": scope["id"], "started": time.time(), "back": back})
        try:
            return _repoint(plugin, moves, wait_s=0.0, must=True, why="test")
        except BaseException:
            sandbox_end(plugin)
            raise


def sandbox_end(plugin: str) -> None:
    """The test is over: each folder points at the copy it pointed at before the test, then
    at the copy the plugin reads now (a switch made meanwhile)."""
    doc = repo.sandbox_get(plugin)
    if not doc:
        return
    repo.sandbox_delete(plugin)
    moves = [(Path(root), Path(target)) for root, target in doc.get("back") or [] if root and target]
    try:
        _repoint(plugin, moves, wait_s=0.0, must=True, why="test over")
        bind_plugin(plugin, wait_s=0.0)
    except Exception:  # noqa: BLE001 — the next bind repairs them
        _log.warning("team folders: putting %s's folders back after its test failed", plugin, exc_info=True)


# --------------------------------------------------------------------------- capture


@dataclass
class Scan:
    """What one scan of a team copy found. ``changed``: files changed per unit this scan;
    ``quiet``: units ready to go out; ``waiting``: units changed less than 3 s ago or with a
    ``*.tmp`` file; ``held``: units with changes that don't go out (conflict, refused,
    changed while someone else holds them); ``refused``: unit → reason."""

    changed: dict[str, int] = field(default_factory=dict)
    quiet: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    tmp: set[str] = field(default_factory=set)
    files: int = 0


def _renamed(rows: dict[str, Any], names: Iterable[str]) -> dict[str, str]:
    """``{name on disk: its row's name}`` of files renamed in place: the row's name isn't on
    disk, and only their case or Unicode form differs (one file and one row each). Such a
    file is the same item (the same key), never a delete and an add."""
    names = list(names)
    on_disk = set(names)
    free: dict[str, list[str]] = {}
    for stored in rows:
        if stored not in on_disk:
            free.setdefault(norm_name(stored), []).append(stored)
    if not free:
        return {}
    new: dict[str, list[str]] = {}
    for stored in names:
        if stored not in rows:
            new.setdefault(norm_name(stored), []).append(stored)
    return {got[0]: free[n][0] for n, got in new.items() if len(got) == 1 and len(free.get(n, ())) == 1}


def _sweep(base: Path, leftovers: Iterable[str]) -> None:
    """Core's own files a crash left in a copy (callers hold the space's round lock, so no
    apply is under way): a backup whose file is missing goes back in its place, any other
    backup and every download goes."""
    for rel in leftovers:
        path = os.path.join(_lp(base), *rel.split("/"))
        name = rel.rsplit("/", 1)[-1]
        target = os.path.join(os.path.dirname(path), name.rsplit(BAK_TAG, 1)[0]) if BAK_TAG in name else ""
        try:
            if target and not os.path.lexists(target):
                os.replace(path, target)
            else:
                _unlink(path)
        except OSError:
            _log.debug("team folders: %s couldn't be put right", _plain(path), exc_info=True)


def _clashes(rels: Iterable[str], key: Callable[[str], str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for rel in rels:
        groups.setdefault(key(rel), []).append(rel)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def _foreign_units(account: str, space: str, plugin: str, units: Iterable[str],
                   unit_id: Callable[[str], str] | None) -> dict[str, dict[str, Any]]:
    """``{unit: lock}`` of these units someone else holds a live lock on."""
    if unit_id is None:
        return {}
    from backend.store.repos import space_vcs

    held = {lk["unit"]: lk for lk in space_vcs.locks(account, space, plugin) if not lk["mine"]}
    out: dict[str, dict[str, Any]] = {}
    for unit in set(units):
        lk = held.get(unit_id(unit))
        if lk is not None:
            out[unit] = lk
    return out


def note_ai_edit(paths: Iterable[Any], *, ducky: str = "", at: float | None = None) -> list[str]:
    """An AI's own file tool (Codex's apply_patch, Claude Code's Edit or Write) is about to
    change, or changed, ``paths`` outside any plugin call. Each plugin whose declared folder
    holds one of them notes it, so the change goes out as the AI's, never the person's
    (:func:`_caller`). Returns those plugins."""
    from backend.uefn_plugins.store import get_enabled_plugin_ids

    wanted = [p for p in paths if p]
    if not wanted:
        return []
    project = current_project_root()
    noted: list[str] = []
    for plugin in get_enabled_plugin_ids():
        roots: list[Any] = []
        for folder in plugin_folders(plugin):
            root = resolve_root(folder, project)
            if root is not None:
                roots += [root, *filter(None, [junction_target(root)])]
        if roots and any(_inside(p, r) for p in wanted for r in roots):
            repo.last_call_put(plugin, actor="agent", ducky=ducky, at=at)
            noted.append(plugin)
    return noted


def _caller(plugin: str, now: float) -> tuple[str, str]:
    for doc in live_calls(plugin):
        return str(doc.get("actor") or "user"), str(doc.get("ducky") or "")
    last = repo.last_call(plugin)
    if last and now - float(last.get("at") or 0.0) <= AGENT_WINDOW_S:
        return str(last.get("actor") or "user"), str(last.get("ducky") or "")
    return "user", ""


def _tmp_units(folder: Folder, tmp: Iterable[str], units: Iterable[str], project_id: str,
               files: set[str]) -> set[str]:
    """Units a ``*.tmp`` file (a save in progress) belongs to: inside a folder unit, or
    beside a file unit (a save writes its temp file next to the file it replaces)."""
    tmp = list(tmp)
    out: set[str] = set()
    tmp_dirs = {rel.rpartition("/")[0] for rel in tmp}
    for unit in units:
        local = _unit_local(unit, project_id)
        if not local:
            if tmp:
                out.add(unit)
        elif any(rel.startswith(local + "/") for rel in tmp):
            out.add(unit)
        elif (folder.unit == "file" or local in files) and local.rpartition("/")[0] in tmp_dirs:
            out.add(unit)
    return out


_KEEP_ON_CHANGE = ("conflict", "quarantined", "locked_out")  # unit states a new edit doesn't clear


def scan(account: str, space: str, plugin: str, folder: Folder, *, project_id: str = "", now: float | None = None,
         quiet_s: float = QUIET_S, unit_id: Callable[[str], str] | None = None) -> Scan:
    """Capture one team copy: a stat scan against ``folder_files`` (ignored globs pruned;
    sha256 only for files whose size or mtime changed, streamed, outside any transaction).
    A changed file is dirty unless its content is the team's again; a missing one is a
    delete. A unit is ready (``quiet``) after ``quiet_s`` seconds without changes and with
    no ``*.tmp`` file. Names in one unit that differ only by case or Unicode form are
    refused with the reason. Changes to a unit someone else holds are quarantined. A
    plugin under test is skipped. ``unit_id`` maps a unit to its id on the server (locks,
    presence)."""
    from backend.store import db

    now = time.time() if now is None else float(now)
    out = Scan()
    if sandboxed(plugin):
        return out
    base = team_copy(account, space, plugin, folder, project_id)
    left: list[str] = []
    disk, tmp = _disk_files(base, folder, left)
    if left:  # core's own files a crash left: put back or dropped, so the unit isn't held forever
        _sweep(base, left)
        disk, tmp = _disk_files(base, folder)
    out.files = len(disk)
    rows = {r["relpath"]: r for r in repo.files(account, space, plugin, folder.id, project_id=project_id)}
    moved = _renamed(rows, [_stored(rel, project_id) for rel in disk])  # name on disk → its row's name
    by_unit: dict[str, list[str]] = {}
    for rel in disk:
        by_unit.setdefault(unit_of(folder, rel, project_id), []).append(rel)
    out.tmp = _tmp_units(folder, tmp, set(by_unit) | {r["unit"] for r in rows.values()}, project_id, set(disk))
    for unit, rels in by_unit.items():
        for names in _clashes(rels, norm_name).values():
            out.refused[unit] = f"{' and '.join(names)}{CLASH} Rename one so the team can tell them apart."
        big = sorted(rel for rel in rels if disk[rel].st_size > FILE_MAX_BYTES)
        if big:  # never uploaded only to be refused
            out.refused[unit] = TOO_BIG + big[0]
    for names in _clashes(by_unit, norm_name).values():
        for unit in names:
            out.refused[unit] = f"{' and '.join(names)}{CLASH} Rename one."
    held = _foreign_units(account, space, plugin, set(by_unit) | {r["unit"] for r in rows.values()}, unit_id)
    # A unit held back (a conflict, changed while someone held it) holds a new change to it too.
    unit_kept: dict[str, tuple[str, str]] = {}
    for r in rows.values():
        if r["sync_state"] in _KEEP_ON_CHANGE:
            unit_kept.setdefault(r["unit"], (r["sync_state"], r["sync_error"]))

    def _state(unit: str, row: dict[str, Any] | None) -> tuple[str, str]:
        if unit in held:
            return "quarantined", _held_text(held[unit])
        if row is not None and row["sync_state"] in _KEEP_ON_CHANGE:
            return row["sync_state"], row["sync_error"]
        return unit_kept.get(unit, ("", ""))

    puts: list[tuple[str, dict[str, Any]]] = []
    drops: list[str] = []
    for rel, st in disk.items():
        stored = _stored(rel, project_id)
        row = rows.get(stored) or rows.get(moved.get(stored, ""))
        unit = unit_of(folder, rel, project_id)
        if row is not None and row["sync_state"] == "refetch":
            continue  # Discard mine: the team's version is on its way
        if row is not None and not row["deleted"] and int(row["size"]) == st.st_size \
                and int(row["mtime_ns"]) == st.st_mtime_ns:
            continue
        try:
            sha = _sha_file(os.path.join(_lp(base), *rel.split("/")))
        except OSError:
            continue  # being written: the next scan reads it
        if row is not None and not row["deleted"] and row["sha256"] == sha:
            puts.append((stored, {"size": st.st_size, "mtime_ns": st.st_mtime_ns}))
            continue
        dirty = sha != (row["base_sha"] if row else "")
        state, why = _state(unit, row) if dirty else ("", "")
        puts.append((stored, {"unit": unit, "project_id": project_id, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                              "sha256": sha, "dirty": dirty, "deleted": False,
                              "changed_at": min(now, st.st_mtime_ns / 1e9) if dirty else 0.0, "sync_state": state,
                              "sync_error": why}))
        if dirty:
            out.changed[unit] = out.changed.get(unit, 0) + 1
    renamed = set(moved.values())
    for stored, row in rows.items():
        if _bound_rel(stored, project_id) in disk or stored in renamed or row["sync_state"] == "refetch" \
                or row["deleted"]:
            continue
        if not row["base_seq"] and not row["base_sha"]:
            drops.append(stored)  # never on the team: nothing to send
            continue
        unit = row["unit"]
        state, why = _state(unit, row)
        puts.append((stored, {"sha256": "", "size": 0, "mtime_ns": 0, "dirty": True, "deleted": True,
                              "changed_at": now, "sync_state": state, "sync_error": why}))
        out.changed[unit] = out.changed.get(unit, 0) + 1

    conn = db.connect()
    with db.write_txn(conn):
        # Renamed in place (case or Unicode form only): the same item under its new name.
        for new, old in moved.items():
            repo.file_rename(conn, account, space, plugin, folder.id, old, new,
                             unit_of(folder, _bound_rel(new, project_id), project_id))
        for stored, fields_ in puts:
            repo.file_put(conn, account, space, plugin, folder.id, stored, **fields_)
        for stored in drops:
            repo.file_delete(conn, account, space, plugin, folder.id, stored)
        for unit, why in out.refused.items():
            repo.unit_set_state(account, space, plugin, folder.id, unit, "refused", why, conn=conn)
        # A clash renamed away, or a file too big made smaller or removed: the unit's files go out again.
        still = ", ".join("?" * len(out.refused)) or "''"
        conn.execute("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? AND "
                     "plugin_id=? AND folder_id=? AND project_id=? AND sync_state='refused' AND "
                     f"(sync_error LIKE ? OR sync_error LIKE ?) AND unit NOT IN ({still})",
                     (account, space, plugin, folder.id, project_id, f"%{CLASH}%", f"{TOO_BIG}%", *out.refused))
        # A unit whose sends kept failing (blocked) goes again, afresh, once it changes.
        if out.changed:
            conn.execute("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? AND "
                         "plugin_id=? AND folder_id=? AND sync_state='blocked' AND unit IN "
                         f"({', '.join('?' * len(out.changed))})", (account, space, plugin, folder.id, *out.changed))
    if out.changed:
        from backend.store.repos import space_vcs

        space_vcs.unit_tries_clear(account, space, plugin, [f"{folder.id}/{unit}" for unit in out.changed])
        _note_activity(account, space, plugin, folder, out.changed, now, unit_id)
    for (_fid, unit), info in repo.dirty_units(account, space, plugin, folder.id).items():
        if project_id and not (unit == project_id or unit.startswith(project_id + "/")):
            continue
        if info["states"] & set(HELD_STATES):
            out.held.append(unit)
        elif unit in out.tmp or now - info["changed_at"] < quiet_s:
            out.waiting.append(unit)
        else:
            out.quiet.append(unit)
    out.quiet.sort()
    out.waiting.sort()
    out.held.sort()
    return out


def _held_text(lock: dict[str, Any] | None) -> str:
    if not lock:
        return ""
    try:
        from backend.uefn_plugins.vcs_engine import holder_of

        who = holder_of(str(lock.get("account_id") or ""), str(lock.get("space_id") or ""), lock)[0]
    except Exception:  # noqa: BLE001
        who = person(lock.get("holder_name"), lock.get("holder_user"))
    return f"Changed here while {who} holds it"


def _note_activity(account: str, space: str, plugin: str, folder: Folder, changed: dict[str, int], now: float,
                   unit_id: Callable[[str], str] | None) -> None:
    try:
        from backend.store.repos import space_vcs

        actor, ducky = _caller(plugin, now)
        for unit in changed:
            uid = unit_id(unit) if unit_id is not None else f"tree:{folder.id}/{unit}"
            space_vcs.activity_note(account, space, plugin, uid, actor=actor, ducky=ducky, at=now)
    except Exception:  # noqa: BLE001 — presence is a hint
        _log.debug("noting folder activity for %s failed", plugin, exc_info=True)


def quiet_units(account: str, space: str, plugin: str, folder: Folder, *, project_id: str = "",
                now: float | None = None, quiet_s: float = QUIET_S) -> list[str]:
    """Units ready to go out now (a fresh :func:`scan` decides; this reads it again)."""
    return scan(account, space, plugin, folder, project_id=project_id, now=now, quiet_s=quiet_s).quiet


def outgoing(account: str, space: str, plugin: str, folder: Folder, unit: str, *,
             project_id: str = "") -> list[dict[str, Any]]:
    """One unit's changes to send, as the last scan saw them: each changed file (``put``,
    with its plaintext ``path`` on disk, ``size``, ``sha256``, ``mtime_ns``) or deleted one
    (``del``), with ``base_seq`` (the team's version it is based on) and ``item_key``."""
    base = team_copy(account, space, plugin, folder, project_id)
    out: list[dict[str, Any]] = []
    for r in repo.files(account, space, plugin, folder.id, unit=unit):
        if not r["dirty"]:
            continue
        rel = _bound_rel(r["relpath"], project_id)
        out.append({"relpath": r["relpath"], "unit": unit, "op": "del" if r["deleted"] else "put",
                    "path": "" if r["deleted"] else os.path.join(_lp(base), *rel.split("/")),
                    "size": int(r["size"]), "sha256": r["sha256"], "mtime_ns": int(r["mtime_ns"]),
                    "base_seq": int(r["base_seq"]), "item_key": r["item_key"]})
    return out


def mark_sent(account: str, space: str, plugin: str, folder: Folder, items: Iterable[dict[str, Any]], seq: int, *,
              project_id: str = "") -> dict[str, int]:
    """The server committed these files (as :func:`outgoing` listed them) at ``seq``. Per
    file, compare and set: still exactly what went out → clean at ``seq``; changed since →
    stays dirty on the new base; a delete still deleted → its row goes. Files the folder
    merges keep what went out as their merge base. Returns ``{clean, kept}``."""
    from backend.store import db

    items = list(items)
    bases: dict[str, tuple[str, str] | None] = {}
    for it in items:
        if it.get("op") == "put" and folder.merge and it.get("path"):
            try:
                data = read_bytes(it["path"])
            except OSError:
                continue
            if hashlib.sha256(data).hexdigest() == it.get("sha256"):
                bases[it["relpath"]] = _sealed_base(account, folder, it["relpath"], data)
    clean = kept = 0
    conn = db.connect()
    with db.write_txn(conn):
        for it in items:
            rel, sha, deleted = str(it["relpath"]), str(it.get("sha256") or ""), it.get("op") == "del"
            row = repo.file_get(account, space, plugin, folder.id, rel, conn=conn)
            if row is None:
                continue
            if bool(row["deleted"]) == deleted and row["sha256"] == sha and row["dirty"]:
                if deleted:
                    repo.file_delete(conn, account, space, plugin, folder.id, rel)
                    repo.base_delete(conn, account, space, plugin, folder.id, rel)
                else:
                    repo.file_put(conn, account, space, plugin, folder.id, rel, dirty=False, base_seq=seq,
                                  base_sha=sha, sync_state="", sync_error="", changed_at=0.0)
                    if bases.get(rel):
                        repo.base_put(conn, account, space, plugin, folder.id, rel, seq, *bases[rel])
                clean += 1
            else:
                repo.file_put(conn, account, space, plugin, folder.id, rel, base_seq=seq,
                              base_sha="" if deleted else sha)
                kept += 1
    repo.copy_put(account, space, plugin, folder.id, project_id, pushed_at=time.time())
    return {"clean": clean, "kept": kept}


def outbox(account: str, space: str, plugin: str) -> Path:
    """Where files about to go out are copied (core's own folder, never the plugin's)."""
    from backend.uefn_plugins import scopes

    return scopes.plugin_dir({"account": account, "id": space}, plugin) / "outgoing"


def snapshot(account: str, space: str, plugin: str, cs_id: str, key: str, path: str, sha256: str) -> str:
    """A copy of a file a changeset sends, made in one read as it is now: the upload reads
    the copy at its own pace while the plugin goes on saving the file, and what goes out is
    always what the changeset says (a retry sends the same copy). Returns the copy's path,
    or '' when the file is no longer what the scan saw (its unit goes again as it is now)."""
    box = outbox(account, space, plugin) / cs_id
    dst = os.path.join(_lp(box), hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".out")
    if os.path.isfile(dst):
        return dst
    _mkdirs(box)
    part = dst + ".part"
    try:
        got = copy_hashed(path, part)
        if got == sha256:
            os.replace(part, dst)
            return dst
    except OSError:
        pass
    with contextlib.suppress(OSError):
        _unlink(part)
    return ""


def drop_snapshots(account: str, space: str, plugin: str, cs_id: str) -> None:
    """A changeset's copies are gone once it is answered for good."""
    remove_tree(outbox(account, space, plugin) / cs_id)


def prune_snapshots(account: str, space: str, plugin: str, keep: Iterable[str]) -> None:
    """Copies of changesets no longer waiting to go (a crash's leftovers) go."""
    keep = set(keep)
    for e in _entries(outbox(account, space, plugin)):
        if e.name not in keep:
            remove_tree(e.path)


# --------------------------------------------------------------------------- apply


@dataclass(frozen=True)
class Incoming:
    """One file of a pulled change to a unit. ``relpath`` is relative to the bound folder;
    ``temp`` holds the verified content, already in the target's own folder
    (:func:`temp_for`)."""

    relpath: str
    op: str = "put"
    temp: str = ""
    mtime_ns: int = 0
    sha256: str = ""
    size: int = 0
    item_key: str = ""


def temp_for(account: str, space: str, plugin: str, folder: Folder, relpath: str, project_id: str = "") -> Path:
    """Where a download of ``relpath`` lands first: a uuid-named file of core's own in its
    own folder (the replace is a rename; a crash's leftover is swept by the next scan)."""
    target = Path(os.path.join(_plain(team_copy(account, space, plugin, folder, project_id)), *relpath.split("/")))
    _mkdirs(target.parent)
    return target.with_name(f".{target.name}{IN_TAG}{uuid.uuid4().hex[:12]}.tmp")


def _unit_rows(account: str, space: str, plugin: str, folder: Folder, unit: str, project_id: str, *,
               conn: Any = None) -> dict[str, dict[str, Any]]:
    """``{relpath: row}`` of one unit's files (its name compared as names are: case and
    Unicode form never matter)."""
    key = norm_name(unit)
    return {r["relpath"]: r for r in repo.files(account, space, plugin, folder.id, project_id=project_id, conn=conn)
            if norm_name(r["unit"]) == key}


def _dirty_here(account: str, space: str, plugin: str, folder: Folder, base: Path, unit: str,
                project_id: str) -> set[str]:
    """Bound-relative paths of the unit's files changed here (sent or not), on disk now. A
    file renamed in place (case or Unicode form only) is its row's file."""
    key = norm_name(unit)
    rows = _unit_rows(account, space, plugin, folder, unit, project_id)
    disk, _tmp = _disk_files(base, folder)
    disk = {rel: st for rel, st in disk.items() if norm_name(unit_of(folder, rel, project_id)) == key}
    moved = _renamed(rows, [_stored(rel, project_id) for rel in disk])
    out = {_bound_rel(p, project_id) for p, r in rows.items() if r["dirty"]}
    for rel, st in disk.items():
        stored = _stored(rel, project_id)
        row = rows.get(stored) or rows.get(moved.get(stored, ""))
        if row is None:
            out.add(rel)
        elif row["sync_state"] != "refetch" and (int(row["size"]) != st.st_size
                                                  or int(row["mtime_ns"]) != st.st_mtime_ns):
            if _sha_file(os.path.join(_lp(base), *rel.split("/"))) != row["base_sha"]:
                out.add(rel)
    renamed = set(moved.values())
    for stored, row in rows.items():
        rel = _bound_rel(stored, project_id)
        if rel not in disk and stored not in renamed and row["base_seq"] and not row["deleted"] \
                and row["sync_state"] != "refetch":
            out.add(rel)
    return out


def mergeable(folder: Folder, rel: str, size: int) -> bool:
    return bool(folder.merge) and size <= MERGE_MAX_BYTES and matches(folder.merge, _within_unit(folder, rel))


def _json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"))


def _sealed_base(account: str, folder: Folder, relpath: str, data: bytes) -> tuple[str, str] | None:
    """(sha256, sealed text) of ``data`` as a merge base, when the folder merges ``relpath``
    and it is valid JSON. Sealing may touch the database: never inside a transaction."""
    if not mergeable(folder, _strip_pid(folder, relpath), len(data)):
        return None
    try:
        _json(data)
    except ValueError:
        return None
    from backend.uefn_plugins.data_crypto import seal_text

    return hashlib.sha256(data).hexdigest(), seal_text(data.decode("utf-8-sig"), account)


def remember_base(account: str, space: str, plugin: str, folder: Folder, relpath: str, seq: int,
                  data: bytes) -> bool:
    """Keep ``data`` (sealed) as the merge base of ``relpath`` at ``seq`` when the folder
    merges it and it is valid JSON (after a commit of this PC's version). Returns whether
    it was kept."""
    sealed = _sealed_base(account, folder, relpath, data)
    if sealed is None:
        return False
    repo.base_put(None, account, space, plugin, folder.id, relpath, seq, *sealed)
    return True


def _strip_pid(folder: Folder, relpath: str) -> str:
    return relpath.split("/", 1)[1] if folder.project and "/" in relpath else relpath


def _base_json(account: str, space: str, plugin: str, folder: Folder, relpath: str, conn: Any) -> Any:
    from backend.uefn_plugins import json_merge
    from backend.uefn_plugins.data_crypto import open_text

    row = repo.base_get(account, space, plugin, folder.id, relpath, conn=conn)
    if not row or row["value"] is None:
        return json_merge.MISSING
    try:
        return json.loads(open_text(row["value"], account))
    except Exception:  # noqa: BLE001 — no base: every two-sided change is a conflict
        return json_merge.MISSING


def _encode_like(value: Any, sample: bytes) -> bytes:
    """Merged JSON written the way the plugin wrote it (indented or compact)."""
    indent = 2 if b"\n" in sample.strip() else None
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    return (text + ("\n" if sample.endswith(b"\n") else "")).encode("utf-8")


def _merge_overlap(account: str, space: str, plugin: str, folder: Folder, base: Path, items: list[Incoming],
                   dirty: set[str], project_id: str, conn: Any) -> tuple[dict[str, bytes], dict[str, str]] | None:
    """Files changed here and by the team, merged three ways: ``({relpath: merged bytes},
    {relpath: sha256 of mine as it was merged})``, or None when the unit is a conflict (no
    ``merge`` globs, a file that doesn't merge, or one real clash)."""
    from backend.uefn_plugins import json_merge

    changed = {norm_name(d) for d in dirty}
    overlap = {it.relpath for it in items if norm_name(it.relpath) in changed}
    if not folder.merge or not overlap:
        return None
    merged: dict[str, bytes] = {}
    mine: dict[str, str] = {}
    for it in items:
        if it.relpath not in overlap:
            continue
        target = os.path.join(_lp(base), *it.relpath.split("/"))
        if it.op != "put" or not os.path.isfile(target) or not mergeable(folder, it.relpath, it.size):
            return None
        try:
            mine_raw = read_bytes(target)
            if len(mine_raw) > MERGE_MAX_BYTES:
                return None
            result = json_merge.merge(
                _base_json(account, space, plugin, folder, _stored(it.relpath, project_id), conn),
                _json(Path(_lp(it.temp)).read_bytes()), _json(mine_raw))
        except (OSError, ValueError):
            return None
        if result.conflicts:
            return None
        merged[it.relpath] = _encode_like(result.value, mine_raw)
        mine[it.relpath] = hashlib.sha256(mine_raw).hexdigest()
    return merged, mine


class _Changed(Exception):
    """A file of the unit changed on disk after the unit was checked (a save just then)."""

    def __init__(self, relpath: str) -> None:
        super().__init__(relpath)
        self.relpath = relpath


def _set_aside(target: str, journal: list[tuple[str, str | None]],
               expect: Callable[[str], bool] | None = None, relpath: str = "") -> None:
    """Move the file at ``target`` to a backup beside it (journalled, so a failure puts it
    back). ``expect(backup)``: whether what moved aside is still what the unit was checked
    against; a file saved since raises :class:`_Changed` (and is put back with the rest)."""
    if os.path.lexists(target):
        if _readonly(target):
            set_readonly(target, False)
        backup = f"{target}{BAK_TAG}{uuid.uuid4().hex[:8]}.tmp"
        os.replace(target, backup)
        journal.append((target, backup))
        if expect is not None and not expect(backup):
            raise _Changed(relpath)
    else:
        journal.append((target, None))


def apply_unit(account: str, space: str, plugin: str, folder: Folder, unit: str, items: list[Incoming], *,
               seq: int, project_id: str = "", held: bool = False, force: bool = False) -> dict[str, Any]:
    """Apply one unit of a pulled change to a team copy: puts other than ``last`` globs,
    then ``last``, then deletes; each put is temp → ``os.replace`` → ``os.utime`` with the
    origin's exact ``mtime_ns``. A unit changed here is never overwritten: it answers
    ``conflict`` and nothing on disk changes (files a declaration merges and that are
    valid JSON merge three ways instead; one real clash keeps the whole unit back). A file
    saved here while the unit lands (after the check) is caught as it is moved aside: the
    unit goes back and is a conflict. A file already as theirs, or already gone where they
    deleted it, isn't a change here (an apply a crash cut short lands again). A file that
    fails puts every file of the unit back (``blocked``, its downloads gone: it is fetched
    again). One file has one row (another under a name that differs only in case or
    Unicode form goes). ``held``: the unit is someone else's (or has later changes
    waiting), so its files end read-only. ``force``: take theirs over changes here."""
    from backend.store import db

    base = team_copy(account, space, plugin, folder, project_id)
    conn = db.connect()
    dirty = _dirty_here(account, space, plugin, folder, base, unit, project_id)
    if dirty:
        by_name = {norm_name(d): d for d in dirty}
        for it in items:
            d = by_name.get(norm_name(it.relpath))
            if d is None:
                continue
            target = os.path.join(_lp(base), *it.relpath.split("/"))
            try:
                same = (it.op == "del" and not os.path.lexists(target)) or (
                    it.op == "put" and bool(it.sha256) and os.path.isfile(target) and _sha_file(target) == it.sha256)
            except OSError:
                same = False
            if same:
                dirty.discard(d)
    merged: dict[str, bytes] = {}
    mine_sha: dict[str, str] = {}
    if dirty and not force:
        got = _merge_overlap(account, space, plugin, folder, base, items, dirty, project_id, conn)
        if got is None:
            return _conflict(account, space, plugin, folder, unit, items, dirty, conn)
        merged, mine_sha = got
    puts = sorted((it for it in items if it.op == "put"), key=lambda it: it.relpath)
    order = [it for it in puts if not matches(folder.last, _within_unit(folder, it.relpath))]
    order += [it for it in puts if matches(folder.last, _within_unit(folder, it.relpath))]
    deletes = sorted((it for it in items if it.op == "del"), key=lambda it: it.relpath)
    bases: dict[str, tuple[str, str] | None] = {}  # the team's version of each merged file, sealed first
    for it in puts if folder.merge else ():
        try:
            bases[it.relpath] = _sealed_base(account, folder, _stored(it.relpath, project_id),
                                             Path(_lp(it.temp)).read_bytes())
        except OSError:
            bases[it.relpath] = None
    journal: list[tuple[str, str | None]] = []
    done: list[str] = []

    def unchanged(row: dict[str, Any] | None, rel: str, theirs: str = "") -> Callable[[str], bool] | None:
        """What a file moved aside must still be: mine as merged, else the version the
        unit was checked against (or theirs already)."""
        if force:
            return None
        if rel in merged:
            return lambda backup: _sha_file(backup) == mine_sha[rel]

        def check(backup: str) -> bool:
            if row is not None and row["sync_state"] == "refetch":
                return True
            st = os.stat(backup)
            if row is not None and not row["deleted"] and int(row["size"]) == st.st_size \
                    and int(row["mtime_ns"]) == st.st_mtime_ns:
                return True
            ok = {s for s in (theirs, "" if row is None or row["deleted"] else row["base_sha"]) if s}
            return _sha_file(backup) in ok

        return check

    try:
        with db.write_txn(conn):
            rows = _unit_rows(account, space, plugin, folder, unit, project_id, conn=conn)
            by_name: dict[str, set[str]] = {}
            by_key: dict[str, set[str]] = {}
            for p, r in rows.items():
                by_name.setdefault(norm_name(p), set()).add(p)
                if r["item_key"]:
                    by_key.setdefault(r["item_key"], set()).add(p)

            def row_of(stored: str) -> dict[str, Any] | None:
                return rows.get(stored) or next((rows[p] for p in sorted(by_name.get(norm_name(stored), ()))), None)

            def one_row(stored: str, key: str) -> None:
                """Rows of the same file under another name go (one key, one row)."""
                others = set(by_name.get(norm_name(stored), ())) | (by_key.get(key, set()) if key else set())
                for other in others - {stored}:
                    repo.file_delete(conn, account, space, plugin, folder.id, other)
                    repo.base_delete(conn, account, space, plugin, folder.id, other)

            for it in order:
                target = os.path.join(_lp(base), *it.relpath.split("/"))
                stored = _stored(it.relpath, project_id)
                _mkdirs(os.path.dirname(target))
                _set_aside(target, journal, unchanged(row_of(stored), it.relpath, it.sha256), it.relpath)
                one_row(stored, it.item_key)
                if it.relpath in merged:
                    # Theirs merged with mine: the team's file is the new base, the merge is a change here.
                    Path(_lp(it.temp)).write_bytes(merged[it.relpath])
                    os.replace(_lp(it.temp), target)
                    st = os.stat(target)
                    repo.file_put(conn, account, space, plugin, folder.id, stored, unit=unit, project_id=project_id,
                                  size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=_sha_file(target), base_seq=seq,
                                  base_sha=it.sha256, dirty=True, deleted=False, sync_state="", sync_error="",
                                  changed_at=time.time(), item_key=it.item_key, readonly=False)
                else:
                    os.replace(_lp(it.temp), target)
                    if it.mtime_ns:
                        os.utime(target, ns=(it.mtime_ns, it.mtime_ns))
                    st = os.stat(target)
                    repo.file_put(conn, account, space, plugin, folder.id, stored, unit=unit, project_id=project_id,
                                  size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=it.sha256, base_seq=seq,
                                  base_sha=it.sha256, dirty=False, deleted=False, sync_state="", sync_error="",
                                  changed_at=0.0, item_key=it.item_key, readonly=False)
                if bases.get(it.relpath):
                    repo.base_put(conn, account, space, plugin, folder.id, stored, seq, *bases[it.relpath])
                done.append(it.relpath)
            for it in deletes:
                target = os.path.join(_lp(base), *it.relpath.split("/"))
                stored = _stored(it.relpath, project_id)
                if os.path.lexists(target):
                    _set_aside(target, journal, unchanged(row_of(stored), it.relpath), it.relpath)
                one_row(stored, it.item_key)
                repo.file_delete(conn, account, space, plugin, folder.id, stored)
                repo.base_delete(conn, account, space, plugin, folder.id, stored)
                done.append(it.relpath)
            if force:
                # Take theirs: a file only this PC had in the unit goes; one the team has is fetched again.
                theirs = {norm_name(it.relpath) for it in items}
                for rel in sorted(d for d in dirty if norm_name(d) not in theirs):
                    target = os.path.join(_lp(base), *rel.split("/"))
                    stored = _stored(rel, project_id)
                    row = repo.file_get(account, space, plugin, folder.id, stored, conn=conn)
                    if os.path.lexists(target):
                        _set_aside(target, journal)
                    if row is not None and (row["base_seq"] or row["base_sha"]):
                        repo.file_put(conn, account, space, plugin, folder.id, stored, dirty=False, deleted=False,
                                      sync_state="refetch", sync_error="", sha256="", size=0, mtime_ns=0)
                    else:
                        repo.file_delete(conn, account, space, plugin, folder.id, stored)
                conn.execute("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? "
                             "AND plugin_id=? AND folder_id=? AND unit=? AND sync_state IN ('conflict', "
                             "'quarantined', 'locked_out')", (account, space, plugin, folder.id, unit))
    except BaseException as exc:
        for target, backup in reversed(journal):
            try:
                if os.path.lexists(target):
                    _unlink(target)
                if backup is not None:
                    os.replace(backup, target)
            except OSError:
                _log.warning("team folders: putting %s back failed", _plain(target), exc_info=True)
        for it in items:
            if it.temp and os.path.lexists(_lp(it.temp)):
                with contextlib.suppress(OSError):
                    _unlink(it.temp)
        if isinstance(exc, _Changed):
            return _conflict(account, space, plugin, folder, unit, items, dirty | {exc.relpath}, conn)
        if isinstance(exc, OSError):
            return {"ok": False, "state": "blocked", "unit": unit, "error": _io_reason(exc)}
        raise
    for _target, backup in journal:
        if backup is not None:
            with contextlib.suppress(OSError):
                _unlink(backup)
    for it in deletes:
        _prune_empty(base, it.relpath)
    if held:
        protect(account, space, plugin, folder, [unit], True, project_id=project_id)
    return {"ok": True, "state": "merged" if merged else "applied", "unit": unit, "files": done}


def _conflict(account: str, space: str, plugin: str, folder: Folder, unit: str, items: list[Incoming],
              dirty: set[str], conn: Any) -> dict[str, Any]:
    """The unit changed here and by the team: held, nothing on disk changed."""
    from backend.store import db

    with db.write_txn(conn):
        # Every file of the unit, so a change the scan hasn't seen yet is held with it.
        repo.unit_set_state(account, space, plugin, folder.id, unit, "conflict", "Changed here and by the team",
                            dirty_only=False, conn=conn)
    return {"ok": False, "state": "conflict", "unit": unit, "mine": sorted(dirty), "theirs": [it.relpath for it in items]}


def _io_reason(exc: OSError) -> str:
    if _in_use(exc):
        return "A file is in use or read-only on this PC. It is tried again."
    if getattr(exc, "winerror", 0) == 112 or getattr(exc, "errno", 0) == 28:
        return "The disk is full."
    return str(exc)


def _prune_empty(base: Path, rel: str) -> None:
    parts = rel.split("/")[:-1]
    while parts:
        d = os.path.join(_lp(base), *parts)
        try:
            os.rmdir(d)
        except OSError:
            return
        parts.pop()


# --------------------------------------------------------------------------- read-only units


def protect(account: str, space: str, plugin: str, folder: Folder, units: Iterable[str], on: bool, *,
            project_id: str = "") -> int:
    """Files of these units read-only (``on``) or writable again. Only files core made
    read-only are made writable. The row always says read-only first: it is written before
    the attribute is set and after it is cleared, so a failure between the two never leaves
    a read-only file core doesn't know about. Returns how many files changed."""
    from backend.store import db

    base = team_copy(account, space, plugin, folder, project_id)
    todo: list[tuple[str, str]] = []
    for unit in set(units):
        for row in repo.files(account, space, plugin, folder.id, unit=unit):
            if row["deleted"] or (not on and not row["readonly"]):
                continue
            path = os.path.join(_lp(base), *_bound_rel(row["relpath"], project_id).split("/"))
            if os.path.isfile(path) and not (bool(row["readonly"]) == on and _readonly(path) == on):
                todo.append((row["relpath"], path))
    if not todo:
        return 0
    conn = db.connect()
    if on:
        with db.write_txn(conn):
            for rel, _path in todo:
                repo.file_put(conn, account, space, plugin, folder.id, rel, readonly=True)
    changed: list[str] = []
    for rel, path in todo:
        try:
            set_readonly(path, on)
            changed.append(rel)
        except OSError:
            continue
    if not on and changed:
        with db.write_txn(conn):
            for rel in changed:
                repo.file_put(conn, account, space, plugin, folder.id, rel, readonly=False)
    return len(changed)


def refresh_readonly(account: str, space: str, plugin: str, folder: Folder, *, project_id: str = "",
                     unit_id: Callable[[str], str] | None = None, incoming: Iterable[str] = ()) -> dict[str, list[str]]:
    """Read-only exactly where it should be: units someone else holds (unless the folder
    quarantines instead) and units with changes not applied here yet; writable everywhere
    else core had made read-only."""
    rows = repo.files(account, space, plugin, folder.id, project_id=project_id)
    units = {r["unit"] for r in rows}
    want = set(incoming) & units
    if folder.on_locked == "readonly":
        want |= set(_foreign_units(account, space, plugin, units, unit_id))
    now_ro = {r["unit"] for r in rows if r["readonly"]}
    protect(account, space, plugin, folder, want, True, project_id=project_id)
    protect(account, space, plugin, folder, now_ro - want, False, project_id=project_id)
    return {"readonly": sorted(want), "writable": sorted(now_ro - want)}


def quarantined(account: str, space: str, plugin: str) -> list[dict[str, Any]]:
    """Units changed here while someone else holds them: never sent; the bar offers Keep mine
    as a copy or Discard mine."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for (fid, unit), info in repo.dirty_units(account, space, plugin).items():
        if "quarantined" in info["states"]:
            rows = repo.files(account, space, plugin, fid, unit=unit)
            why = next((r["sync_error"] for r in rows if r["sync_state"] == "quarantined"), "")
            out[(fid, unit)] = {"folder": fid, "unit": unit, "files": info["files"], "reason": why}
    return list(out.values())


# --------------------------------------------------------------------------- choices


def _copy_name(name: str, holder: str, *, is_file: bool, n: int = 1) -> str:
    who = (f"{holder}'s copy" if holder else "my copy") + (f" {n}" if n > 1 else "")
    if is_file:
        stem, dot, ext = name.rpartition(".")
        return f"{stem} ({who}).{ext}" if dot and stem else f"{name} ({who})"
    return f"{name} ({who})"


def keep_mine_as_copy(account: str, space: str, plugin: str, folder: Folder, unit: str, *, project_id: str = "",
                      holder: str = "") -> dict[str, Any]:
    """Keep mine as a copy: the unit as it is here is copied beside it as
    ``<unit> (<name>'s copy)`` (a whole-folder unit goes to the copy's ``conflicts/``
    folder), then the original goes back to the team's version (:func:`discard_mine`)."""
    base = team_copy(account, space, plugin, folder, project_id)
    local = _unit_local(unit, project_id)
    is_file = folder.unit == "file" or (local and os.path.isfile(os.path.join(_lp(base), *local.split("/"))))
    if local:
        src = Path(os.path.join(_plain(base), *local.split("/")))
        parent, leaf = src.parent, src.name
    else:
        src = Path(_plain(base))
        from backend.uefn_plugins import scopes

        parent = scopes.plugin_dir({"account": account, "id": space}, plugin) / "conflicts" / folder.id
        leaf = project_id or folder.id
    n = 1
    dest = parent / _copy_name(leaf, holder, is_file=bool(is_file))
    while _exists(dest):
        n += 1
        dest = parent / _copy_name(leaf, holder, is_file=bool(is_file), n=n)
    if is_file:
        _copy_verified(src, dest)
        set_readonly(dest, False)
    else:
        for rel, entry in _walk_files(src):
            in_root = f"{local}/{rel}" if local else rel
            if matches(folder.ignore, in_root) or norm_name(entry.name).endswith(".tmp"):
                continue
            target = os.path.join(_lp(dest), *rel.split("/"))
            _copy_verified(entry.path, target)
            set_readonly(target, False)
    out = discard_mine(account, space, plugin, folder, unit, project_id=project_id)
    return {**out, "copy": str(dest)}


def save_unit_to_local(account: str, space: str, plugin: str, folder: Folder, unit: str, label: str, *,
                       project_id: str = "") -> str:
    """A unit of a team's copy changed here and never sent is copied into the Local copy
    (access to the team is gone, and its copy will go): under its own name when Local has
    none there, else ``<name> (from <team>)``. A whole-folder unit's files go in one by
    one, a file Local has with other content as ``<stem> (from <team>).<ext>``. Returns
    where it went ('' when there was nothing to copy)."""
    src_base = team_copy(account, space, plugin, folder, project_id)
    dst_base = local_copy(plugin, folder, project_id)
    tag = f"from {label}" if label else "from the team"
    local = _unit_local(unit, project_id)

    def wanted(rel: str, name: str) -> bool:
        return not (matches(folder.ignore, rel) or norm_name(name).endswith(".tmp"))

    if local:
        src = os.path.join(_lp(src_base), *local.split("/"))
        if not os.path.lexists(src):
            return ""
        dest = os.path.join(_lp(dst_base), *local.split("/"))
        if os.path.lexists(dest):
            dest = _free_name(dest, tag)
        if os.path.isfile(src):
            _copy_verified(src, dest)
            set_readonly(dest, False)
            return _plain(dest)
        copied = 0
        for rel, entry in _walk_files(Path(_plain(src))):
            if wanted(f"{local}/{rel}", entry.name):
                target = os.path.join(dest, *rel.split("/"))
                _copy_verified(entry.path, target)
                set_readonly(target, False)
                copied += 1
        return _plain(dest) if copied else ""
    copied = 0
    for rel, entry in _walk_files(src_base) if os.path.isdir(_lp(src_base)) else ():
        if not wanted(rel, entry.name):
            continue
        target = os.path.join(_lp(dst_base), *rel.split("/"))
        if os.path.lexists(target):
            if _same_content(entry.path, target):
                continue
            target = _free_name(target, tag)
        _copy_verified(entry.path, target)
        set_readonly(target, False)
        copied += 1
    return _plain(dst_base) if copied else ""


def discard_mine(account: str, space: str, plugin: str, folder: Folder, unit: str, *,
                 project_id: str = "") -> dict[str, Any]:
    """Discard mine: the unit's files changed here go; files the team has are fetched again
    at its head (``refetch``), files only this PC had are dropped."""
    from backend.store import db

    base = team_copy(account, space, plugin, folder, project_id)
    dirty = _dirty_here(account, space, plugin, folder, base, unit, project_id)
    refetch: list[str] = []
    dropped: list[str] = []
    conn = db.connect()
    with db.write_txn(conn):
        for rel in sorted(dirty):
            stored = _stored(rel, project_id)
            row = repo.file_get(account, space, plugin, folder.id, stored, conn=conn)
            target = os.path.join(_lp(base), *rel.split("/"))
            if os.path.lexists(target):
                _unlink(target)
            if row is not None and (row["base_seq"] or row["base_sha"]):
                repo.file_put(conn, account, space, plugin, folder.id, stored, dirty=False, deleted=False,
                              sync_state="refetch", sync_error="", sha256="", size=0, mtime_ns=0, readonly=False)
                refetch.append(rel)
            else:
                repo.file_delete(conn, account, space, plugin, folder.id, stored)
                dropped.append(rel)
        conn.execute("UPDATE folder_files SET sync_state='', sync_error='' WHERE account_id=? AND space_id=? AND "
                     "plugin_id=? AND folder_id=? AND unit=? AND sync_state IN ('quarantined', 'conflict', "
                     "'locked_out')", (account, space, plugin, folder.id, unit))
    for rel in dropped:
        _prune_empty(base, rel)
    return {"ok": True, "refetch": refetch, "dropped": dropped}


def refetch_items(account: str, space: str, plugin: str) -> list[dict[str, Any]]:
    """Files waiting to be fetched again at the team's head (after Discard mine)."""
    from backend.store import db

    out = db.connect().execute(
        "SELECT folder_id, relpath, unit, item_key, base_seq FROM folder_files WHERE account_id=? AND space_id=? AND "
        "plugin_id=? AND sync_state='refetch' ORDER BY folder_id, relpath", (account, space, plugin)).fetchall()
    return [{k: r[k] for k in r.keys()} for r in out]


def copy_local_into(plugin: str, folder: Folder, account: str, space: str, units: Iterable[str],
                    project_id: str = "") -> dict[str, Any]:
    """Copy these Local units into the team's copy (with their mtimes). A unit the team copy
    already has is kept as it is. The next scan sends them."""
    src_base = local_copy(plugin, folder, project_id)
    dst_base = team_copy(account, space, plugin, folder, project_id)
    files, _tmp = _disk_files(src_base, folder)
    have, _ = _disk_files(dst_base, folder)
    have_units = {unit_of(folder, rel, project_id) for rel in have}
    wanted = set(units)
    copied = kept = size = 0
    for unit in sorted(wanted & have_units):
        kept += 1
    for rel, st in sorted(files.items()):
        unit = unit_of(folder, rel, project_id)
        if unit not in wanted or unit in have_units:
            continue
        target = os.path.join(_lp(dst_base), *rel.split("/"))
        _copy_verified(os.path.join(_lp(src_base), *rel.split("/")), target)
        if _readonly(target):
            set_readonly(target, False)
        copied += 1
        size += int(st.st_size)
    if copied:
        repo.copy_put(account, space, plugin, folder.id, project_id, offer=0)
    return {"ok": True, "copied": copied, "kept": kept, "bytes": size}


# --------------------------------------------------------------------------- erase


def purge_space(account: str, space: str) -> int:
    """A space's copy on this PC goes: junctions pointing into it go back to Local first
    (never left dangling), then its folder copies (read-only files too; links inside are
    removed, never followed) and their rows. Returns how many junctions moved."""
    from backend.uefn_plugins import scopes

    base = scopes.scopes_root(account) / space
    moved = 0
    for lk in repo.links():
        if not (lk["account_id"] == account and lk["space_id"] == space) and not _inside(lk["target"], base):
            continue
        local = local_copy(lk["plugin_id"], lk["folder_id"], lk["project_id"])
        try:
            _repoint(lk["plugin_id"], [(Path(lk["root"]), local)], wait_s=2.0, must=True, why="purge")
            repo.link_put(lk["plugin_id"], lk["folder_id"], lk["project_id"], root=lk["root"], target=str(local),
                          account=LOCAL_ACCOUNT, space=PERSONAL)
            moved += 1
        except (FolderError, OSError):
            _log.warning("team folders: moving %s back to Local failed", lk["root"], exc_info=True)
    for plugin_dir in _entries(base):
        if plugin_dir.is_dir(follow_symlinks=False) and not plugin_dir.is_junction():
            remove_tree(os.path.join(plugin_dir.path, "folders"))
    repo.forget_files(account, space)
    return moved


def clear_space(account: str, space: str) -> list[str]:
    """Clear my copy, after the space's data was reset on the server: this PC's files of the
    space go (read-only ones too; links inside are removed, never followed), while the
    folder copies plugins' junctions point at stay, empty, so no plugin's folder dangles
    and the next pull fills them again (the rows went with the reset). It happens once the
    plugins' calls are done. Returns the plugins whose folders were emptied (they reload)."""
    from backend.uefn_plugins import scopes

    base = scopes.scopes_root(account) / space
    targets = [lk for lk in repo.links() if lk["target"] and _inside(lk["target"], base)]
    plugins = sorted({lk["plugin_id"] for lk in targets})
    with contextlib.ExitStack() as stack:
        for plugin in plugins:
            stack.enter_context(_fence(plugin, 5.0, True))
        if not remove_tree(base):
            _log.warning("team folders: some files of %s couldn't be deleted", space)
        for lk in targets:
            _mkdirs(lk["target"])
        for plugin in plugins:
            repo.reload_bump(plugin, "reset")
    return plugins


def erase_plugin(account: str, plugin: str) -> dict[str, Any]:
    """Uninstall + erase: the plugin's junctions go (``os.rmdir`` on each), its Local copy
    goes back to where the plugin keeps its folder (it belongs to this PC, every account),
    and this account's team copies of it and their rows go. Another account's copies, and
    any copy another scope still points at, stay."""
    from backend.uefn_plugins import scopes

    junctions = restored = 0
    for lk in repo.links(plugin):
        root = Path(lk["root"])
        if _is_junction(root):
            _quiesce(plugin, 2.0, True)
            os.rmdir(_lp(root))
            junctions += 1
        local = local_copy(plugin, lk["folder_id"], lk["project_id"])
        if os.path.isdir(_lp(local)) and not _exists(root):
            try:
                _move_dir(local, root)
                restored += 1
            except (FolderError, OSError):
                _log.warning("team folders: putting %s back failed; it stays in %s", root, local, exc_info=True)
        repo.link_delete(plugin, lk["folder_id"], lk["project_id"])
    _prune_empty_tree(app_root() / "scopes" / LOCAL_ACCOUNT / plugin)
    root = scopes.scopes_root(account)
    for scope_dir in _entries(root):
        if scope_dir.is_dir(follow_symlinks=False) and not scope_dir.is_junction():
            remove_tree(os.path.join(scope_dir.path, plugin, "folders"))
    repo.forget_plugin(account, plugin)
    if junctions:
        repo.reload_bump(plugin, "erase")
    return {"ok": True, "junctions": junctions, "restored": restored}


def _prune_empty_tree(path: Path) -> None:
    """Remove empty folders under ``path`` (and it, once empty)."""
    p = _lp(path)
    if not os.path.isdir(p) or _is_junction(p):
        return
    for e in _entries(p):
        if e.is_dir(follow_symlinks=False) and not e.is_junction():
            _prune_empty_tree(Path(_plain(e.path)))
    try:
        os.rmdir(p)
    except OSError:
        pass


# --------------------------------------------------------------------------- server names + status


def _fallback_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def tree_key(backend: Any, space: str, folder_id: str, unit: str, relpath: str) -> str:
    """A folder file's item key: ``tree:<folder>/<h32>`` from the backend (names hashed with
    the team's key), over the normalised unit and path (case and Unicode form never make
    two keys for one file)."""
    u, r = norm_name(unit), norm_name(relpath)
    fn = getattr(backend, "tree_key", None)
    if callable(fn):
        return str(fn(space, folder_id, u, r))
    return f"tree:{folder_id}/{_fallback_key(f'{u}/{r}')}"


def tree_unit(backend: Any, space: str, folder_id: str, unit: str) -> str:
    """A folder unit's id, as locks and presence name it."""
    u = norm_name(unit)
    fn = getattr(backend, "tree_unit", None)
    if callable(fn):
        return str(fn(space, folder_id, u))
    return f"tree:{folder_id}/{_fallback_key(f'{folder_id}/{u}')}"


def unit_ids(backend: Any, space: str, folder_id: str) -> Callable[[str], str]:
    return functools.lru_cache(maxsize=4096)(lambda unit: tree_unit(backend, space, folder_id, unit))


def units_table(account: str, space: str, plugin: str, folder: Folder, *, project_id: str = "",
                unit_id: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """The drawer's folder units: each unit's state (``synced``, ``changed``, ``locked`` by
    someone, ``conflict``, ``quarantined``, ``refused``), files and bytes."""
    rows = repo.files(account, space, plugin, folder.id, project_id=project_id)
    units: dict[str, dict[str, Any]] = {}
    for r in rows:
        u = units.setdefault(r["unit"], {"unit": r["unit"], "name": _unit_local(r["unit"], project_id) or folder.id,
                                         "files": 0, "bytes": 0, "states": set(), "dirty": 0, "reason": ""})
        if not r["deleted"]:
            u["files"] += 1
            u["bytes"] += int(r["size"])
        u["dirty"] += int(r["dirty"])
        if r["sync_state"]:
            u["states"].add(r["sync_state"])
            u["reason"] = u["reason"] or r["sync_error"]
    locked = _foreign_units(account, space, plugin, units, unit_id)
    out: list[dict[str, Any]] = []
    for unit, u in sorted(units.items(), key=lambda kv: norm_name(kv[0])):
        states = u.pop("states")
        state = next((s for s in ("conflict", "quarantined", "refused") if s in states), "")
        if not state and unit in locked:
            state = "locked"
            try:
                from backend.uefn_plugins.vcs_engine import holder_of

                u["holder"], u["elsewhere"] = holder_of(account, space, locked[unit])
            except Exception:  # noqa: BLE001
                u["holder"] = person(locked[unit].get("holder_name"), locked[unit].get("holder_user"))
        state = state or ("changed" if u["dirty"] else "synced")
        out.append({**u, "state": state})
    return out


def status(plugin: str, *, project_root: str | None = None) -> dict[str, Any]:
    """Each declared folder for the bar: where it points, why it can't be shared (if so),
    and the plaintext note."""
    out: list[dict[str, Any]] = []
    for b in resolve(plugin, project_root=project_root):
        link = repo.link_get(plugin, b.folder.id, b.project_id) if b.root is not None else None
        out.append({"id": b.folder.id, "root": str(b.root) if b.root else "", "projectId": b.project_id,
                    "refused": b.refused, "adopted": _adopted(plugin, b) if b.root else False,
                    "bound": (link or {}).get("space_id", ""), "afterPull": b.folder.after_pull})
    return {"folders": out, "offers": offers(plugin), "note": PLAINTEXT_NOTE}
