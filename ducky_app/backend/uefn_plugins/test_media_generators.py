import pytest

from backend.uefn_plugins import host


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(host, "_MEDIA_GENERATORS", {})
    monkeypatch.setattr(host, "is_plugin_enabled", lambda pid: True)


def _keys(monkeypatch, saved: dict):
    monkeypatch.setattr("backend.agent.secrets.get_key", lambda name: saved.get(name))


def test_fake_video_generator_listed_with_key_hidden_without(monkeypatch):
    fake = lambda prompt, **o: {"path": "x.mp4", "mime": "video/mp4"}  # noqa: E731
    host.register_media_generator("fakevid", "video", fake, {"label": "Fake", "secret_key": "fakevid_key"})

    _keys(monkeypatch, {})
    assert host.media_generators("video") == []

    _keys(monkeypatch, {"fakevid_key": "  "})
    assert host.media_generators("video") == []

    _keys(monkeypatch, {"fakevid_key": "sk-1"})
    rows = host.media_generators("video")
    assert [r["plugin_id"] for r in rows] == ["fakevid"]
    assert rows[0]["label"] == "Fake" and rows[0]["fn"] is fake
    assert host.media_generators("image") == []


def test_keyless_listed_and_bad_input_rejected(monkeypatch):
    _keys(monkeypatch, {})
    host.register_media_generator("freemusic", "music", lambda p, **o: {}, {"label": "Free"})
    assert len(host.media_generators("music")) == 1
    with pytest.raises(ValueError):
        host.register_media_generator("freemusic", "audio", lambda p, **o: {})
    with pytest.raises(TypeError):
        host.register_media_generator("freemusic", "video", "nope")


def test_disabled_plugin_hidden(monkeypatch):
    _keys(monkeypatch, {})
    host.register_media_generator("fakevid", "video", lambda p, **o: {})
    monkeypatch.setattr(host, "is_plugin_enabled", lambda pid: False)
    assert host.media_generators("video") == []
