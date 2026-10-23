"""Live editing in core: the WebRTC bridge to the main window (asks and answers, bytes in
and out, only for the spaces provider), going live on a team copy only, in groups named
after their host, what goes to the group (the host's pointers and holds, a plugin's own
topics within limits), and changes: never live, only a commit's "pull now", which pulls
at once. Presence carries the room; panel pages get the live script.
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
    woke: list[tuple[str, str, str | None]] = []
    from backend.uefn_plugins import sync_scheduler

    monkeypatch.setattr(sync_scheduler, "wake", lambda a, s, p=None: woke.append((a, s, p)))
    live.reset_for_tests()
    yield {"account": account, "impl": impl, "pushed": pushed, "beats": beats, "woke": woke}
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
    me = space_vcs.device_id()
    assert got["ok"] and got["on"] and got["room"] == f"h:{me}" and got["state"] == "live"  # this PC hosts
    assert impl.joined == [(SPACE, PLUGIN, f"h:{me}")]
    assert team["beats"] == [(account, SPACE)]  # presence says so now, not at the next beat
    assert team["woke"] == [(account, SPACE, PLUGIN)]  # joined up to date: a pull now
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


def _roster(account: str, *people: dict[str, Any]) -> None:
    space_vcs.presence_put(account, SPACE, {"people": list(people)}, sent_sha="", now=time.time())


def _on(device: str, name: str, room: str, since: float, plugin: str = PLUGIN) -> dict[str, Any]:
    return {"device": device, "user": f"u_{name}", "user_name": name, "label": f"{name.upper()}-PC",
            "plugins": {plugin: {"viewing": True, "live": {"room": room, "since": since}}}}


def test_groups_are_named_by_their_host_with_who_is_in_them(team: dict[str, Any]) -> None:
    account = team["account"]
    _roster(account,
            _on("d_iliya", "iliya", "h:d_iliya", 10), _on("d_cy", "Cy", "h:d_iliya", 20),
            _on("d_mo", "Mo", "h:d_mo", 5), _on("d_ed", "Ed", "h:d_gone", 30),
            _on("d_x", "Xi", "h:d_x", 1, plugin="other"),
            {"device": "d_bo", "user_name": "Bo", "plugins": {PLUGIN: {"viewing": True}}})
    got = live.status(PLUGIN)["groups"]
    assert [(g["room"], g["host"], [m["name"] for m in g["members"]], g["mine"]) for g in got] == [
        ("h:d_iliya", "iliya", ["iliya", "Cy"], False),  # the biggest first
        ("h:d_gone", "", ["Ed"], False),  # its host left: no host
        ("h:d_mo", "Mo", ["Mo"], False),
    ]
    # Joining iliya's group: this PC counts at once, before its next beat, and comes first.
    assert live.join(PLUGIN, "h:d_iliya")["ok"]
    mine = live.status(PLUGIN)["groups"][0]
    assert mine["mine"] and mine["host"] == "iliya" and not mine["hostIsMe"]
    assert [m["name"] for m in mine["members"]] == ["iliya", "Cy", "You"] and mine["members"][2]["me"]
    # Hosting: this PC's own group.
    assert live.join(PLUGIN)["ok"]
    mine = live.status(PLUGIN)["groups"][0]
    assert mine["room"] == live.host_room() and mine["hostIsMe"] and mine["host"] == "You"


def test_a_space_is_live_while_one_of_its_plugins_is(team: dict[str, Any]) -> None:
    assert live.spaces_live() == set()
    live.join(PLUGIN)
    assert live.spaces_live() == {(team["account"], SPACE)}
    live.leave(PLUGIN)
    assert live.spaces_live() == set()


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


def test_a_group_member_with_no_link_is_named_after_a_grace(team: dict[str, Any]) -> None:
    now = time.time()
    _roster(team["account"], _on("d_iliya", "iliya", "h:d_iliya", now - 60), _on("d_cy", "Cy", "h:d_iliya", now))
    assert live.join(PLUGIN, "h:d_iliya")["ok"]
    st = live.status(PLUGIN)
    assert st["unlinked"] == []  # this PC just joined: still connecting to everyone
    assert sorted(st["connecting"]) == ["Cy", "iliya"]
    with live._lock:
        live._live[PLUGIN].since = now - 60
    team["impl"].peers = [{**ALEX, "device": "d_iliya", "path": "direct"}]
    st = live.status(PLUGIN)
    assert st["unlinked"] == [] and st["connecting"] == ["Cy"]  # Cy only just went live
    team["impl"].peers = [{**ALEX, "device": "d_iliya", "path": "none"}]
    assert live.status(PLUGIN)["unlinked"] == ["iliya"]  # presence has them, nothing reaches them


def test_this_account_on_another_pc_is_you_on_that_pc(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    account = team["account"]
    monkeypatch.setattr(vcs_engine, "my_user_id", lambda: "u_me")
    laptop = {**_on("d_lap", "me", "h:d_lap", 10), "user": "u_me", "label": "Laptop"}
    space_vcs.presence_put(account, SPACE, {"people": [laptop], "devices": {"d_lap": "Laptop"}}, sent_sha="", now=time.time())
    assert live.status(PLUGIN)["groups"][0]["members"][0]["name"] == "You on Laptop"
    live.join(PLUGIN, "h:d_lap")
    team["pushed"].clear()
    live.deliver(account, SPACE, PLUGIN, {"name": "me", "user": "u_me", "device": "d_lap"}, "ducky.pointer", {})
    assert team["pushed"][-1]["from"]["name"] == "You on Laptop"  # pointers say which PC


# --------------------------------------------------------------------------- what goes out


def test_a_plugin_sends_its_own_topics_within_the_limits(team: dict[str, Any]) -> None:
    impl = team["impl"]
    assert live.send(PLUGIN, "cursor", {"x": 1})["ok"] is False  # not live yet
    live.join(PLUGIN)
    assert live.send(PLUGIN, "ducky.change", {})["ok"] is False  # the host's, after a commit only
    assert live.send(PLUGIN, "ducky.secret", {})["ok"] is False
    assert live.send(PLUGIN, "Bad Topic", {})["ok"] is False
    assert live.send(PLUGIN, "chat", {"t": "x" * (live.LIMIT_BYTES + 1)})["ok"] is False
    assert live.send(PLUGIN, "chat", object())["ok"] is False  # not JSON
    impl.sent.clear()
    assert live.send(PLUGIN, "chat", {"t": "hi"}, to="d_alex") == {"ok": True, "sent": 1}
    assert live.send(PLUGIN, "ducky.pointer", {"anchor": "body"})["ok"] is True
    assert live.send(PLUGIN, "ducky.hold", {"anchor": "body", "on": True, "t": 1})["ok"] is True
    # Pointers may drop (the next replaces them); a hold, and its let-go, never may.
    assert impl.sent == [(PLUGIN, "chat", {"t": "hi"}, "d_alex", False), (PLUGIN, "ducky.pointer", {"anchor": "body"}, "", True),
                         (PLUGIN, "ducky.hold", {"anchor": "body", "on": True, "t": 1}, "", False)]
    results = [live.send(PLUGIN, "chat", {"n": n})["ok"] for n in range(live.LIMIT_PER_S + 5)]
    assert results.count(False) >= 5  # at most 30 a second


def test_a_write_never_goes_live_a_commit_tells_the_group_to_pull(team: dict[str, Any]) -> None:
    impl, account, data = team["impl"], team["account"], PluginData(PLUGIN)
    live.join(PLUGIN)
    impl.sent.clear()
    data.put("card.pip", {"hp": 2})
    data.put_file("art/pip.png", b"\x89PNG")
    data.delete("card.pip")
    assert impl.sent == []  # half a change (a doc without its picture) never reaches anyone
    live.committed(account, SPACE, PLUGIN)
    assert impl.sent == [(PLUGIN, live.CHANGE, {}, "", False)]
    live.leave(PLUGIN)
    live.committed(account, SPACE, PLUGIN)  # not live: the group's next round brings it
    assert len(impl.sent) == 1


def test_a_teammates_commit_pulls_it_now_and_nothing_shows_before_it_lands(team: dict[str, Any]) -> None:
    account, data = team["account"], PluginData(PLUGIN)
    data.put("card.pip", {"hp": 1})
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {})
    assert team["woke"] == []  # not live here: nothing comes in live
    live.join(PLUGIN)
    team["woke"].clear()
    team["pushed"].clear()
    live.deliver(account, SPACE, PLUGIN, ALEX, live.CHANGE, {"kind": "doc", "key": "card.pip", "value": "{}"})
    assert team["woke"] == [(account, SPACE, PLUGIN)]
    assert data.get("card.pip") == {"hp": 1}  # what is stored, until the pull lands it whole
    assert team["pushed"] == []  # the pull tells the panel what it changed


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


# --------------------------------------------------------------------------- holds


def test_a_hold_goes_to_the_group_at_once_and_to_everyone_in_presence(team: dict[str, Any]) -> None:
    impl, account = team["impl"], team["account"]
    assert live.hold(PLUGIN, '[id="title"]', True, 5, "vabc") == {"ok": True}
    assert impl.sent == []  # not live: presence only
    blob = vcs_engine.presence_blob(account, SPACE, [PLUGIN])
    assert blob["plugins"][PLUGIN]["holds"] == [{"a": '[id="title"]', "t": 5.0, "v": "vabc"}]
    live.join(PLUGIN)
    impl.sent.clear()
    live.hold(PLUGIN, "body>button:nth-of-type(1)", True, 7, "vabc")
    assert impl.sent == [(PLUGIN, live.HOLD, {"anchor": "body>button:nth-of-type(1)", "on": True, "t": 7.0, "v": "vabc"}, "", False)]
    live.hold(PLUGIN, '[id="title"]', False)
    assert [h["a"] for h in live.holds_of(PLUGIN)] == ["body>button:nth-of-type(1)"]
    # A hold the page stopped renewing goes; at most a few go in presence; bad ones never.
    assert live.holds_of(PLUGIN, now=time.time() + live.HOLD_STALE_S + 1) == []
    for i in range(live.HOLDS_MAX + 3):
        live.hold(PLUGIN, f"body>div:nth-of-type({i + 1})", True, i, "v1")
    assert len(live.holds_of(PLUGIN)) == live.HOLDS_MAX
    assert live.hold(PLUGIN, "x" * 401, True)["ok"] is False
    assert live.hold(PLUGIN, "body", True, 1, "bad view!")["ok"] is False
    repo.link_set(account, PLUGIN, scopes.PERSONAL)
    assert live.hold(PLUGIN, "body", True)["ok"] is False  # Local: nobody to tell


def test_teammates_holds_from_their_presence_reach_the_panels_when_they_change(team: dict[str, Any]) -> None:
    account = team["account"]
    me = space_vcs.device_id()
    mo = {"device": "d_mo", "user": "u_mo", "user_name": "Mo",
          "plugins": {PLUGIN: {"viewing": True, "holds": [{"a": '[id="title"]', "t": 3, "v": "vx"}]}}}
    mine = {"device": me, "user": "u_me", "user_name": "Me", "plugins": {PLUGIN: {"holds": [{"a": "body", "t": 1, "v": ""}]}}}
    live.roster_holds(account, SPACE, {"people": [mo, mine]})
    told = [e for e in team["pushed"] if e["type"] == "live_holds"]
    assert told == [{"type": "live_holds", "plugin": PLUGIN,
                     "holds": [{"device": "d_mo", "name": "Mo", "anchor": '[id="title"]', "t": 3, "v": "vx"}]}]
    assert live.holds_now(PLUGIN) == told[0]["holds"]
    live.roster_holds(account, SPACE, {"people": [mo, mine]})  # nothing moved: nothing told
    assert len([e for e in team["pushed"] if e["type"] == "live_holds"]) == 1
    live.roster_holds(account, SPACE, {"people": [mine]})  # Mo let go
    assert [e for e in team["pushed"] if e["type"] == "live_holds"][-1] == {"type": "live_holds", "plugin": PLUGIN, "holds": []}


def test_a_roster_from_heads_or_a_beat_tells_the_panels_what_teammates_hold(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(live, "roster_holds", lambda a, s, r: got.append((a, s, r)))
    vcs_engine._roster_came(team["account"], SPACE, {}, {"people": []})
    assert got == [(team["account"], SPACE, {"people": []})]


# --------------------------------------------------------------------------- folder plugins


def test_a_live_folder_plugin_restarts_for_a_pull_with_its_panels_kept(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.store.repos import folder_files
    from backend.uefn_plugins import host
    from frontend.ui_web import agent_modes

    told: list[dict[str, Any]] = []
    restarted: list[str] = []
    monkeypatch.setattr(agent_modes, "push_ui_event", told.append)
    monkeypatch.setattr(host, "reload_single_plugin", lambda pid: restarted.append(pid))
    live.join(PLUGIN)
    folder_files.reload_bump(PLUGIN, "pull")
    host._restart_moved(PLUGIN)
    assert restarted == [PLUGIN]
    assert told == [{"type": "plugin_scope_changed", "plugins": [PLUGIN], "synced": True, "live": True}]
    before = folder_files.reload_epoch(PLUGIN)
    live.leave(PLUGIN)  # the reload it skipped happens once now
    assert folder_files.reload_epoch(PLUGIN) == before + 1 and folder_files.reload_reason(PLUGIN) == "live ended"
    told.clear()
    host._restart_moved(PLUGIN)
    assert told == [{"type": "plugin_scope_changed", "plugins": [PLUGIN], "switched": True}]
    live.leave(PLUGIN)
    assert folder_files.reload_epoch(PLUGIN) == before + 1  # nothing skipped: no more reloads


def test_joining_a_teammates_group_reloads_the_panels_on_its_first_pull(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.store.repos import folder_files
    from backend.uefn_plugins import host
    from frontend.ui_web import agent_modes

    told: list[dict[str, Any]] = []
    monkeypatch.setattr(agent_modes, "push_ui_event", told.append)
    monkeypatch.setattr(host, "reload_single_plugin", lambda pid: None)
    live.join(PLUGIN, "h:d_alex")
    folder_files.reload_bump(PLUGIN, "pull")
    host._restart_moved(PLUGIN)  # the join's pull: the page opens on the host's data
    assert told == [{"type": "plugin_scope_changed", "plugins": [PLUGIN], "switched": True}]
    told.clear()
    folder_files.reload_bump(PLUGIN, "pull")
    host._restart_moved(PLUGIN)  # later pulls: kept, the page merges them
    assert told == [{"type": "plugin_scope_changed", "plugins": [PLUGIN], "synced": True, "live": True}]


def test_live_folder_changes_never_wait_behind_update_now(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from backend.uefn_plugins import panel_presence
    from backend.uefn_plugins import team_folders as tf

    monkeypatch.setattr(tf, "plugin_folders", lambda plugin: [SimpleNamespace(after_pull="reload")])
    monkeypatch.setattr(panel_presence, "panel_state", lambda plugin: {"visible": True})
    ctx = SimpleNamespace(plugin=PLUGIN)
    assert vcs_engine._holds_incoming(ctx) is True  # on screen: they wait for Update now
    live.join(PLUGIN)
    assert vcs_engine._holds_incoming(ctx) is False  # live: they land and the panels merge them


# --------------------------------------------------------------------------- live data ("data_live")


@pytest.fixture
def live_data(team: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``cards`` shares its data live; the outbox runs only when the test asks."""
    monkeypatch.setattr(scopes, "data_live", lambda plugin: plugin == PLUGIN)
    monkeypatch.setattr(live, "_outbox_start", lambda: None)
    return team


