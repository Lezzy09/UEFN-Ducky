"""Programs run in a Ducky terminal find the ffmpeg the app bundles."""

from __future__ import annotations

import os
from pathlib import Path


def test_terminals_get_duckys_ffmpeg_after_the_persons_own(monkeypatch, tmp_path) -> None:
    # Oct 12 2026: a plugin's tests ran in a terminal, outside the app, and could not find the
    # bundled encoder, so no builder could make its test export.
    from frontend.ui_web.terminal import path_env

    ffmpeg, ffprobe = tmp_path / "ffmpeg.exe", tmp_path / "ffprobe.exe"
    monkeypatch.setattr("backend.agent.video.ffmpeg_install.binaries", lambda: (ffmpeg, ffprobe))
    monkeypatch.setattr(path_env, "windows_merged_path", lambda: os.pathsep.join(["C:/mine/bin", "C:/Windows"]))
    env = path_env.env_with_fresh_path({})
    assert env["DUCKY_FFMPEG"] == str(ffmpeg) and env["DUCKY_FFPROBE"] == str(ffprobe)
    parts = env["PATH"].split(os.pathsep)
    assert parts[-1] == str(tmp_path) and parts[0] == "C:/mine/bin"  # the person's own ffmpeg wins
    assert env_twice(path_env).count(str(tmp_path)) == 1


def env_twice(path_env) -> str:
    return path_env.env_with_fresh_path(path_env.env_with_fresh_path({}))["PATH"]


def test_no_ffmpeg_no_change(monkeypatch) -> None:
    from frontend.ui_web.terminal import path_env

    monkeypatch.setattr("backend.agent.video.ffmpeg_install.binaries", lambda: None)
    monkeypatch.setattr(path_env, "windows_merged_path", lambda: "C:/Windows")
    env = path_env.env_with_fresh_path({})
    assert "DUCKY_FFMPEG" not in env and env["PATH"] == "C:/Windows"
