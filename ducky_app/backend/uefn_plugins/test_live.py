"""Live editing in core: the WebRTC bridge to the main window (asks and answers, bytes in
and out, only for the spaces provider), going live on a team copy only, what goes to the
room (changes by themselves, the host's pointers, a plugin's own topics within limits),
and a teammate's live change: reads show it until its commit lands or 30 s pass, the
panel hears it at once, a write here wins. Presence carries the room; panel pages get
the pointer script.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import threading
import time
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")

from backend.store.repos import plugin_data as repo
from backend.store.repos import space_vcs
from backend.uefn_plugins import data_crypto, live, rtc, scopes, spaces, vcs_engine
from backend.uefn_plugins.scopes import PluginData

SPACE, PLUGIN = "spaceT", "cards"
ALEX = {"name": "Alex", "user": "u_alex", "device": "d_alex", "label": "ALEX-PC"}


class FakeLive(spaces.Provider):
    kind_label = "team"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Any, str, bool]] = []
        self.joined: list[tuple[str, str, str | None]] = []
        self.peers: list[dict[str, Any]] = []
        self.supported = True

    def enabled(self) -> bool:
        return True

    def live_supported(self) -> bool:
        return self.supported

    def live_join(self, account: str, space_id: str, plugin: str, room: str) -> None:
        self.joined.append((space_id, plugin, room))

    def live_leave(self, account: str, space_id: str, plugin: str) -> None:
        self.joined.append((space_id, plugin, None))

    def live_send(self, account: str, space_id: str, plugin: str, topic: str, data: Any, *,
                  to: str = "", fast: bool = False) -> int:
        self.sent.append((plugin, topic, data, to, fast))
        return 1

    def live_state(self, account: str, space_id: str, plugin: str) -> dict[str, Any]:
        return {"state": "live", "peers": list(self.peers)}


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch):
    """Ana signed in, ``cards`` on the team copy (pulled once), a provider with live."""
    from frontend import duckyos_account

    key = "https://uefnducky.org|ana@example.com"
    data_crypto.reset_for_tests()
    monkeypatch.setattr(duckyos_account, "account_key", lambda blob=None: key)
    monkeypatch.setattr(data_crypto, "_fetch_adk", lambda: hashlib.sha256(b"adk/" + key.encode()).digest())
    impl = FakeLive()
    spaces.install_for_tests(impl)
    account = scopes.account_id()
    repo.link_set(account, PLUGIN, SPACE)
    repo.sync_put(account, SPACE, label="Alpha", synced_at=time.time())
    space_vcs.head_put(account, SPACE, PLUGIN, engine="v2")  # on the team repo: presence, locks, live
    pushed: list[dict[str, Any]] = []
    beats: list[tuple[str, str]] = []
    monkeypatch.setattr(live, "_push", pushed.append)
    monkeypatch.setattr(live, "_beat_soon", lambda a, s: beats.append((a, s)))
    live.reset_for_tests()
    yield {"account": account, "impl": impl, "pushed": pushed, "beats": beats}
    live.reset_for_tests()
    spaces.reset_for_tests()
    scopes.forget_change_listeners(PLUGIN)
    data_crypto.reset_for_tests()


def _row(account: str, key: str) -> dict[str, Any] | None:
    return repo.get(account, SPACE, PLUGIN, "doc", key)


# --------------------------------------------------------------------------- the bridge


def test_the_bridge_asks_the_window_and_waits_for_its_answer() -> None:
    told: list[dict[str, Any]] = []
    b = rtc.Bridge(push=told.append)
    offer = {"type": "offer", "sdp": "v=0 offer"}

    def answer() -> None:
        while not told:
            time.sleep(0.01)
        b.reply(told[0]["id"], {"offer": offer})

    threading.Thread(target=answer, daemon=True).start()
    assert b.open("peer-1") == offer
    assert told[0]["type"] == "rtc_cmd" and told[0]["op"] == "open" and told[0]["peer"] == "peer-1"
    assert told[0]["ice"] == rtc.DEFAULT_ICE
    assert b.reply(told[0]["id"], {}) is False  # nobody waits for it any more


def test_the_bridge_says_why_when_the_window_fails_or_never_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[dict[str, Any]] = []
    b = rtc.Bridge(push=lambda ev: (told.append(ev), b.reply(ev["id"], {"error": "no such peer"})))
    with pytest.raises(rtc.RtcError, match="no such peer"):
        b.finish("peer-1", {"type": "answer", "sdp": "v=0"})
    quiet = rtc.Bridge(push=lambda ev: None)
    with pytest.raises(rtc.RtcError, match="window"):
        quiet._ask("open", timeout=0.05, peer="p")
    with pytest.raises(rtc.RtcError, match="invalid"):
        quiet.accept("p", {"type": "answer", "sdp": "x"})  # not an offer
    with pytest.raises(rtc.RtcError, match="peer id"):
        quiet.open("bad peer!")


def test_bytes_go_out_as_base64_and_come_back_as_bytes() -> None:
    told: list[dict[str, Any]] = []
    b = rtc.Bridge(push=told.append)
    b.send("peer-1", "live-fast", b"\x00\x01hi")
    assert told[-1] == {"type": "rtc_cmd", "op": "send", "peer": "peer-1", "channel": "live-fast",
                        "data": base64.b64encode(b"\x00\x01hi").decode()}
    with pytest.raises(rtc.RtcError):
        b.send("peer-1", "other", b"x")
    with pytest.raises(rtc.RtcError):
        b.send("peer-1", "live", b"x" * (rtc.MAX_SEND_BYTES + 1))
    got: list[tuple[str, ...]] = []
    b.on_message = lambda peer, ch, data: got.append((peer, ch, data))
    b.on_state = lambda peer, st: got.append((peer, st))
    b.event("peer-1", "message", {"channel": "live", "data": base64.b64encode(b"yo").decode()})
    b.event("peer-1", "message", {"channel": "nope", "data": "eW8="})
    b.event("peer-1", "message", {"channel": "live", "data": "not base64!"})
    b.event("peer-1", "state", {"state": "connected"})
    b.event("peer-1", "state", {"state": "weird"})
    b.event("bad peer!", "state", {"state": "connected"})
    assert got == [("peer-1", "live", b"yo"), ("peer-1", "connected")]


def test_only_the_spaces_provider_gets_the_bridge(team: dict[str, Any]) -> None:
    with pytest.raises(PermissionError):
        spaces.rtc_bridge("cards")
    with pytest.raises(PermissionError):
        spaces.rtc_bridge("")
    assert spaces.rtc_bridge("test-spaces") is rtc.bridge()


# --------------------------------------------------------------------------- going live


def test_live_is_for_a_team_copy_with_a_provider_that_has_it(team: dict[str, Any]) -> None:
    impl, account = team["impl"], team["account"]
    impl.supported = False
    assert live.join(PLUGIN)["ok"] is False
    impl.supported = True
    space_vcs.head_put(account, SPACE, PLUGIN, engine="v1")
    assert live.join(PLUGIN)["error"].startswith("Live works once")  # the older sync has no presence
    space_vcs.head_put(account, SPACE, PLUGIN, engine="v2")
    repo.link_set(account, PLUGIN, scopes.PERSONAL)
    got = live.join(PLUGIN)
    assert got == {"ok": False, "error": "Live works on a team copy."}
    repo.link_set(account, PLUGIN, SPACE)
    assert live.join(PLUGIN, "no spaces!")["ok"] is False
    got = live.join(PLUGIN)
    assert got["ok"] and got["on"] and got["room"] == live.DEFAULT_ROOM and got["state"] == "live"
    assert impl.joined == [(SPACE, PLUGIN, "all")]
    assert team["beats"] == [(account, SPACE)]  # presence says so now, not at the next beat
    assert team["pushed"][-1]["type"] == "live_peers" and team["pushed"][-1]["on"] is True


def test_presence_carries_the_room_and_leaving_drops_it(team: dict[str, Any]) -> None:
    account = team["account"]
    live.join(PLUGIN, "level-2")
    blob = vcs_engine.presence_blob(account, SPACE, [PLUGIN])
    assert blob["plugins"][PLUGIN]["live"]["room"] == "level-2"
    status = spaces.scope_status(PLUGIN)
    assert status["live"]["on"] is True and status["live"]["room"] == "level-2"
    live.join(PLUGIN, "level-3")  # another room: the first one is left
    assert team["impl"].joined[-2:] == [(SPACE, PLUGIN, None), (SPACE, PLUGIN, "level-3")]
    live.leave(PLUGIN)
    assert "live" not in vcs_engine.presence_blob(account, SPACE, [PLUGIN])["plugins"][PLUGIN]
    assert spaces.scope_status(PLUGIN)["live"]["on"] is False


def test_switching_to_local_ends_live(team: dict[str, Any]) -> None:
    live.join(PLUGIN)
    repo.link_set(team["account"], PLUGIN, scopes.PERSONAL)
    assert live.status(PLUGIN)["on"] is False
    assert team["impl"].joined[-1] == (SPACE, PLUGIN, None)


def test_the_bar_shows_who_is_live_and_how_they_are_reached(team: dict[str, Any]) -> None:
    team["impl"].peers = [{**ALEX, "path": "direct"}, {"name": "Sam", "device": "d_sam", "path": "none"}]
    live.join(PLUGIN)
    st = live.status(PLUGIN)
    assert [p["path"] for p in st["peers"]] == ["direct", "none"]


# --------------------------------------------------------------------------- what goes out


def test_a_plugin_sends_its_own_topics_within_the_limits(team: dict[str, Any]) -> None:
    impl = team["impl"]
    assert live.send(PLUGIN, "cursor", {"x": 1})["ok"] is False  # not live yet
    live.join(PLUGIN)
    assert live.send(PLUGIN, "ducky.change", {})["ok"] is True  # the host's (from local_change)
    assert live.send(PLUGIN, "ducky.secret", {})["ok"] is False
    assert live.send(PLUGIN, "Bad Topic", {})["ok"] is False
    assert live.send(PLUGIN, "chat", {"t": "x" * (live.LIMIT_BYTES + 1)})["ok"] is False
    assert live.send(PLUGIN, "chat", object())["ok"] is False  # not JSON
    impl.sent.clear()
    assert live.send(PLUGIN, "chat", {"t": "hi"}, to="d_alex") == {"ok": True, "sent": 1}
    assert live.send(PLUGIN, "ducky.pointer", {"anchor": "body"})["ok"] is True
    assert impl.sent == [(PLUGIN, "chat", {"t": "hi"}, "d_alex", False), (PLUGIN, "ducky.pointer", {"anchor": "body"}, "", True)]
    results = [live.send(PLUGIN, "chat", {"n": n})["ok"] for n in range(live.LIMIT_PER_S + 5)]
    assert results.count(False) >= 5  # at most 30 a second


def test_a_write_goes_to_the_room_by_itself(team: dict[str, Any]) -> None:
    impl, data = team["impl"], PluginData(PLUGIN)
    data.put("card.pip", {"hp": 1})
    assert impl.sent == []  # not live: only the commit carries it
    live.join(PLUGIN)
    data.put("card.pip", {"hp": 2})
    plugin, topic, change, to, fast = impl.sent[-1]
    assert (plugin, topic, to, fast) == (PLUGIN, live.CHANGE, "", False)
    assert change["kind"] == "doc" and change["key"] == "card.pip" and json.loads(change["value"]) == {"hp": 2}
    assert change["sha"] == _row(team["account"], "card.pip")["sha256"]
    data.put("card.big", {"blob": "x" * (live.DOC_INLINE_MAX + 10)})
    assert "value" not in impl.sent[-1][2]  # too big to travel live: a ref, the pull brings it
    data.delete("card.pip")
    assert impl.sent[-1][2]["deleted"] is True
    data.put_file("art/pip.png", b"\x89PNG")
    assert impl.sent[-1][2]["kind"] == "file" and impl.sent[-1][2]["key"] == "art/pip.png"


# --------------------------------------------------------------------------- what comes in


def test_a_teammates_change_shows_at_once_until_its_commit_lands(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    account, data = team["account"], PluginData(PLUGIN)
    data.put("card.pip", {"hp": 1})
    live.join(PLUGIN)
    team["pushed"].clear()
    theirs = scopes.encode_doc({"hp": 9}).decode()
    sha = hashlib.sha256(theirs.encode()).hexdigest()
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "doc", "key": "card.pip", "value": theirs, "sha": sha})
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE,
                 {"kind": "doc", "key": "card.new", "value": scopes.encode_doc({"hp": 3}).decode(), "sha": "x"})
    assert data.get("card.pip") == {"hp": 9}
    assert data.items("card.") == {"card.pip": {"hp": 9}, "card.new": {"hp": 3}}
    told = team["pushed"][0]
    assert told == {"type": "plugin_scope_changed", "plugins": [PLUGIN], "synced": True, "live": True,
                    "keys": {PLUGIN: ["card.pip"]}, "by": "Alex"}
    # The commit lands (the pull writes the same content): the stored row is read again.
    repo.put(account, SPACE, PLUGIN, "doc", "card.pip", value=data_crypto.seal_text(theirs, account),
             size=len(theirs), sha256=sha, dirty=False)
    assert data.get("card.pip") == {"hp": 9}
    assert live.provisional_keys(account, SPACE, PLUGIN, "card.pip") == []
    # Nothing landed for card.new: after 30 s it goes.
    later = time.time() + live.PROVISIONAL_S + 1
    monkeypatch.setattr(live.time, "time", lambda: later)
    assert data.get("card.new") is None


def test_a_write_here_wins_over_a_teammates_live_value(team: dict[str, Any]) -> None:
    account, data = team["account"], PluginData(PLUGIN)
    live.join(PLUGIN)
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE,
                 {"kind": "doc", "key": "card.pip", "value": scopes.encode_doc({"hp": 9}).decode(), "sha": "s"})
    data.put("card.pip", {"hp": 5})
    assert data.get("card.pip") == {"hp": 5}


def test_a_teammates_delete_and_a_big_change_or_file_wake_a_pull(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.uefn_plugins import sync_scheduler

    account, data = team["account"], PluginData(PLUGIN)
    woke: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(sync_scheduler, "wake", lambda a, s, p=None: woke.append((a, s, p)))
    data.put("card.pip", {"hp": 1})
    live.join(PLUGIN)
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "doc", "key": "card.pip", "deleted": True, "sha": ""})
    assert data.get("card.pip") is None and "card.pip" not in data.items("card.")
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "doc", "key": "card.big", "sha": "s"})
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "file", "key": "art/a.png", "sha": "s"})
    assert woke == [(account, SPACE, PLUGIN), (account, SPACE, PLUGIN)]
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "weird", "key": "x"})
    assert len(woke) == 2


def test_nothing_comes_in_for_a_plugin_that_isnt_live_here(team: dict[str, Any]) -> None:
    account, data = team["account"], PluginData(PLUGIN)
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE,
                 {"kind": "doc", "key": "card.pip", "value": scopes.encode_doc({"hp": 9}).decode(), "sha": "s"})
    assert data.get("card.pip") is None and team["pushed"] == []


def test_a_plugins_own_topics_reach_its_panels_and_backend(team: dict[str, Any]) -> None:
    account = team["account"]
    heard: list[tuple[dict[str, str], Any]] = []
    api = live.LiveApi(PLUGIN)
    api.on("cursor", lambda who, data: heard.append((who, data)))
    api.on("cursor", lambda who, data: 1 / 0)  # a broken callback never stops delivery
    with pytest.raises(TypeError):
        api.on("cursor", "not a function")  # type: ignore[arg-type]
    api.join()
    team["pushed"].clear()
    live.deliver(account, SPACE, PLUGIN, ALEX, "cursor", {"x": 3})
    assert heard == [(ALEX, {"x": 3})]
    assert team["pushed"] == [{"type": "live_message", "plugin": PLUGIN, "from": ALEX, "topic": "cursor", "data": {"x": 3}}]
    live.forget(PLUGIN)
    live.deliver(account, SPACE, PLUGIN, ALEX, "cursor", {"x": 4})
    assert len(heard) == 1


# --------------------------------------------------------------------------- the page


def test_panel_pages_get_the_pointer_script() -> None:
    from backend.uefn_plugins.ui_kit import LIVE_PRESENCE_SCRIPT
    from backend.uefn_plugins.webview import with_panel_error_script

    out = with_panel_error_script(b"<!doctype html><html><head></head><body></body></html>")
    assert LIVE_PRESENCE_SCRIPT.encode() in out
    for need in ("live.pointer", "live.select", "live.state", "live.message", "live.peers", "pointer-events:none"):
        assert need in LIVE_PRESENCE_SCRIPT, need
