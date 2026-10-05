from __future__ import annotations

from backend.agent.video.limits import clamp, video_limits
from frontend.settings import PanelSettings


def test_defaults_when_unset():
    lim = video_limits()
    assert lim.max_bytes == 100 * 1024 * 1024
    assert lim.frames_per_video == 20
    assert lim.max_images_per_message == 40


def test_values_are_read_from_settings_and_clamped():
    s = PanelSettings.load()
    s.video_max_mb = 999
    s.video_frames_per_video = 0
    s.max_images_per_message = 60
    s.save()
    lim = video_limits()
    assert lim.max_bytes == 200 * 1024 * 1024
    assert lim.frames_per_video == 1
    assert lim.max_images_per_message == 60


def test_clamp_bad_input_falls_back_to_default():
    assert clamp("nope", 1, 40, 20) == 20
    assert clamp(None, 1, 40, 20) == 20
    assert clamp("7", 1, 40, 20) == 7
