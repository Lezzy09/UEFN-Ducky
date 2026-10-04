"""Auto-reload of a stale listener must not loop.

Regression: a reload briefly takes the listener offline, coming back online
re-ships, and when the reload could not load AppData (a dev checkout ahead on
the editor's sys.path) the stamps still differed — 112 reloads in one session.
"""

from __future__ import annotations

import pytest

from frontend import ship_newest


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(ship_newest, "_last_auto_reload", None)


def test_matching_or_missing_stamp_never_reloads():
    assert ship_newest._should_auto_reload("79:1", "79:1", 0.0) is False
    assert ship_newest._should_auto_reload("71:1", "", 0.0) is False


def test_stale_listener_reloads_once_not_again():
    assert ship_newest._should_auto_reload("71:1", "79:2", 100.0) is True
    # Listener came back still on the other tree: same pair → no second reload.
    assert ship_newest._should_auto_reload("71:1", "79:2", 105.0) is False


def test_new_deploy_or_retry_window_reloads_again():
    assert ship_newest._should_auto_reload("71:1", "79:2", 100.0) is True
    assert ship_newest._should_auto_reload("71:1", "80:3", 101.0) is True  # newer deploy
    later = 101.0 + ship_newest._AUTO_RELOAD_RETRY_SEC
    assert ship_newest._should_auto_reload("71:1", "80:3", later) is True  # transient failure retried


def test_unstamped_listener_reloads_once():
    assert ship_newest._should_auto_reload("", "79:2", 0.0) is True
    assert ship_newest._should_auto_reload("", "79:2", 1.0) is False
