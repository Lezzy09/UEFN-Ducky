"""What's new shows each update's short changes once, and never on a first start."""

from __future__ import annotations

from frontend import whats_new as wn


def _row(version: str, *texts: str) -> dict:
    row = {"version": version, "changelog": "long", "created_at": f"t{version}"}
    if texts:
        row["items"] = [{"kind": "fix", "text": t} for t in texts]
    return row


FEED = [
    _row("1.2.412", "Team plugins no longer reset by themselves"),
    _row("1.2.411"),
    _row("1.2.410", "Sign in works again", "New Tripo plugin"),
    _row("1.2.409", "Faster start"),
    _row("1.2.408", "Older"),
]


def _decide(**kw):
    args = {"current": "1.2.412", "last_seen": "1.2.408", "fresh_install": False, "enabled": True}
    args.update(kw)
    return wn.whats_new(FEED, **args)


def test_lists_the_unseen_versions_with_changes_newest_first() -> None:
    got = _decide()
    assert got["show"] is True
    assert [v["version"] for v in got["versions"]] == ["1.2.412", "1.2.410", "1.2.409"]
    assert got["versions"][1]["items"][1] == {"kind": "fix", "text": "New Tripo plugin"}
    assert got["released_at"] == "t1.2.412"
    assert got["mark"] is None


def test_nothing_when_already_seen_or_rolled_back() -> None:
    assert _decide(last_seen="1.2.412")["show"] is False
    assert _decide(last_seen="1.2.413")["versions"] == []


def test_first_start_of_a_fresh_install_marks_seen_without_showing() -> None:
    got = _decide(last_seen=None, fresh_install=True)
    assert got["show"] is False
    assert got["mark"] == "1.2.412"


def test_no_last_seen_on_an_old_install_shows_only_the_running_version() -> None:
    got = _decide(last_seen=None)
    assert [v["version"] for v in got["versions"]] == ["1.2.412"]


def test_offline_or_unlisted_build_waits_without_marking() -> None:
    got = wn.whats_new(FEED[1:], current="1.2.412", last_seen="1.2.408", fresh_install=False, enabled=True)
    assert got["show"] is False
    assert got["mark"] is None


def test_running_version_without_changes_is_marked_quietly() -> None:
    got = _decide(current="1.2.411", last_seen="1.2.410")
    assert got["show"] is False
    assert got["mark"] == "1.2.411"


def test_turned_off_marks_seen_without_showing() -> None:
    got = _decide(enabled=False)
    assert got["show"] is False
    assert got["mark"] == "1.2.412"
    assert [v["version"] for v in got["recent"]][:2] == ["1.2.412", "1.2.410"]


def test_mark_seen_never_moves_back_and_can_turn_the_window_off(monkeypatch) -> None:
    store: dict[str, str] = {"whats_new.last_seen": "1.2.412"}
    monkeypatch.setattr(wn, "_meta_get", store.get)
    monkeypatch.setattr(wn, "_meta_set", store.__setitem__)
    saved = []

    class FakeSettings:
        whats_new_popup = True

        @classmethod
        def load(cls):
            return cls()

        def save(self):
            saved.append(self.whats_new_popup)

    monkeypatch.setattr("frontend.settings.PanelSettings", FakeSettings)
    assert wn.mark_whats_new_seen("1.2.410")["ok"] is True
    assert store["whats_new.last_seen"] == "1.2.412"
    wn.mark_whats_new_seen("1.2.413", dont_show_again=True)
    assert store["whats_new.last_seen"] == "1.2.413"
    assert saved == [False]