def _data_sent(team: dict[str, Any]) -> list[dict[str, Any]]:
    return [data for plugin, topic, data, _to, _fast in team["impl"].sent if topic == live.DATA]


def _item(key: str, value: Any, at: float) -> dict[str, Any]:
    raw = scopes.encode_doc(value)
    return {"k": "doc", "key": key, "op": "put", "at": at, "sha": hashlib.sha256(raw).hexdigest(),
            "v": raw.decode("utf-8")}


def test_a_live_plugins_writes_go_to_the_group_at_once(live_data: dict[str, Any]) -> None:
    data = PluginData(PLUGIN)
    data.put("card.old", {"hp": 0})  # before going live: that goes with sync only
    live.join(PLUGIN)
    data.put("card.pip", {"hp": 1})
    assert live.send_changes() == 1
    sent = _data_sent(live_data)
    assert [(d["k"], d["key"], d["op"]) for d in sent] == [("doc", "card.pip", "put")]
    assert json.loads(sent[0]["v"]) == {"hp": 1} and sent[0]["sha"] == _row(live_data["account"], "card.pip")["sha256"]
    assert live.send_changes() == 0  # each write goes once
    data.delete("card.pip")
    data.put_file("art/pip.png", b"PNG")
    assert live.send_changes() == 2
    gone, art = _data_sent(live_data)[1:]
    assert (gone["key"], gone["op"]) == ("card.pip", "del")
    assert (art["k"], art["key"], base64.b64decode(art["b"])) == ("asset", "art/pip.png", b"PNG")
    assert _row(live_data["account"], "card.old")["dirty"] == 1  # still on its way with sync


