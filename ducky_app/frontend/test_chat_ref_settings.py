"""Composer mention toggles stay on when an older settings file omits them."""

from __future__ import annotations

from frontend.settings import PanelSettings


def test_chat_ref_toggles_default_on_when_the_key_is_absent() -> None:
    settings = PanelSettings.from_json_dict({})
    assert settings.chat_mentions_enabled is True
    assert settings.chat_slash_references_enabled is True


def test_turning_a_chat_ref_toggle_off_is_saved() -> None:
    settings = PanelSettings.from_json_dict({"chat_slash_references_enabled": False})
    assert settings.chat_slash_references_enabled is False
    assert settings._has_overrides()
