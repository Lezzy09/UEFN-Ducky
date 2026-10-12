"""Find personal paths (a user's home folder) in a plugin's files before they ship.

A plugin built by an agent team held twenty files with the builder's own home folder in
them (evidence, check scripts, a measurement file): a published plugin would hand every
user the author's account name and folder layout.
"""

from __future__ import annotations

import re
from pathlib import Path

# A home folder with a real name in it: C:\Users\<name>, C:/Users/<name>, /Users/<name>,
# /home/<name>. Placeholders (<name>, {user}, %USERNAME%, $HOME) and shared profiles are fine.
_PERSONAL_RE = re.compile(
    r"(?i)(?:\b[a-z]:(?:\\\\|\\|/)+users(?:\\\\|\\|/)+|(?<![\w.])/(?:users|home)/)"
    r"(?![<{%$]|public\b|default\b|all users\b|shared\b)([a-z0-9._ -]{2,64})"
)
_TEXT_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".md", ".txt", ".css", ".html", ".htm",
    ".verse", ".yaml", ".yml", ".toml", ".csv", ".ini", ".cfg", ".xml", ".svg",
})
_MAX_BYTES = 32 * 1024 * 1024
_VENDOR_DIRS = frozenset({"vendor", "node_modules", "third_party"})


def personal_paths_in(text: str) -> list[str]:
    """The personal paths in ``text`` (each once, in order)."""
    seen: list[str] = []
    for match in _PERSONAL_RE.finditer(text or ""):
        hit = match.group(0)
        if hit not in seen:
            seen.append(hit)
    return seen


def find_personal_paths(root: Path, files: list[Path]) -> list[dict[str, object]]:
    """``files`` (inside ``root``) that hold a personal path: path, line and the path found."""
    found: list[dict[str, object]] = []
    for path in files:
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if _VENDOR_DIRS.intersection(part.lower() for part in path.relative_to(root).parts):
            continue  # third-party code (Emscripten's virtual /home/web_user is not a person)
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _PERSONAL_RE.search(text)
        if match is None:
            continue
        found.append({
            "path": path.relative_to(root).as_posix(),
            "line": text.count("\n", 0, match.start()) + 1,
            "found": match.group(0),
        })
    return found


def personal_path_message(found: list[dict[str, object]], *, limit: int = 8) -> str:
    rows = ", ".join(f"{f['path']}:{f['line']}" for f in found[:limit])
    more = f" and {len(found) - limit} more" if len(found) > limit else ""
    return (f"{len(found)} file(s) hold a personal path (a user's home folder): {rows}{more}. "
            "Use a path relative to the plugin, an environment variable, or the plugin API's "
            "folders; move development evidence under tests/ (it never ships).")
