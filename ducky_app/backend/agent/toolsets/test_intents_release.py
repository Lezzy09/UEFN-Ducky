"""Talking about a plugin release unlocks ducky_plugin_release_check."""

from __future__ import annotations


def test_release_intent_lists_the_release_check():
    from backend.agent.toolsets.intents import INTENT_KEYWORDS

    def unlocked(text: str) -> set[str]:
        return set().union(*(tools for pattern, tools in INTENT_KEYWORDS if pattern.search(text)))

    assert "ducky_plugin_release_check" in unlocked("release the island-media-kit plugin")
    assert "ducky_plugin_release_check" in unlocked("publish a plugin to the store")
    assert "ducky_plugin_release_check" not in unlocked("what time is it")