def test_a_groupmates_change_lands_at_once_as_a_pulled_copy(live_data: dict[str, Any]) -> None:
    account = live_data["account"]
    heard: list[list[str]] = []
    scopes.add_change_listener(PLUGIN, heard.append)
    live.join(PLUGIN, "h:d_alex")
    live.deliver(account, SPACE, PLUGIN, ALEX, live.DATA, _item("card.pip", {"hp": 7}, time.time()))
    assert PluginData(PLUGIN).get("card.pip") == {"hp": 7}
    assert _row(account, "card.pip")["dirty"] == 0  # theirs: sync records it from their PC, not this one
    assert heard == [["card.pip"]]  # the plugin's backend hears it like a pull
    assert {"type": "plugin_scope_changed", "plugins": [PLUGIN], "synced": True,
            "keys": {PLUGIN: ["card.pip"]}} in live_data["pushed"]
    assert live.send_changes() == 0  # never sent back to the group
    assert not [p for p in live_data["pushed"] if p.get("type") == "live_message"]  # not a page message
    live.deliver(account, SPACE, PLUGIN, ALEX, live.DATA, {"k": "doc", "key": "card.pip", "op": "del", "at": time.time()})
    assert PluginData(PLUGIN).get("card.pip") is None


def test_the_newest_change_of_an_item_wins_inside_the_group(live_data: dict[str, Any]) -> None:
    account = live_data["account"]
    live.join(PLUGIN, "h:d_alex")
    then = time.time() - 60
    PluginData(PLUGIN).put("card.pip", {"hp": 1})  # mine, written after their change was made
    assert not live._apply_data(account, SPACE, PLUGIN, ALEX, _item("card.pip", {"hp": 2}, then))
    assert PluginData(PLUGIN).get("card.pip") == {"hp": 1} and _row(account, "card.pip")["dirty"] == 1
    assert live._apply_data(account, SPACE, PLUGIN, ALEX, _item("card.pip", {"hp": 3}, time.time() + 1))
    assert PluginData(PLUGIN).get("card.pip") == {"hp": 3} and _row(account, "card.pip")["dirty"] == 0


