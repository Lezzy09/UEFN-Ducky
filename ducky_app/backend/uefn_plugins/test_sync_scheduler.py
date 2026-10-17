"""The background sync of shared spaces, driven by a fake clock and a fake provider.

Writes come from another sqlite connection (their own thread), the way the MCP bridge
process writes: the scheduler only sees them through ``PRAGMA data_version``. Checks:
a round 5 s after the last write and at most one per 30 s; a round every 60 s while a
linked panel or the Workflows view is on screen, else every 15 minutes; failed rounds
retried after 1, 5, then 15 minutes, recorded on the space while the next tick still
runs; changes queued again without a write keep rounds coming while each sends some;
rounds of one space never overlap across processes; the exit flush is bounded; the
daemon never runs in the MCP bridge.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from backend.store.repos import plugin_data as repo
from backend.uefn_plugins import spaces, sync_scheduler
from backend.uefn_plugins import test_scopes
from backend.uefn_plugins.sync_scheduler import IDLE_EVERY_S, Scheduler

who = test_scopes.who

PLUGIN = "brainrot-tcg"
T = 1_000_000.0


class Recorder(spaces.Provider):
    """Rounds as they were asked for: ``(space, force)``. ``fail``: spaces whose round raises."""

    def __init__(self) -> None:
        self.rounds: list[tuple[str, bool]] = []
        self.fail: dict[str, Exception] = {}

    def sync(self, account: str, space_id: str, *, force: bool = False) -> dict[str, Any]:
        self.rounds.append((space_id, force))
        if space_id in self.fail:
            raise self.fail[space_id]
        return {"state": "ok", "changed": [], "error": ""}


class Clock:
    def __init__(self) -> None:
        self.now = T

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The scheduler's clock, and the one rows are stamped with (``updated``)."""
    c = Clock()
    monkeypatch.setattr(repo, "time", SimpleNamespace(time=c))
    return c


@pytest.fixture
def provider() -> Recorder:
    impl = Recorder()
    spaces.install_for_tests(impl)
    yield impl
    spaces.reset_for_tests()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from frontend.ui_web import agent_modes

    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(agent_modes, "push_ui_event", seen.append)
    return seen


def scheduler(clock: Clock) -> Scheduler:
    return Scheduler(clock=clock, spawn=lambda fn: fn())  # rounds run inline


