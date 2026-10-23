"""The environment every sandbox program starts with: its own profile folders and caches."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from backend.sandbox import paths


def tool_bins() -> list[str]:
    """Bin folders of the portable runtimes set up so far (shared by every sandbox)."""
    base = paths.tools_root()
    out: list[str] = []
    if not base.is_dir():
        return out
    for exe in sorted((base / "uv-python").glob("cpython-*/python.exe"), reverse=True)[:1]:
        out += [str(exe.parent), str(exe.parent / "Scripts")]
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.endswith(".part") or child.name == "uv-python":
            continue
        for sub in ("", "bin", "cmd", "Scripts", "mingw64/bin", "usr/bin"):
            folder = child / sub if sub else child
            if folder.is_dir() and any(
                (folder / name).is_file()
                for name in ("node.exe", "uv.exe", "python.exe", "git.exe", "npm.cmd")
            ):
                out.append(str(folder))
    return out


def sandbox_env(sandbox: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ with every profile and cache folder pointed into ``sandbox``.

    Programs that read %USERPROFILE%, %APPDATA%, %LOCALAPPDATA% or %TEMP% (installers,
    pip, npm, Ducky itself) write there instead of the person's real profile."""
    env = dict(os.environ)
    home = str(sandbox / "home")
    local = str(sandbox / "appdata" / "Local")
    roaming = str(sandbox / "appdata" / "Roaming")
    temp = str(sandbox / "temp")
    env.update({
        "USERPROFILE": home,
        "HOME": home,
        "APPDATA": roaming,
        "LOCALAPPDATA": local,
        "TEMP": temp,
        "TMP": temp,
        "PIP_CACHE_DIR": str(sandbox / "appdata" / "Local" / "pip-cache"),
        "PYTHONUSERBASE": str(sandbox / "home" / ".python"),
        "UV_CACHE_DIR": str(sandbox / "appdata" / "Local" / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(paths.tools_root() / "uv-python"),
        "npm_config_cache": str(sandbox / "appdata" / "Local" / "npm-cache"),
        "npm_config_prefix": str(sandbox / "appdata" / "Roaming" / "npm"),
        "CARGO_HOME": str(sandbox / "home" / ".cargo"),
        "GOPATH": str(sandbox / "home" / "go"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "DUCKY_SANDBOX": str(sandbox),
        # A Ducky started in here must never update itself, re-point IDE configs or
        # install CLIs into the person's PATH.
        "DUCKY_SKIP_CLI_UPDATE": "1",
    })
    # Anything an IDE or this Ducky put in the environment for its own MCP bridge would
    # point a program in here at the person's real app: drop it.
    for key in ("UEFN_DUCKY_SHARED_MCP", "DUCKY_CONV_ID", "DUCKY_RUN_ID", "UEFN_DUCKY_MCP_BRIDGE"):
        env.pop(key, None)
    bins = tool_bins()
    if bins:
        env["PATH"] = os.pathsep.join([*bins, env.get("PATH", "")])
    for key, value in (extra or {}).items():
        if key and isinstance(value, str):
            env[str(key)] = value
    return env


def free_port() -> int:
    """A TCP port nothing listens on right now (127.0.0.1)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