def test_a_change_too_big_to_carry_is_pulled_instead(live_data: dict[str, Any]) -> None:
    account = live_data["account"]
    live.join(PLUGIN, "h:d_alex")
    live_data["woke"].clear()
    item = _item("card.big", {"x": 1}, time.time())
    del item["v"]
    assert not live._apply_data(account, SPACE, PLUGIN, ALEX, item)
    assert (account, SPACE, PLUGIN) in live_data["woke"]
    bad = _item("card.pip", {"hp": 1}, time.time())
    bad["sha"] = "0" * 64  # damaged: never lands
    assert not live._apply_data(account, SPACE, PLUGIN, ALEX, bad) and PluginData(PLUGIN).get("card.pip") is None


def test_members_of_a_live_group_never_lock_each_other_out(live_data: dict[str, Any]) -> None:
    account = live_data["account"]
    unit = "doc:card.pip"
    space_vcs.lock_put(account, SPACE, PLUGIN, unit, name="Pip", holder_user="u_alex", holder_name="Alex",
                       holder_device="d_alex", lease_left=60)
    with pytest.raises(scopes.LockedOut):  # not live: Alex's lock holds as before
        PluginData(PLUGIN).put("card.pip", {"hp": 1})
    live.join(PLUGIN, "h:d_alex")
    _roster(account, _on("d_alex", "Alex", "h:d_alex", 1.0))
    assert live.group_devices(PLUGIN, account, SPACE) == {"d_alex"}
    assert PluginData(PLUGIN).put("card.pip", {"hp": 1})["changed"]  # Alex is in the group
    PluginData(PLUGIN).put("card.zed", {"hp": 2})
    assert space_vcs.lock_request_get(account, SPACE, PLUGIN, "doc:card.zed") is None  # no auto lock asked for
    space_vcs.lock_put(account, SPACE, PLUGIN, "doc:card.ben", name="Ben", holder_user="u_ben", holder_name="Ben",
                       holder_device="d_ben", lease_left=60)
    with pytest.raises(scopes.LockedOut):  # Ben isn't in the group: his lock still holds
        PluginData(PLUGIN).put("card.ben", {"hp": 3})


