from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.agent.video import encoder, ffmpeg_install

_HEAD = " Encoders:\n V..... = Video\n ------\n"


def _listing(*names: str) -> str:
    return _HEAD + "".join(f" V....D {n:<18} fake {n}\n" for n in names)


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """state["out"] is the -encoders listing; encoders in state["fail"] fail their trial."""
    encoder.reset_cache()
    runs: list[list[str]] = []
    state = {"out": "", "fail": set()}

    monkeypatch.setattr(
        ffmpeg_install, "ensure_installed", lambda: (Path("ffmpeg.exe"), Path("ffprobe.exe"))
    )

    def fake_run(cmd, **kw):
        runs.append(cmd)
        if "-encoders" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=state["out"], stderr="")
        enc = cmd[cmd.index("-c:v") + 1]
        return subprocess.CompletedProcess(cmd, 1 if enc in state["fail"] else 0, "", "")

    monkeypatch.setattr(encoder.subprocess, "run", fake_run)
    yield state, runs
    encoder.reset_cache()


def test_nvenc_wins_over_the_rest(fake_ffmpeg):
    state, _ = fake_ffmpeg
    state["out"] = _listing("libx264", "h264_qsv", "h264_amf", "h264_nvenc")
    assert encoder.pick_encoder() == "h264_nvenc"


def test_amf_then_qsv_order(fake_ffmpeg):
    state, _ = fake_ffmpeg
    state["out"] = _listing("h264_qsv", "h264_amf")
    assert encoder.pick_encoder() == "h264_amf"
    encoder.reset_cache()
    state["out"] = _listing("h264_qsv")
    assert encoder.pick_encoder() == "h264_qsv"


def test_listed_nvenc_whose_trial_fails_moves_on(fake_ffmpeg):
    state, runs = fake_ffmpeg
    state["out"] = _listing("h264_nvenc", "h264_amf", "libx264")
    state["fail"] = {"h264_nvenc"}
    assert encoder.pick_encoder() == "h264_amf"
    trial = runs[1]
    assert trial[trial.index("-i") + 1] == "color=s=64x64:d=0.04"
    assert trial[-3:] == ["-f", "null", "-"]


def test_no_libx264_picks_libopenh264(fake_ffmpeg):
    state, _ = fake_ffmpeg
    state["out"] = _listing("h264_nvenc", "h264_qsv", "libopenh264", "mpeg4")
    state["fail"] = {"h264_nvenc", "h264_qsv"}
    assert encoder.pick_encoder() == "libopenh264"


def test_libx264_before_libopenh264(fake_ffmpeg):
    state, _ = fake_ffmpeg
    state["out"] = _listing("libopenh264", "libx264")
    assert encoder.pick_encoder() == "libx264"


def test_nothing_works_falls_back_to_libopenh264(fake_ffmpeg):
    state, _ = fake_ffmpeg
    state["out"] = _listing("mpeg4", "libvpx")
    assert encoder.pick_encoder() == "libopenh264"


def test_probe_runs_once(fake_ffmpeg):
    state, runs = fake_ffmpeg
    state["out"] = _listing("h264_nvenc")
    encoder.pick_encoder()
    encoder.pick_encoder()
    assert len(runs) == 2
    assert "-encoders" in runs[0]
