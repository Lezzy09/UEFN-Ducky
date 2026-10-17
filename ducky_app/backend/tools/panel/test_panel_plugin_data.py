"""The agents' team tools against a fake team server: ``ducky_team_status`` says who is in
a plugin's team copy and what they do, what is locked, what waits to go out or come in,
and what conflicts; ``ducky_team_lock`` takes and releases a lock (someone else's answers
who holds it); ``ducky_plugin_data_scope`` reports the same for a shared copy, and only
the copy for Local.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

# Every seal/open is DPAPI: these checks need Windows.
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")

from backend.tools.panel.panel_plugin_data import ducky_plugin_data_scope, ducky_team_lock, ducky_team_status
from backend.uefn_plugins import spaces, test_scopes, vcs_engine
from backend.uefn_plugins.ledger import LockUnit

account_keys = test_scopes.account_keys
who = test_scopes.who
team_pc = test_scopes.team_pc
TEAM = "cards"


class Team(spaces.Provider):
    """Every plugin is on the new sync, through Ana's client of the fake server."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def enabled(self) -> bool:
        return True

    def ledger(self, account: str, space_id: str, plugin: str) -> Any:
        return self.backend


@pytest.fixture
def team(team_pc):
    pc, ben, world = team_pc
    spaces.install_for_tests(Team(pc.backend))
    yield pc, ben, world
    spaces.reset_for_tests()


def test_team_status_says_who_does_what_what_is_locked_waiting_and_in_conflict(team) -> None:
    pc, ben, _ = team
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 3})
    pc.data.put("card.pip", {"hp": 2})
    assert pc.run()["conflicts"] == 1
    ben.client.lock("spaceT", TEAM, [LockUnit("doc:card.zed", "Zed")], "best", {})
    editing = [{"unitName": "Zed", "actor": "agent", "ducky": "Builder", "since": 5.0}]
    ben.client.beat("spaceT", {"label": "Ben's PC", "plugins": {TEAM: {"viewing": True, "editing": editing}}})
    assert vcs_engine.beat(pc.account, "spaceT", pc.backend, [TEAM], force=True)["ok"]
    pc.data.put("card.new", {"v": 1})
    ben.put_doc("card.ben", {"v": 1})
    vcs_engine.refresh(pc.account, "spaceT", [TEAM], pc.backend)

    out = json.loads(ducky_team_status(TEAM))
    assert (out["ok"], out["plugin"], out["state"], out["scope"]["kind"], out["mode"]) == (
        True, TEAM, "ok", "shared", "auto")
    assert out["people"] == [{"name": "Ben", "device": "Ben's PC", "doing": ["ducky Builder editing Zed"]}]
    (lock,) = out["locks"]
    assert (lock["unit"], lock["name"], lock["holder"]) == ("doc:card.zed", "Zed", "Ben")
    assert 290 <= lock["leaseLeft"] <= 300
    assert (out["head"], out["pending"], out["incoming"]) == (2, 1, 1)
    assert out["conflicts"] == [{"kind": "doc", "key": "card.pip", "reason": "changed", "by": "Ben"}]
    assert out["notSent"] == []

    same = json.loads(ducky_plugin_data_scope(TEAM))
    assert same == {k: v for k, v in out.items() if k != "plugin"}


def test_team_lock_takes_and_releases_and_names_the_holder(team) -> None:
    pc, ben, world = team
    got = json.loads(ducky_team_lock(TEAM, "card.pip"))
    assert (got["ok"], got["state"], got["unit"]) == (True, "granted", "doc:card.pip")
    theirs = ben.client.lock("spaceT", TEAM, [LockUnit("doc:card.pip")], "best", {})
    assert type(theirs["doc:card.pip"]).__name__ == "LockInfo"
    pc.data.put("card.pip", {"hp": 4})  # this PC holds it: its writes go ahead
    holds = json.loads(ducky_team_status(TEAM))["locks"]
    assert [(lk["unit"], lk["holder"]) for lk in holds] == [("doc:card.pip", "you")]
    assert json.loads(ducky_team_lock(TEAM, "doc:card.pip", "release"))["ok"]
    assert world.server.space("spaceT").locks == {}

    ben.client.lock("spaceT", TEAM, [LockUnit("doc:card.zed", "Zed")], "best", {})
    taken = json.loads(ducky_team_lock(TEAM, "card.zed"))
    assert (taken["ok"], taken["state"], taken["holder"], taken["error"]) == (False, "locked", "Ben", "Locked by Ben")
    assert json.loads(ducky_team_lock(TEAM, "card.zed", "break")) == {
        "ok": False, "error": "action must be acquire or release"}
    assert json.loads(ducky_team_lock("Bad Id", "x"))["ok"] is False


def test_a_local_copy_reports_only_where_its_data_lives(who) -> None:
    who.be("ana@x.org")
    out = json.loads(ducky_plugin_data_scope("brainrot-tcg"))
    assert out == {"ok": True, "state": "ok", "scope": {"kind": "personal", "label": "Local", "spaceId": "",
                                                         "readOnly": False}}
    assert json.loads(ducky_team_status("brainrot-tcg"))["scope"]["kind"] == "personal"
    refused = json.loads(ducky_team_lock("brainrot-tcg", "card.pip"))
    assert refused == {"ok": False, "error": "brainrot-tcg's data is Local, on this PC only."}