def test_every_process_sees_where_the_app_is_live(live_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from backend.store.repos import kv

    account = live_data["account"]
    live.join(PLUGIN, "h:d_alex")
    assert live.room_anywhere(PLUGIN, account, SPACE) == "h:d_alex"
    doc = kv.get_doc("workspace_state", live.ROOM_KEY + PLUGIN)
    assert doc["room"] == "h:d_alex" and doc["pid"] == os.getpid()
    with live._lock:
        live._live.clear()  # another process: nothing live in it, the app's room is read
    kv.set_doc("workspace_state", live.ROOM_KEY + PLUGIN, {**doc, "pid": os.getppid()})  # a running app
    assert live.room_anywhere(PLUGIN, account, SPACE) == "h:d_alex"
    kv.set_doc("workspace_state", live.ROOM_KEY + PLUGIN, {**doc, "pid": 2 ** 31 - 7})  # an app that is gone
    assert live.room_anywhere(PLUGIN, account, SPACE) == ""
    assert live.group_devices(PLUGIN, account, SPACE) is None


def test_data_live_is_checked_in_the_manifest() -> None:
    from backend.uefn_plugins.store import data_live, manifest_data_errors

    assert data_live({"data_live": True}) and not data_live({"data_live": True, "data_sharing": False})
    assert any('"data_live"' in e for e in manifest_data_errors({"data_live": "yes"}))
    assert any('"data_live"' in e for e in manifest_data_errors({"data_live": True, "data_sharing": False}))
    assert not manifest_data_errors({"data_live": True, "data_sharing": True})


# --------------------------------------------------------------------------- the page


def test_panel_pages_get_the_pointer_script() -> None:
    from backend.uefn_plugins.ui_kit import LIVE_PRESENCE_SCRIPT
    from backend.uefn_plugins.webview import with_panel_error_script

    out = with_panel_error_script(b"<!doctype html><html><head></head><body></body></html>")
    assert LIVE_PRESENCE_SCRIPT.encode() in out
    for need in ("live.pointer", "live.select", "live.hold", "ducky.hold", "live.state", "live.message", "live.peers",
                 "sync.state", "pointer-events:none"):
        assert need in LIVE_PRESENCE_SCRIPT, need
