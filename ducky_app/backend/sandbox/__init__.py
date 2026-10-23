"""Sandbox: a private workspace per chat where an agent downloads, installs, builds, runs
and studies programs (test copies of Ducky included) without touching the person's
projects or their real Windows profile.

Layout under ``%LOCALAPPDATA%/UEFN-Ducky/sandboxes/<chat id>/``: ``work`` (clones,
worktrees, builds), ``downloads``, ``logs`` (each launched program's output, capped),
``home`` + ``appdata/Local`` + ``appdata/Roaming`` + ``temp`` (the programs' own profile
folders), and ``manifest.json`` (what came in, what ran, what was seen). Shared portable
runtimes live in ``%LOCALAPPDATA%/UEFN-Ducky/tools/sandbox``.

Processes run in the Ducky window's process inside a Windows Job Object: stopping one
ends its whole tree, and closing Ducky ends every sandbox program with it, so nothing is
left running. Tools called from an agent's tool server hand the work to the window.
"""