def elsewhere(fn: Any) -> None:
    """``fn`` on its own thread, so its own sqlite connection: like the MCP bridge."""
    box: dict[str, BaseException] = {}

    def run() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            box["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(10)
    if "error" in box:
        raise box["error"]


def link(aid: str, space: str, plugin: str = PLUGIN) -> None:
    repo.link_set(aid, plugin, space)
    repo.sync_put(aid, space, label=space, synced_at=1.0)


def write(aid: str, space: str, key: str, clock: Clock, at: float) -> None:
    clock.now = at
    elsewhere(lambda: repo.put(aid, space, PLUGIN, "doc", key, value="v", size=1, sha256=key, dirty=True))


def ticks(sched: Scheduler, clock: Clock, *at: float) -> list[list[str]]:
    out = []
    for when in at:
        clock.now = when
        out.append(sched.tick())
    return out


def test_a_write_elsewhere_starts_a_round_5s_after_the_last_write_at_most_every_30s(
    who, clock: Clock, provider: Recorder, events
) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    sched = scheduler(clock)
    assert sched.tick() == ["spaceT"] and provider.rounds == [("spaceT", False)]  # the round at start

    write(aid, "spaceT", "card.a", clock, T + 100)
    assert ticks(sched, clock, T + 100, T + 104.9) == [[], []]
    assert ticks(sched, clock, T + 105) == [["spaceT"]]
    assert provider.rounds[-1] == ("spaceT", True)  # changes to send beat the provider's minute limit

    # Another write right after: 5 s later would be too soon, the 30 s cap holds it.
    write(aid, "spaceT", "card.b", clock, T + 106)
    assert ticks(sched, clock, T + 111, T + 134.9) == [[], []]
    assert ticks(sched, clock, T + 135) == [["spaceT"]]

    # Writes 3 s apart: one round, 5 s after the last of them.
    write(aid, "spaceT", "card.c", clock, T + 300)
    assert ticks(sched, clock, T + 300) == [[]]
    write(aid, "spaceT", "card.d", clock, T + 303)
    assert ticks(sched, clock, T + 305, T + 307.9, T + 308) == [[], [], ["spaceT"]]
    assert provider.rounds.count(("spaceT", True)) == 3
    assert events and events[-1] == {"type": "plugin_scope_changed", "plugins": [], "synced": True}


def test_rounds_every_60s_while_a_linked_panel_or_the_workflows_view_is_on_screen_else_every_15_min(
    who, clock: Clock, provider: Recorder, events
) -> None:
    from backend.uefn_plugins.panel_presence import note_panel

    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    repo.sync_put(aid, "spaceW", label="Workflows only", synced_at=1.0)  # a space with no linked plugin
    sched = scheduler(clock)
    assert ticks(sched, clock, T) == [["spaceT"]]
    assert ticks(sched, clock, T + 60, T + IDLE_EVERY_S - 1) == [[], []]
    assert ticks(sched, clock, T + IDLE_EVERY_S) == [["spaceT"]]
    assert provider.rounds[-1] == ("spaceT", False)  # a pull the provider may skip

    start = T + IDLE_EVERY_S
    clock.now = start + 1
    elsewhere(lambda: note_panel("main", f"plugin:{PLUGIN}:main", visible=True))
    assert ticks(sched, clock, start + 6, start + 59) == [[], []]
    assert ticks(sched, clock, start + 60, start + 119, start + 120) == [["spaceT"], [], ["spaceT"]]
    assert "spaceW" not in sched.spaces  # nothing of this account's lives there yet

    # The Workflows view on screen: every space this account keeps workflows in, each minute.
    clock.now = start + 121
    elsewhere(lambda: note_panel("main", "plugin:ducky.automations:workflows", visible=True))
    assert ticks(sched, clock, start + 126) == [["spaceW"]]
    assert ticks(sched, clock, start + 180, start + 185, start + 186) == [["spaceT"], [], ["spaceW"]]

    # Both off screen: back to every 15 minutes.
    clock.now = start + 187
    elsewhere(lambda: note_panel("main", f"plugin:{PLUGIN}:main", visible=False))
    elsewhere(lambda: note_panel("main", "plugin:ducky.automations:workflows", visible=False, open_=False))
    assert ticks(sched, clock, start + 192, start + 180 + IDLE_EVERY_S - 1) == [[], []]
    assert ticks(sched, clock, start + 180 + IDLE_EVERY_S) == [["spaceT"]]
    assert "spaceW" not in sched.spaces


def test_a_round_that_raises_is_recorded_and_retried_after_1_5_then_15_minutes(
    who, clock: Clock, provider: Recorder, events
) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    link(aid, "spaceU", plugin="forge")
    provider.fail["spaceT"] = KeyError("rev")
    sched = scheduler(clock)
    assert sorted(sched.tick()) == ["spaceT", "spaceU"]  # the other space still synced
    st = repo.sync_get(aid, "spaceT")
    assert st["state"] == "error" and "KeyError" in st["error"]
    assert repo.sync_get(aid, "spaceU")["state"] == "ok"

    def failing_rounds() -> list[float]:
        at = []
        for step in range(1, 2 * 3600):
            clock.now = T + step
            if "spaceT" in sched.tick():
                at.append(step)
        return at

    assert failing_rounds()[:5] == [60, 360, 1260, 2160, 3060]

    # It works again: back to the usual cadence, and the space says ok.
    provider.fail.clear()
    clock.now += 900
    assert "spaceT" in sched.tick()
    assert sched.spaces["spaceT"].fails == 0 and sched.spaces["spaceT"].state == "ok"


def test_a_round_that_worked_elsewhere_ends_the_backoff(who, clock: Clock, provider: Recorder, events) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    provider.fail["spaceT"] = KeyError("rev")
    sched = scheduler(clock)
    assert ticks(sched, clock, T, T + 61) == [["spaceT"], ["spaceT"]]
    assert sched.spaces["spaceT"].fails == 2  # next try in 5 minutes
    provider.fail.clear()
    clock.now = T + 100
    # The scope bar's round worked meanwhile (any process): the usual cadence again.
    elsewhere(lambda: repo.sync_put(aid, "spaceT", state="ok", error="", called_at=T + 100))
    assert ticks(sched, clock, T + 100, T + 400, T + 999) == [[], [], []]
    assert ticks(sched, clock, T + 1000) == [["spaceT"]]


def test_a_space_failing_on_this_pc_retries_a_queued_write_on_the_backoff_not_every_30s(
    who, clock: Clock, provider: Recorder, events
) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    provider.fail["spaceT"] = OSError("offline")
    sched = scheduler(clock)
    assert sched.tick() == ["spaceT"]
    write(aid, "spaceT", "card.a", clock, T + 10)
    assert ticks(sched, clock, T + 15, T + 40, T + 59) == [[], [], []]  # waits out the minute
    assert ticks(sched, clock, T + 60) == [["spaceT"]]
    assert provider.rounds[-1] == ("spaceT", True)


def test_no_provider_no_rounds_and_one_round_per_space_when_it_arrives(who, clock: Clock, events) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    sched = scheduler(clock)
    assert sched.tick() == [] and sched.spaces == {}
    impl = Recorder()
    spaces.install_for_tests(impl)
    try:
        clock.now += 1
        assert sched.tick() == ["spaceT"] and impl.rounds == [("spaceT", False)]
    finally:
        spaces.reset_for_tests()


def test_flush_sends_queued_changes_and_returns_within_its_timeout(who, monkeypatch, events) -> None:
    aid = who.be("ana@x.org")
    link(aid, "spaceT")
    link(aid, "spaceU", plugin="forge")
    repo.put(aid, "spaceT", PLUGIN, "doc", "card.a", value="v", size=1, sha256="a", dirty=True)
    gate = threading.Event()

    class Hung(Recorder):
        def sync(self, account: str, space_id: str, *, force: bool = False) -> dict[str, Any]:
            self.rounds.append((space_id, force))
            gate.wait(30)
            return {"state": "ok", "changed": [], "error": ""}

    impl = Hung()
    spaces.install_for_tests(impl)
    try:
        began = time.monotonic()
        assert sync_scheduler.flush(timeout=1.0) == 1
        assert time.monotonic() - began < 3.0
        assert impl.rounds == [("spaceT", True)]  # only the space with something to send
    finally:
        gate.set()
        spaces.reset_for_tests()
    assert sync_scheduler.flush(timeout=1.0) == 0  # no provider: nothing to do


def test_hard_exit_flushes_for_5s_before_plugins_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    from frontend import boot_report
    from frontend.ui_web import shutdown

    order: list[str] = []
    monkeypatch.setattr(shutdown, "_exit_started", False)
    monkeypatch.setattr(boot_report, "mark", lambda *a, **k: None)
    monkeypatch.setattr(sync_scheduler, "flush", lambda timeout=5.0: order.append(f"flush {timeout:g}") or 0)
    for name in ("_stop_all_agents", "_stop_cpu_workers", "_stop_all_terminals", "_stop_mcp_plugins",
                 "release_panel_process", "_kill_sibling_processes", "_spawn_kill_uefn_processes",
                 "_terminate_process"):
        monkeypatch.setattr(shutdown, name, lambda name=name: order.append(name))
    shutdown.hard_exit()
    assert order.index("flush 5") == order.index("_stop_mcp_plugins") - 1
    assert order[-1] == "_terminate_process"


def test_never_in_the_mcp_bridge(monkeypatch: pytest.MonkeyPatch, who) -> None:
    monkeypatch.setenv("UEFN_DUCKY_MCP_BRIDGE", "1")
    impl = Recorder()
    spaces.install_for_tests(impl)
    try:
        aid = who.be("ana@x.org")
        repo.put(aid, "spaceT", PLUGIN, "doc", "card.a", value="v", size=1, sha256="a", dirty=True)
        assert sync_scheduler.start() is False
        assert sync_scheduler.flush(timeout=1.0) == 0 and impl.rounds == []
    finally:
        spaces.reset_for_tests()


class Batches(spaces.Provider):
    """Sends at most two queued changes per round (a provider's batch), stamping each round
    as a real one does; never sends the ``stuck`` keys."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.rounds: list[tuple[str, bool]] = []
        self.stuck: set[str] = set()

    def sync(self, account: str, space_id: str, *, force: bool = False) -> dict[str, Any]:
        self.rounds.append((space_id, force))
        repo.sync_put(account, space_id, called_at=self.clock())
        for row in [r for r in repo.dirty(account, space_id, 100) if r["key"] not in self.stuck][:2]:
            repo.mark_pushed(account, space_id, row["plugin_id"], row["kind"], row["key"], rev=1, sha256=row["sha256"])
        return {"state": "ok", "changed": [], "error": ""}


def test_changes_queued_again_keep_rounds_coming_while_each_sends_some(who, clock: Clock, events) -> None:
    impl = Batches(clock)
    spaces.install_for_tests(impl)
    try:
        aid = who.be("ana@x.org")
        link(aid, "spaceT")
        clock.now = T - 3600
        for key in ("a", "b", "c", "d", "e"):
            repo.put(aid, "spaceT", PLUGIN, "doc", key, value="v", size=1, sha256=key, dirty=False, rev=3)
        sched = scheduler(clock)
        assert ticks(sched, clock, T) == [["spaceT"]]  # the round at start: nothing to send
        # Upload my copy queues all five again with no new write, and its own round sends two.
        clock.now = T + 100
        elsewhere(lambda: repo.settle_reset(aid, "spaceT", keep=True))
        elsewhere(lambda: sync_scheduler.run_round(aid, "spaceT", force=True))
        assert repo.count_dirty(aid, "spaceT") == 3
        # Before, the rest went one batch per 15-minute round. Now the next comes 30 s after.
        assert ticks(sched, clock, T + 105, T + 129.9, T + 130) == [[], [], ["spaceT"]]
        assert impl.rounds[-1] == ("spaceT", True) and repo.count_dirty(aid, "spaceT") == 1
        assert ticks(sched, clock, T + 136, T + 159.9, T + 160) == [[], [], ["spaceT"]]
        assert repo.count_dirty(aid, "spaceT") == 0
        assert ticks(sched, clock, T + 166, T + 300) == [[], []]  # all sent: back to the cadence

        # A change the provider keeps skipping: its round sent nothing, so no round follows.
        impl.stuck.add("z")
        write(aid, "spaceT", "z", clock, T + 400)
        assert ticks(sched, clock, T + 405) == [["spaceT"]]
        assert ticks(sched, clock, T + 411, T + 435, T + 500, T + 900) == [[], [], [], []]
        assert repo.count_dirty(aid, "spaceT") == 1
    finally:
        spaces.reset_for_tests()


def test_rounds_of_one_space_never_overlap_across_processes(who, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows byte-range locks hold per handle, so another thread's handle stands in for the
    # MCP bridge process here.
    impl = Recorder()
    spaces.install_for_tests(impl)
    held, release = threading.Event(), threading.Event()

    def bridge_round() -> None:
        with sync_scheduler._round_lock("acc", "spaceT", 0) as got:
            assert got
            held.set()
            release.wait(10)

    worker = threading.Thread(target=bridge_round)
    worker.start()
    try:
        assert held.wait(5)
        assert sync_scheduler.run_round("acc", "spaceT", force=False) == {"state": "busy", "changed": [], "error": ""}
        assert sync_scheduler.run_round("acc", "spaceU", force=False)["state"] == "ok"  # other spaces go on
        monkeypatch.setattr(sync_scheduler, "ROUND_WAIT_S", 0.5)
        assert sync_scheduler.run_round("acc", "spaceT", force=True)["state"] == "busy"  # waited, then gave up
        assert impl.rounds == [("spaceU", False)]
        monkeypatch.setattr(sync_scheduler, "ROUND_WAIT_S", 10.0)
        threading.Timer(0.3, release.set).start()
        assert sync_scheduler.run_round("acc", "spaceT", force=True)["state"] == "ok"  # ran once it was free
        assert impl.rounds[-1] == ("spaceT", True)
    finally:
        release.set()
        worker.join(10)
        spaces.reset_for_tests()
