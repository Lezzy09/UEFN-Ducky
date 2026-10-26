"""island_watch: one cheap lore call a round, one alert per new remote head, never a pull."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend.ui_web.verse_editor.urc import island_watch as iw


class FakeLore:
    def __init__(self) -> None:
        self.remote = {"ok": True, "revision": 15, "signature": "s15", "error": ""}
        self.local = {"ok": True, "revision": 13, "signature": "s13", "error": ""}
        self.state: dict = {}
        self.calls: list[str] = []

    def remote_head(self, root):
        self.calls.append("remote_head")
        return dict(self.remote)

    def local_head(self, root):
        self.calls.append("local_head")
        return dict(self.local)

    def repo_state(self, root):
        self.calls.append("repo_state")
        return dict(self.state)


def behind_15(own: bool = False) -> dict:
    return {
        "ok": True, "behind": True, "local_revision": 13, "remote_revision": 15,
        "local_signature": "s13", "remote_signature": "s15",
        "incoming": [{"revision": 15, "signature": "s15", "creator": "Mich ou", "message": "moved the sphere",
                      "own": own}],
    }


IN_SYNC_15 = {"ok": True, "behind": False, "local_revision": 15, "remote_revision": 15,
              "local_signature": "s15", "remote_signature": "s15", "incoming": []}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    island = tmp_path / "test_ducky_v2"
    (island / ".lore").mkdir(parents=True)
    lore = FakeLore()
    out = SimpleNamespace(island=str(island), lore=lore, alerts=[], pushes=[], doc={}, away=False)
    out.open = str(island)
    monkeypatch.setattr(iw, "_lore", lambda: lore)
    monkeypatch.setattr(iw, "_open_island", lambda: out.open)
    monkeypatch.setattr(iw, "_person_away", lambda: out.away)
    monkeypatch.setattr(iw, "_alert", lambda *a: out.alerts.append(a))
    monkeypatch.setattr(iw, "_push", out.pushes.append)
    monkeypatch.setattr(iw, "_read_doc", lambda: dict(out.doc) if out.doc else None)

    def write(doc):
        out.doc = dict(doc) if doc else {}

    monkeypatch.setattr(iw, "_write_doc", write)
    iw.reset_for_tests()
    yield out
    iw.reset_for_tests()


def test_new_changes_from_the_other_pc_alert_once(env) -> None:
    env.lore.state = behind_15()
    assert iw.tick() == iw.ACTIVE_S
    assert env.lore.calls == ["remote_head", "repo_state"]
    assert len(env.alerts) == 1
    title, status, detail = env.alerts[0]
    assert title == "test_ducky_v2" and status == "1 new change to pull."
    assert detail.startswith("1 new change on test_ducky_v2 from Mich ou: “moved the sphere”")
    assert "revision_pull" in detail
    assert env.pushes == [{"type": "island_updates", "island": env.island, "name": "test_ducky_v2", "behind": True,
                           "count": 1, "detail": "1 new change on test_ducky_v2 from Mich ou: “moved the sphere”"}]
    assert env.doc["behind"] and env.doc["new_changes"] == 1 and env.doc["authors"] == ["Mich ou"]

    # Same remote head, same local head: two cheap calls, no new alert, never a pull.
    env.lore.calls.clear()
    iw.tick()
    assert env.lore.calls == ["remote_head", "local_head"]
    assert len(env.alerts) == 1


def test_a_pull_clears_it_and_tells_the_panel(env) -> None:
    env.lore.state = behind_15()
    iw.tick()
    env.lore.local = {"ok": True, "revision": 15, "signature": "s15", "error": ""}
    env.lore.state = IN_SYNC_15
    iw.tick()
    assert env.pushes[-1]["behind"] is False and env.pushes[-1]["detail"] == "test_ducky_v2 is up to date."
    assert env.doc["behind"] is False and env.doc["new_changes"] == 0
    env.lore.calls.clear()
    iw.tick()  # in sync: one call a round
    assert env.lore.calls == ["remote_head"]


def test_own_check_in_is_not_news(env) -> None:
    env.lore.state = behind_15(own=True)
    iw.tick()
    assert env.alerts == [] and env.pushes == []
    assert env.doc["behind"] is True and env.doc["new_changes"] == 0


def test_a_newer_push_alerts_again(env) -> None:
    env.lore.state = behind_15()
    iw.tick()
    env.lore.remote = {"ok": True, "revision": 17, "signature": "s17", "error": ""}
    state = behind_15()
    state["remote_signature"] = "s17"
    state["incoming"].insert(0, {"revision": 17, "signature": "s17", "creator": "Mich ou", "message": "more",
                                 "own": False})
    env.lore.state = state
    iw.tick()
    assert len(env.alerts) == 2 and env.alerts[1][1] == "2 new changes to pull."


def test_restart_does_not_retell_the_same_news(env) -> None:
    env.doc = {"island": env.island, "told": "s15"}
    iw.reset_for_tests()
    env.lore.state = behind_15()
    iw.tick()
    assert env.alerts == [] and env.doc["behind"] is True


def test_no_island_no_lore_call(env) -> None:
    env.open = ""
    assert iw.tick() == iw.NO_ISLAND_S
    assert env.lore.calls == []


def test_not_a_lore_island(env, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    env.open = str(plain)
    assert iw.tick() == iw.NOT_LORE_S
    assert env.lore.calls == []


def test_errors_back_off_then_recover(env) -> None:
    env.lore.remote = {"ok": False, "error": "offline"}
    assert iw.tick() == iw.ACTIVE_S * 2
    assert iw.tick() == iw.ACTIVE_S * 4
    for _ in range(10):
        delay = iw.tick()
    assert delay == iw.ERROR_MAX_S
    env.lore.remote = {"ok": True, "revision": 15, "signature": "s15", "error": ""}
    env.lore.state = IN_SYNC_15
    assert iw.tick() == iw.ACTIVE_S


def test_slower_when_the_person_is_away(env) -> None:
    env.away = True
    env.lore.state = IN_SYNC_15
    assert iw.tick() == iw.IDLE_S


def test_island_closed_forgets_it(env) -> None:
    env.lore.state = behind_15()
    iw.tick()
    env.open = ""
    iw.tick()
    assert env.doc == {}


def test_for_agents(env, monkeypatch: pytest.MonkeyPatch) -> None:
    assert iw.for_agents() is None
    env.lore.state = behind_15()
    iw.tick()
    out = iw.for_agents()
    assert out["behind"] is True and out["new_changes"] == 1 and out["authors"] == ["Mich ou"]
    assert out["latest"] == {"revision": 15, "by": "Mich ou", "message": "moved the sphere"}
    assert "revision_pull" in out["hint"]
    # The app that wrote it is gone: nothing watches the island any more.
    env.doc["pid"] = 999999999
    assert iw.for_agents() is None


def test_news_text() -> None:
    news = [{"creator": "A", "message": "m2"}, {"creator": "B", "message": "m1"}, {"creator": "A", "message": ""}]
    assert iw.news_text("isle", news) == "3 new changes on isle from A, B: “m2”"
    assert iw.news_text("isle", [{"creator": "", "message": ""}]) == "1 new change on isle"
