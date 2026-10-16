"""Check what makes skills and tools findable by skill and tool search.

Same rules as ``ducky_plugin_validate`` (``backend.uefn_plugins.plugin_lint``): every
skill file needs a one-line ``description:`` (error); descriptions under 40 characters
and tool docstrings whose first line is under 30 are warnings.

Usage::

    python scripts/check_findability.py <plugin folder> [<plugin folder> ...]
    python scripts/check_findability.py --core        # UEFN Ducky's own skill packs and tools
    python scripts/check_findability.py --installed   # every plugin installed on this PC (read-only)

Exit code 1 when any error is found.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ducky_app"))

from backend.uefn_plugins.plugin_lint import (  # noqa: E402
    check_findability,
    skill_description_issues,
    tool_docstring_issues,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="*", type=Path)
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--installed", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="counts only")
    args = ap.parse_args()

    targets: list[tuple[str, tuple[list[str], list[str]]]] = []
    if args.core:
        app = ROOT / "ducky_app"
        errors, warnings = skill_description_issues(app / "frontend" / "skill_packs", app)
        targets.append(("UEFN Ducky (core)", (errors, warnings + tool_docstring_issues(app))))
    folders = list(args.folders)
    if args.installed:
        plugins = Path(os.environ.get("LOCALAPPDATA", "")) / "UEFN-Ducky" / "uefn_plugins"
        folders += sorted(p for p in plugins.iterdir() if p.is_dir() and (p / "plugin.json").is_file())
    for folder in folders:
        targets.append((folder.name, check_findability(folder)))

    total_errors = 0
    for name, (errors, warnings) in targets:
        total_errors += len(errors)
        print(f"{name}: {len(errors)} errors, {len(warnings)} warnings")
        if not args.quiet:
            for line in errors:
                print(f"  ERROR {line}")
            for line in warnings:
                print(f"  warn  {line}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
