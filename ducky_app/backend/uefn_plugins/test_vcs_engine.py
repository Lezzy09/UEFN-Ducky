"""The version engine against FakeLedger: this PC (Ana, a real ducky.db) and a teammate
(Ben, a client of the same fake server).

Pushes and pulls round-trip; disjoint edits merge and push as merged; a clash keeps mine
in conflicts while theirs is current; files keep both; edit against delete; a crash
between upload and commit replays the same changeset and loses no later edit; writers in
another process or on another connection racing the apply lose nothing; resync; locks
(successor, locked out, broken); refused, offline, manual mode, groups, blocked
downloads, workflows, on_change, presence, restore and undo, unsent changes of a lost
space saved to Local.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# Every seal/open is DPAPI: these checks need Windows.
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")

from backend.store.repos import plugin_data as repo
from backend.store.repos import space_vcs
from backend.uefn_plugins import data_crypto, ledger_conformance as conf, scopes, vcs_engine
from backend.uefn_plugins.ledger import Committed, LockUnit, Offline
from backend.uefn_plugins.scopes import PluginData

SPACE, PLUGIN, WF = "spaceT", "cards", "ducky.automations"
APP_DIR = str(Path(__file__).resolve().parents[2])


@pytest.fixture
def aid(monkeypatch: pytest.MonkeyPatch):
    """Ana signed in, ``cards`` linked to the space, already pulled once."""
    from frontend import duckyos_account

    key = "https://uefnducky.org|ana@example.com"
    data_crypto.reset_for_tests()
    monkeypatch.setattr(duckyos_account, "account_key", lambda blob=None: key)
    monkeypatch.setattr(data_crypto, "_fetch_adk", lambda: hashlib.sha256(b"adk/" + key.encode()).digest())
    account = scopes.account_id()
    repo.link_set(account, PLUGIN, SPACE)
    repo.sync_put(account, SPACE, label="Alpha", synced_at=time.time())
    yield account
    scopes.forget_change_listeners(PLUGIN)
    data_crypto.reset_for_tests()


@pytest.fixture
def world():
    w = conf.FakeWorld()
    yield w
    w.server.rmtree()


class PC:
    """This PC: Ana's engine rounds on the real database."""

    def __init__(self, world: conf.FakeWorld, account: str) -> None:
        self.account = account
        self.backend = world.server.client("u_ana", vcs_engine.device_id(), name="Ana")
        self.data = PluginData(PLUGIN)

    def run(self, plugin: str = PLUGIN, backend: Any = None, **kw: Any) -> dict[str, Any]:
        return vcs_engine.run(self.account, SPACE, plugin, backend or self.backend, force=True, **kw)

    def row(self, key: str, kind: str = "doc", plugin: str = PLUGIN) -> dict[str, Any] | None:
        return space_vcs.row(None, self.account, SPACE, plugin, kind, key)

    def put_raw(self, plugin: str, key: str, value: Any) -> None:
        raw = scopes.encode_doc(value)
        repo.put(self.account, SPACE, plugin, "doc", key, value=data_crypto.seal_text(raw.decode(), self.account),
                 size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), dirty=True)

    def get_raw(self, plugin: str, key: str) -> Any:
        r = self.row(key, plugin=plugin)
        return json.loads(data_crypto.open_text(r["value"], self.account)) if r and r["value"] else None


class Ben:
    """The teammate: commits straight to the server."""

    def __init__(self, world: conf.FakeWorld) -> None:
        self.server = world.server
        self.client = world.server.client("u_ben", "d_ben", name="Ben")

    def seq_of(self, kind: str, key: str, plugin: str = PLUGIN) -> int:
        item = self.server.space(SPACE).repo(plugin).items.get((kind, key))
        return item.seq if item else 0

    def _push(self, plugin: str, *items: Any, **kw: Any) -> int:
        out = self.client.push(SPACE, plugin, conf.changeset(*items, **kw))
        assert isinstance(out, Committed), out
        return out.seq

    def put_doc(self, key: str, value: Any, plugin: str = PLUGIN, **kw: Any) -> int:
        item = conf.put_item("doc", key, scopes.encode_doc(value), base=self.seq_of("doc", key, plugin))
        return self._push(plugin, item, **kw)

    def put_file(self, path: str, data: bytes) -> int:
        return self._push(PLUGIN, conf.put_item("asset", path, data, base=self.seq_of("asset", path)))

    def delete(self, kind: str, key: str) -> int:
        return self._push(PLUGIN, conf.del_item(kind, key, base=self.seq_of(kind, key)))

    def doc(self, key: str, plugin: str = PLUGIN) -> Any:
        item = self.server.space(SPACE).repo(plugin).items.get(("doc", key))
        return json.loads(item.content) if item and item.op == "put" else None

    def head(self, plugin: str = PLUGIN) -> int:
        return self.server.space(SPACE).repo(plugin).head


@pytest.fixture
def pc(world: conf.FakeWorld, aid: str) -> PC:
    return PC(world, aid)


@pytest.fixture
def ben(world: conf.FakeWorld) -> Ben:
    return Ben(world)


def _mine(c: dict[str, Any], account: str) -> Any:
    return json.loads(data_crypto.open_text(c["mine_value"], account))


# --------------------------------------------------------------------------- push + pull


def test_changes_go_out_and_come_in(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1, "name": "Pip"})
    pc.data.put("card.zed", {"hp": 2})
    pc.data.put_file("img/pip.png", b"\x89PNG-1")
    out = pc.run()
    assert (out["state"], out["pushed"]) == ("ok", 1)
    assert ben.head() == 1 and ben.doc("card.pip") == {"hp": 1, "name": "Pip"}
    for key, kind in (("card.pip", "doc"), ("card.zed", "doc"), ("img/pip.png", "asset")):
        r = pc.row(key, kind)
        assert (r["dirty"], r["rev"]) == (0, 1), key
    assert space_vcs.base_get(pc.account, SPACE, PLUGIN, "card.pip")["seq"] == 1
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 1

    ben.put_doc("card.zed", {"hp": 3})
    ben.put_file("img/zed.png", b"Z")
    ben.delete("doc", "card.pip")
    out = pc.run()
    assert (out["state"], out["changed"], out["pulled"], out["pushed"]) == ("ok", [PLUGIN], 3, 0)
    assert pc.data.get("card.zed") == {"hp": 3}
    assert pc.data.get_file("img/zed.png") == b"Z"
    assert pc.data.get("card.pip") is None and pc.row("card.pip") is None
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 4
    assert space_vcs.unit_seqs(pc.account, SPACE, PLUGIN, ["doc:card.zed"]) == {"doc:card.zed": 2}
    assert repo.sync_get(pc.account, SPACE)["synced_at"] > 0


def test_disjoint_edits_merge_and_go_out_as_merged(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1, "name": "Pip"})
    pc.run()
    ben.put_doc("card.pip", {"hp": 1, "name": "Pipo"})
    pc.data.put("card.pip", {"hp": 2, "name": "Pip"})
    out = pc.run()
    assert out["state"] == "ok" and out["conflicts"] == 0
    assert pc.data.get("card.pip") == {"hp": 2, "name": "Pipo"}
    assert ben.doc("card.pip") == {"hp": 2, "name": "Pipo"} and ben.head() == 3
    assert ben.client.history(SPACE, PLUGIN).entries[0].message == "Merged with Ben's change"
    assert (pc.row("card.pip")["dirty"], pc.row("card.pip")["rev"]) == (0, 3)


def test_a_clash_keeps_mine_as_a_conflict_while_theirs_is_current(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 3})
    pc.data.put("card.pip", {"hp": 2})
    out = pc.run()
    assert out["conflicts"] == 1 and ben.head() == 2  # mine didn't go over theirs
    assert pc.data.get("card.pip") == {"hp": 3}
    r = pc.row("card.pip")
    assert (r["sync_state"], r["dirty"], r["rev"]) == ("conflict", 0, 2)
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.pip")
    assert _mine(c, pc.account) == {"hp": 2} and (c["theirs_by"], c["theirs_seq"], c["reason"]) == ("Ben", 2, "changed")
    assert vcs_engine.status(pc.account, SPACE, PLUGIN)["conflicts"][0]["key"] == "card.pip"
    assert pc.run()["pushed"] == 0  # held until the person picks

    assert vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine") == {"ok": True}
    assert pc.data.get("card.pip") == {"hp": 2}
    assert pc.run()["pushed"] == 1 and ben.doc("card.pip") == {"hp": 2}
    assert space_vcs.conflicts(pc.account, SPACE) == [] and pc.row("card.pip")["dirty"] == 0


def test_a_file_changed_on_both_sides_keeps_both(pc: PC, ben: Ben) -> None:
    pc.data.put_file("art/a.png", b"v1")
    pc.run()
    ben.put_file("art/a.png", b"theirs")
    pc.data.put_file("art/a.png", b"mine")
    assert pc.run()["conflicts"] == 1
    assert pc.data.get_file("art/a.png") == b"theirs"
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "asset", "art/a.png")
    side = Path(c["mine_path"])
    assert side.parent == scopes.plugin_dir({"account": pc.account, "id": SPACE}, PLUGIN) / "conflicts"
    assert side.read_bytes() != b"mine"  # sealed at rest, like every copy
    assert data_crypto.open_bytes(side.read_bytes(), pc.account) == b"mine"
    assert vcs_engine.resolve(pc.account, SPACE, PLUGIN, "asset", "art/a.png", "theirs") == {"ok": True}
    assert not side.exists() and pc.row("art/a.png", "asset")["sync_state"] == ""
    assert pc.data.get_file("art/a.png") == b"theirs"


def test_an_edit_against_a_delete_waits_for_the_person(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.data.put("card.zed", {"hp": 1})
    pc.run()
    pip_gone = ben.delete("doc", "card.pip")
    ben.delete("doc", "card.zed")
    pc.data.put("card.pip", {"hp": 5})
    pc.data.put("card.zed", {"hp": 6})
    out = pc.run()
    assert out["conflicts"] == 2 and out["pushed"] == 0
    r = pc.row("card.pip")
    assert (r["sync_state"], r["dirty"], r["rev"]) == ("conflict", 1, pip_gone)
    assert "Ben deleted this" in r["sync_error"] and pc.data.get("card.pip") == {"hp": 5}
    assert space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.pip")["reason"] == "deleted"

    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine")  # Restore mine
    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.zed", "theirs")  # Accept delete
    assert pc.run()["pushed"] == 1
    assert ben.doc("card.pip") == {"hp": 5} and ben.doc("card.zed") is None
    assert pc.row("card.zed") is None and pc.data.get("card.zed") is None


def test_a_change_deleted_on_the_server_while_deleted_here_settles(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.delete("doc", "card.pip")
    pc.data.delete("card.pip")
    out = pc.run()
    assert out["conflicts"] == 0 and pc.row("card.pip") is None and ben.head() == 2


def test_a_delete_here_against_their_edit_keeps_theirs_until_the_person_picks(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 7})
    pc.data.delete("card.pip")
    assert pc.run()["conflicts"] == 1
    assert pc.data.get("card.pip") == {"hp": 7}
    assert space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.pip")["reason"] == "mine_deleted"
    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine")  # delete it again
    assert pc.run()["pushed"] == 1 and ben.doc("card.pip") is None and pc.row("card.pip") is None


# --------------------------------------------------------------------------- crashes and races


class _LostAnswer:
    """The commit lands on the server, the answer never comes back."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def push(self, space: str, plugin: str, cs: Any) -> Any:
        self.inner.push(space, plugin, cs)
        return Offline("the answer got lost")


def test_a_crash_between_upload_and_commit_replays_and_loses_no_later_edit(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    out = pc.run(backend=_LostAnswer(pc.backend))
    assert out["state"] == "offline" and ben.head() == 1  # it did land
    pending = space_vcs.cs_open(pc.account, SPACE, PLUGIN)
    assert len(pending) == 1 and pending[0]["state"] == "pushing" and pc.row("card.pip")["dirty"] == 1
    pc.data.put("card.pip", {"hp": 2})  # edited before the next round
    out = pc.run()
    assert out["state"] == "ok"
    space = ben.server.space(SPACE)
    assert pending[0]["cs_id"] in space.csids  # the same changeset, answered as a replay
    assert ben.head() == 2 and ben.doc("card.pip") == {"hp": 2}  # the later edit went out on top
    assert [json.loads(v.content) for v in space.repo(PLUGIN).versions[("doc", "card.pip")]] == [{"hp": 1}, {"hp": 2}]
    r = pc.row("card.pip")
    assert (r["dirty"], r["rev"]) == (0, 2) and space_vcs.cs_open(pc.account, SPACE) == []


def test_a_changeset_written_before_a_crash_goes_out_once_with_its_id(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    ctx = vcs_engine.Ctx(pc.account, SPACE, PLUGIN, pc.backend)
    assert vcs_engine._build(ctx, now=time.time()) == 1  # written, then the app died before the upload
    cs_id = space_vcs.cs_open(pc.account, SPACE, PLUGIN)[0]["cs_id"]
    assert pc.run()["pushed"] == 1
    assert ben.server.space(SPACE).csids == {cs_id: (PLUGIN, 1)} and ben.head() == 1


def test_a_writer_in_another_process_racing_the_apply_loses_nothing(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    pc.data.put("card.pip", {"hp": 1, "name": "Pip"})
    pc.run()
    ben.put_doc("card.pip", {"hp": 1, "name": "Pipo"})
    raw = scopes.encode_doc({"hp": 5, "name": "Pip"})
    sealed = data_crypto.seal_text(raw.decode(), pc.account)
    code = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from backend.store.repos import plugin_data\n"
        "a = sys.argv[2:]\n"
        "plugin_data.put(a[0], a[1], a[2], 'doc', a[3], value=a[4], size=int(a[5]), sha256=a[6], dirty=True)\n"
    )

    def bridge_writes_during_the_download(space: str, plugin: str, kind: str, key: str, seq: Any) -> None:
        world.server.hooks.pop("fetch", None)
        subprocess.run([sys.executable, "-c", code, APP_DIR, pc.account, SPACE, PLUGIN, "card.pip", sealed,
                        str(len(raw)), hashlib.sha256(raw).hexdigest()], check=True, env=dict(os.environ),
                       timeout=120)

    world.server.hooks["fetch"] = bridge_writes_during_the_download
    out = pc.run()
    assert "fetch" not in world.server.hooks and out["state"] == "ok"
    assert pc.data.get("card.pip") == {"hp": 5, "name": "Pipo"}  # the bridge's edit and Ben's, merged
    assert ben.doc("card.pip") == {"hp": 5, "name": "Pipo"}


def test_a_file_written_on_another_connection_during_the_download_is_kept(pc: PC, ben: Ben,
                                                                          world: conf.FakeWorld) -> None:
    pc.data.put_file("art/a.png", b"v1")
    pc.run()
    ben.put_file("art/a.png", b"theirs")

    def write_on_another_connection(*_: Any) -> None:
        world.server.hooks.pop("fetch", None)
        worker = threading.Thread(target=lambda: PluginData(PLUGIN).put_file("art/a.png", b"mine, late"))
        worker.start()
        worker.join(30)

    world.server.hooks["fetch"] = write_on_another_connection
    pc.run()
    assert pc.data.get_file("art/a.png") == b"theirs"
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "asset", "art/a.png")
    assert data_crypto.open_bytes(Path(c["mine_path"]).read_bytes(), pc.account) == b"mine, late"


def test_a_busy_writer_during_a_long_pull_loses_nothing(pc: PC, ben: Ben) -> None:
    for n in range(30):
        ben.put_doc(f"card.b{n}", {"n": n})
    errors: list[BaseException] = []

    def write() -> None:
        try:
            for n in range(30):
                PluginData(PLUGIN).put(f"card.w{n}", {"n": n})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=write)
    worker.start()
    pc.run(push=False)
    worker.join(60)
    assert not errors
    pc.run()
    assert pc.run()["state"] == "ok"
    for n in range(30):
        assert pc.data.get(f"card.b{n}") == {"n": n} and pc.data.get(f"card.w{n}") == {"n": n}
        assert ben.doc(f"card.w{n}") == {"n": n}
    assert repo.count_dirty(pc.account, SPACE) == 0


# --------------------------------------------------------------------------- resync, purge, groups, blocked


def test_a_pull_below_what_the_server_keeps_resyncs_every_item(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    for key in ("card.keep", "card.gone", "card.extra"):
        pc.data.put(key, {"v": 1})
    pc.data.put("card.mine", {"a": 1, "b": 1})
    pc.run()
    ben.put_doc("card.keep", {"v": 2})
    ben.delete("doc", "card.gone")
    ben.put_doc("card.new", {"v": 1})
    ben.put_doc("card.mine", {"a": 2, "b": 1})
    world.purge(SPACE, PLUGIN, "doc", "card.extra")
    world.trim(SPACE, PLUGIN, 5)
    pc.data.put("card.mine", {"a": 1, "b": 3})
    out = pc.run()
    assert out["state"] == "ok"
    assert pc.data.get("card.keep") == {"v": 2} and pc.data.get("card.new") == {"v": 1}
    assert pc.row("card.gone") is None and pc.row("card.extra") is None
    assert pc.data.get("card.mine") == {"a": 2, "b": 3} and ben.doc("card.mine") == {"a": 2, "b": 3}
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == ben.head() == 6


def test_an_edit_of_an_item_purged_for_good_is_an_edit_against_a_delete(pc: PC, ben: Ben,
                                                                        world: conf.FakeWorld) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    world.purge(SPACE, PLUGIN, "doc", "card.pip")
    pc.data.put("card.pip", {"hp": 2})
    out = pc.run()
    assert out["state"] == "ok" and ben.doc("card.pip") is None  # never made again silently
    r = pc.row("card.pip")
    assert (r["sync_state"], r["rev"]) == ("conflict", 0)
    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine")
    assert pc.run()["pushed"] == 1 and ben.doc("card.pip") == {"hp": 2}


def test_a_group_waits_for_its_last_part(pc: PC, ben: Ben) -> None:
    ben.put_doc("card.a", {"v": 1}, group="g1", part=1, last=False)
    out = pc.run(push=False)
    assert out["pulled"] == 0 and pc.data.get("card.a") is None
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 0
    ben.put_doc("card.b", {"v": 1}, group="g1", part=2, last=True)
    out = pc.run(push=False)
    assert out["pulled"] == 2 and pc.data.get("card.a") == {"v": 1} and pc.data.get("card.b") == {"v": 1}
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 2


def test_a_bad_download_is_set_aside_and_the_cursor_moves_on(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    ben.put_doc("card.a", {"v": 1})
    ben.put_doc("card.b", {"v": 1})
    world.server.bad.add((SPACE, PLUGIN, "doc", "card.a", 1))
    out = pc.run()
    assert out["state"] == "ok" and pc.data.get("card.b") == {"v": 1} and pc.data.get("card.a") is None
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 2
    blocked = space_vcs.blocked(pc.account, SPACE, PLUGIN)
    assert [(b["key"], b["seq"]) for b in blocked] == [("card.a", 1)] and "verify" in blocked[0]["error"]
    assert space_vcs.unit_seqs(pc.account, SPACE, PLUGIN, ["doc:card.a"]) == {"doc:card.a": 0}
    pc.run()
    assert space_vcs.blocked(pc.account, SPACE, PLUGIN)[0]["attempts"] == 1  # still waiting its turn
    world.server.bad.clear()
    space_vcs.blocked_retry_now(pc.account, SPACE, PLUGIN, "doc", "card.a")
    pc.run()
    assert pc.data.get("card.a") == {"v": 1} and space_vcs.blocked(pc.account, SPACE) == []


# --------------------------------------------------------------------------- locks


def test_rows_under_someone_elses_lock_wait_and_go_after_it_is_released(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.client.lock(SPACE, PLUGIN, [LockUnit("doc:card.pip", "card.pip")], "best", {"doc:card.pip": 1})
    pc.data.put("card.pip", {"hp": 2})
    pc.data.put("card.zed", {"hp": 1})
    out = pc.run()
    assert out["pushed"] == 1 and ben.doc("card.zed") == {"hp": 1} and ben.doc("card.pip") == {"hp": 1}
    r = pc.row("card.pip")
    assert (r["sync_state"], r["sync_error"]) == ("locked_out", "Locked by Ben")
    assert space_vcs.foreign_lock(pc.account, SPACE, PLUGIN, "doc:card.pip")["holder_name"] == "Ben"
    ben.client.unlock(SPACE, PLUGIN, ["doc:card.pip"])
    assert vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)["state"] == "ok"
    assert pc.row("card.pip")["sync_state"] == ""
    assert pc.run()["pushed"] == 1 and ben.doc("card.pip") == {"hp": 2}


def test_a_lock_on_a_unit_this_pc_is_behind_on_pulls_first(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 2})
    got = vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, [("doc:card.pip", "card.pip")])
    assert got["doc:card.pip"]["ok"] and got["doc:card.pip"]["state"] == "granted"
    assert pc.data.get("card.pip") == {"hp": 2}
    mine = space_vcs.locks(pc.account, SPACE, PLUGIN)
    assert [(lk["unit"], lk["mine"], lk["reason"]) for lk in mine] == [("doc:card.pip", True, "manual")]
    now = time.time()
    assert vcs_engine.renew_due(pc.account, SPACE, PLUGIN, active=True, now=now + 61) == ["doc:card.pip"]
    assert vcs_engine.renew_due(pc.account, SPACE, PLUGIN, active=False, now=now + 61) == []
    assert vcs_engine.idle_auto_locks(pc.account, SPACE, PLUGIN, now=now + 400) == []  # manual: kept
    theirs = vcs_engine.acquire(pc.account, SPACE, PLUGIN, ben.client, [("doc:card.pip", "card.pip")])
    assert theirs["doc:card.pip"]["state"] == "locked"
    assert vcs_engine.release(pc.account, SPACE, PLUGIN, pc.backend, ["doc:card.pip"])["ok"]
    assert space_vcs.locks(pc.account, SPACE) == []
    free = ben.client.lock(SPACE, PLUGIN, [LockUnit("doc:card.pip")], "best", {"doc:card.pip": 2})
    assert type(free["doc:card.pip"]).__name__ == "Granted"


def test_auto_locks_go_five_minutes_after_their_last_change_went_out(pc: PC) -> None:
    pc.data.put("card.pip", {"hp": 1})
    vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, [("doc:card.pip", "card.pip")], reason="auto")
    pc.run()
    now = time.time()
    assert vcs_engine.idle_auto_locks(pc.account, SPACE, PLUGIN, now=now + 60) == []
    assert vcs_engine.release_idle(pc.account, SPACE, PLUGIN, pc.backend, now=now + 301) == ["doc:card.pip"]
    assert space_vcs.locks(pc.account, SPACE) == []


def test_a_broken_lock_turns_unsent_edits_into_a_conflict(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, [("doc:card.pip", "card.pip")])
    pc.data.put("card.pip", {"hp": 9})
    boss = world.client("u_olga", "d_olga", name="Olga", admin=True)
    assert type(boss.break_lock(SPACE, PLUGIN, "doc:card.pip")).__name__ == "Done"
    ben.client.lock(SPACE, PLUGIN, [LockUnit("doc:card.pip", "card.pip")], "best", {"doc:card.pip": 1})
    vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)
    r = pc.row("card.pip")
    assert (r["sync_state"], r["dirty"]) == ("conflict", 1) and "Ben" in r["sync_error"]
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.pip")
    assert c["reason"] == "lock_broken" and _mine(c, pc.account) == {"hp": 9}
    assert pc.run()["pushed"] == 0
    assert vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "theirs", pc.backend)["ok"]
    assert pc.data.get("card.pip") == {"hp": 1} and pc.row("card.pip")["dirty"] == 0


# --------------------------------------------------------------------------- answers and modes


def test_refused_items_wait_with_the_reason_and_the_rest_go_out(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    world.set_max_file_bytes(10)
    pc.data.put_file("big.bin", b"x" * 64)
    pc.data.put("card.pip", {"hp": 1})
    out = pc.run()
    assert out["pushed"] == 1 and ben.doc("card.pip") == {"hp": 1}
    r = pc.row("big.bin", "asset")
    assert (r["sync_state"], r["sync_error"], r["dirty"]) == ("refused", conf.TOO_BIG, 1)


def test_offline_backs_off_and_a_forced_round_goes_anyway(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    world.server.offline = True
    pc.data.put("card.pip", {"hp": 1})
    out = pc.run()
    assert out["state"] == "offline"
    head = space_vcs.head_get(pc.account, SPACE, PLUGIN)
    assert head["state"] == "offline" and head["next_try"] > time.time() + 20
    assert vcs_engine.run(pc.account, SPACE, PLUGIN, pc.backend)["skipped"]
    world.server.offline = False
    out = pc.run()
    assert (out["state"], out["pushed"]) == ("ok", 1)
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["attempts"] == 0


def test_a_failed_read_of_one_file_never_holds_up_the_rest(pc: PC, ben: Ben) -> None:
    pc.data.put_file("art/a.png", b"a")
    pc.data.put("card.pip", {"hp": 1})
    scopes.asset_file({"account": pc.account, "id": SPACE}, PLUGIN, "art/a.png").write_bytes(b"not sealed")
    out = pc.run()
    assert out["pushed"] == 1 and ben.doc("card.pip") == {"hp": 1}
    r = pc.row("art/a.png", "asset")
    assert (r["attempts"], r["dirty"]) == (1, 1) and r["next_try"] > time.time() and r["sync_error"]


def test_manual_mode_moves_only_when_asked(pc: PC, ben: Ben) -> None:
    vcs_engine.set_mode(pc.account, SPACE, PLUGIN, "manual")
    pc.data.put("card.pip", {"hp": 1})
    ben.put_doc("card.zed", {"hp": 1})
    out = pc.run()
    assert (out["pushed"], out["pulled"]) == (0, 0) and pc.data.get("card.zed") is None
    assert pc.run(pull=True)["pulled"] == 1 and pc.data.get("card.zed") == {"hp": 1}
    assert pc.run(push=True, message="Tuned the starter cards")["pushed"] == 1
    assert ben.client.history(SPACE, PLUGIN).entries[0].message == "Tuned the starter cards"
    with pytest.raises(ValueError):
        vcs_engine.set_mode(pc.account, SPACE, PLUGIN, "sometimes")


# --------------------------------------------------------------------------- workflows, callbacks, presence


def test_a_workflow_clash_keeps_your_copy_before_sync_and_folder_adds_keep_both(pc: PC, ben: Ben) -> None:
    from backend.automations import owned
    from backend.store.repos import automations as legacy

    wf = {"id": "wf1", "name": "Daily check", "graph": {"nodes": []}, "updated": 1.0}
    pc.put_raw(WF, "wf1", wf)
    pc.put_raw(WF, owned.FOLDERS_KEY, {"folders": ["Play tests"]})
    pc.run(WF)
    ben.put_doc("wf1", {**wf, "name": "Daily check (Ben)"}, plugin=WF)
    ben.put_doc(owned.FOLDERS_KEY, {"folders": ["Play tests", "Tycoon"]}, plugin=WF)
    pc.put_raw(WF, "wf1", {**wf, "name": "Daily check (Ana)", "updated": 2.0})
    pc.put_raw(WF, owned.FOLDERS_KEY, {"folders": ["Play tests", "Islands"]})
    out = pc.run(WF)
    assert out["conflicts"] == 1
    assert pc.get_raw(WF, "wf1")["name"] == "Daily check (Ben)"
    saved = [owned.open_version(text, pc.account) for _, text in legacy.version_rows("wf1")]
    assert [(v["name"], v["note"]) for v in saved] == [("Daily check (Ana)", owned.BEFORE_SYNC_NOTE)]
    assert pc.get_raw(WF, owned.FOLDERS_KEY) == {"folders": ["Play tests", "Tycoon", "Islands"]}
    assert ben.doc(owned.FOLDERS_KEY, plugin=WF) == {"folders": ["Play tests", "Tycoon", "Islands"]}


def test_on_change_tells_the_plugin_which_keys_a_pull_changed(pc: PC, ben: Ben,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    heard: list[list[str]] = []
    pc.data.on_change(heard.append)
    ben.put_doc("card.a", {"v": 1})
    ben.put_file("img/a.png", b"A")
    pc.run()
    assert heard == [["card.a", "img/a.png"]]
    assert scopes.deliver_data_changes(PLUGIN) == 0  # already heard in this process
    # A pull in another process (the app, while this is the bridge): heard before the next tool call.
    with monkeypatch.context() as m:
        m.setattr(vcs_engine, "_deliver", lambda *a, **k: None)
        ben.put_doc("card.b", {"v": 1})
        pc.run()
    assert heard == [["card.a", "img/a.png"]]
    assert scopes.deliver_data_changes(PLUGIN) == 1 and heard[-1] == ["card.b"]
    assert scopes.deliver_data_changes(PLUGIN) == 0
    # A pull in the bridge (a lock it was behind on), then one here: this process hears both.
    with monkeypatch.context() as m:
        m.setattr(vcs_engine, "_deliver", lambda *a, **k: None)
        ben.put_doc("card.c", {"v": 1})
        pc.run()
    ben.put_doc("card.d", {"v": 1})
    pc.run()
    assert heard[-1] == ["card.c", "card.d"]
    scopes.forget_change_listeners(PLUGIN)
    assert scopes.deliver_data_changes(PLUGIN) == 0


def test_presence_says_who_edits_what_and_keeps_the_roster(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    space_vcs.activity_note(pc.account, SPACE, PLUGIN, "doc:card.pip", actor="agent", ducky="Builder")
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN])["ok"]
    blob, _ = world.server.space(SPACE).presence[("u_ana", vcs_engine.device_id())]
    editing = blob["plugins"][PLUGIN]["editing"]
    assert [(e["unitName"], e["actor"], e["ducky"]) for e in editing] == [("card.pip", "agent", "Builder")]
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN])["skipped"]  # nothing changed
    ben.client.beat(SPACE, {"device": "Ben's PC"})
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], force=True)["people"] == 2
    people = vcs_engine.status(pc.account, SPACE, PLUGIN)["people"]
    assert sorted(p["user_name"] for p in people) == ["Ana", "Ben"]


# --------------------------------------------------------------------------- restore, history, lost access


def test_restore_and_undo_are_new_changesets(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    pc.data.put("card.pip", {"hp": 2})
    pc.data.put("card.new", {"x": 1})
    pc.run()
    out = vcs_engine.undo(pc.account, SPACE, PLUGIN, pc.backend, 2)
    assert out["ok"] and out["seq"] == 3
    assert pc.data.get("card.pip") == {"hp": 1} and pc.data.get("card.new") is None
    out = vcs_engine.restore(pc.account, SPACE, PLUGIN, pc.backend, items={("doc", "card.pip"): 2})
    assert out["ok"] and pc.data.get("card.pip") == {"hp": 2}
    hist = vcs_engine.history(pc.account, SPACE, PLUGIN, pc.backend)
    assert [e["seq"] for e in hist["entries"]] == [4, 3, 2, 1] and hist["entries"][1]["message"] == "Undo #2"
    item = vcs_engine.history(pc.account, SPACE, PLUGIN, pc.backend, key=("doc", "card.pip"))
    assert [e["seq"] for e in item["entries"]] == [4, 3, 2, 1]


def test_unsent_changes_of_a_lost_space_can_be_saved_to_local(pc: PC) -> None:
    pc.data.put("card.pip", {"hp": 2})
    pc.data.put_file("img/a.png", b"mine")
    local = pc.data.personal()
    local.put("card.pip", {"hp": 1})
    assert space_vcs.pending_unsent(pc.account, SPACE) == 2
    out = vcs_engine.save_unsent_to_local(pc.account, SPACE)
    assert sorted((s["key"], s["localKey"]) for s in out["saved"]) == [
        ("card.pip", "card.pip-from-alpha"), ("img/a.png", "img/a.png")]
    assert local.get("card.pip") == {"hp": 1} and local.get("card.pip-from-alpha") == {"hp": 2}
    assert local.get_file("img/a.png") == b"mine"
    assert space_vcs.pending_unsent(pc.account, SPACE) == 0
    again = vcs_engine._local_key(pc.account, PLUGIN, "asset", "img/a.png", "alpha")
    assert again == "img/a-from-alpha.png"


# --------------------------------------------------------------------------- review fixes


def _side_files(pc: PC) -> list[Path]:
    folder = scopes.plugin_dir({"account": pc.account, "id": SPACE}, PLUGIN) / "conflicts"
    return sorted(folder.glob("*")) if folder.is_dir() else []


def _opened(pc: PC, path: str) -> bytes:
    return data_crypto.open_bytes(scopes.asset_file({"account": pc.account, "id": SPACE}, PLUGIN, path).read_bytes(),
                                  pc.account)


def test_a_file_held_open_is_set_aside_alone_and_its_files_go_back(pc: PC, ben: Ben,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    pc.data.put_file("art/a.png", b"v1")
    pc.run()
    ben.put_file("art/a.png", b"theirs")
    ben.put_file("art/b.png", b"B")
    ben.put_doc("card.c", {"v": 1})
    pc.data.put_file("art/a.png", b"mine")  # keep both: mine goes aside, then theirs lands
    target = scopes.asset_file({"account": pc.account, "id": SPACE}, PLUGIN, "art/a.png")
    real = vcs_engine._Files.move

    def held_open(self: Any, src: Path, dst: Path, *, keep: bool) -> None:
        if dst == target and src.name.endswith(".tmp"):
            raise PermissionError("[WinError 32] in use")
        real(self, src, dst, keep=keep)

    monkeypatch.setattr(vcs_engine._Files, "move", held_open)
    out = pc.run()
    assert out["state"] == "ok"
    assert pc.data.get_file("art/b.png") == b"B" and pc.data.get("card.c") == {"v": 1}
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == ben.head()
    blocked = space_vcs.blocked(pc.account, SPACE, PLUGIN)
    assert [b["key"] for b in blocked] == ["art/a.png"] and "open in another program" in blocked[0]["error"]
    r = pc.row("art/a.png", "asset")  # untouched: still mine, unsent, and the file is mine
    assert (r["dirty"], r["sha256"], r["sync_state"]) == (1, hashlib.sha256(b"mine").hexdigest(), "")
    assert _opened(pc, "art/a.png") == b"mine" and _side_files(pc) == []
    assert space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "asset", "art/a.png") is None
    assert not list(target.parent.glob("*.old")) and not list(target.parent.glob("*.tmp"))
    monkeypatch.setattr(vcs_engine._Files, "move", real)
    space_vcs.blocked_retry_now(pc.account, SPACE, PLUGIN, "asset", "art/a.png")
    assert pc.run()["conflicts"] == 1
    assert pc.data.get_file("art/a.png") == b"theirs"
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "asset", "art/a.png")
    assert data_crypto.open_bytes(Path(c["mine_path"]).read_bytes(), pc.account) == b"mine"


def test_an_apply_that_stops_puts_every_file_back(pc: PC, ben: Ben, monkeypatch: pytest.MonkeyPatch) -> None:
    pc.data.put_file("art/a.png", b"v1")
    pc.data.put("card.d", {"v": 1})
    pc.run()
    ben._push(PLUGIN, conf.put_item("asset", "art/a.png", b"theirs", base=1),  # one changeset: one transaction
              conf.put_item("doc", "card.d", scopes.encode_doc({"v": 2}), base=1))
    pc.data.put("card.d", {"v": 3})  # merged after the file landed: the data key goes missing there

    def no_key(*_: Any, **__: Any) -> None:
        raise data_crypto.Locked("no data key")

    monkeypatch.setattr(vcs_engine._Apply, "_merge_doc", no_key)
    assert pc.run()["state"] == "locked"
    assert _opened(pc, "art/a.png") == b"v1"
    assert pc.row("art/a.png", "asset")["sha256"] == hashlib.sha256(b"v1").hexdigest()
    folder = scopes.asset_file({"account": pc.account, "id": SPACE}, PLUGIN, "art/a.png").parent
    assert not list(folder.glob("*.old")) and not list(folder.glob("*.tmp"))
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["seq"] == 1


def test_a_remote_delete_keeps_mine_of_an_unresolved_conflict(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.data.put_file("art/a.png", b"v1")
    pc.run()
    ben.put_doc("card.pip", {"hp": 3})
    ben.put_file("art/a.png", b"theirs")
    pc.data.put("card.pip", {"hp": 2})
    pc.data.put_file("art/a.png", b"mine")
    assert pc.run()["conflicts"] == 2  # theirs current, mine kept in the conflicts
    pip_gone = ben.delete("doc", "card.pip")
    file_gone = ben.delete("asset", "art/a.png")
    assert pc.run()["state"] == "ok"
    assert pc.data.get("card.pip") == {"hp": 2} and pc.data.get_file("art/a.png") == b"mine"
    for key, kind, gone in (("card.pip", "doc", pip_gone), ("art/a.png", "asset", file_gone)):
        r = pc.row(key, kind)
        assert (r["dirty"], r["sync_state"], r["rev"]) == (1, "conflict", gone)
        c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, kind, key)
        assert (c["reason"], c["theirs_deleted"]) == ("deleted", 1)
    assert _side_files(pc) == []  # the side copy is the file again
    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine")  # Restore mine
    vcs_engine.resolve(pc.account, SPACE, PLUGIN, "asset", "art/a.png", "mine")
    assert pc.run()["pushed"] == 1
    assert ben.doc("card.pip") == {"hp": 2}
    assert ben.server.space(SPACE).repo(PLUGIN).items[("asset", "art/a.png")].content == b"mine"


def test_keep_mine_after_the_row_went_makes_it_again(pc: PC, ben: Ben) -> None:
    from backend.store import db

    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 3})
    pc.data.put("card.pip", {"hp": 2})
    pc.run()
    conn = db.connect()
    with db.write_txn(conn):
        space_vcs.delete_row(conn, pc.account, SPACE, PLUGIN, "doc", "card.pip")
    assert vcs_engine.resolve(pc.account, SPACE, PLUGIN, "doc", "card.pip", "mine") == {"ok": True}
    r = pc.row("card.pip")
    assert (r["dirty"], r["rev"]) == (1, 0) and pc.data.get("card.pip") == {"hp": 2}


def _v1_doc(pc: PC, key: str, value: Any, *, rev: int, dirty: bool) -> None:
    raw = scopes.encode_doc(value)
    repo.put(pc.account, SPACE, PLUGIN, "doc", key, value=data_crypto.seal_text(raw.decode(), pc.account),
             size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), dirty=dirty, rev=rev)


def test_the_move_from_the_older_sync_reconciles_each_row(pc: PC, ben: Ben) -> None:
    from dataclasses import replace

    _v1_doc(pc, "card.same", {"v": "x"}, rev=7, dirty=False)
    _v1_doc(pc, "card.old", {"v": "y"}, rev=5, dirty=False)
    _v1_doc(pc, "card.mine", {"v": "edited here"}, rev=8, dirty=True)
    _v1_doc(pc, "card.stale", {"v": "stale edit"}, rev=3, dirty=True)
    _v1_doc(pc, "card.gone", {"v": 1}, rev=4, dirty=False)
    _v1_doc(pc, "card.edited_gone", {"v": "mine"}, rev=4, dirty=True)
    _v1_doc(pc, "card.new", {"v": "made here"}, rev=0, dirty=True)
    imported = [("card.same", {"v": "x"}, 7), ("card.old", {"v": "y2"}, 6), ("card.mine", {"v": "z"}, 8),
                ("card.stale", {"v": "t"}, 9), ("card.extra", {"v": "e"}, 2)]
    items = [replace(conf.put_item("doc", key, scopes.encode_doc(value)), meta={"v1rev": v1rev})
             for key, value, v1rev in imported]
    assert ben._push(PLUGIN, *items, message="Imported from team data") == 1
    out = pc.run()
    assert out["state"] == "ok"
    head = space_vcs.head_get(pc.account, SPACE, PLUGIN)
    assert head["engine"] == "v2" and head["seq"] == ben.head()
    same = pc.row("card.same")
    assert (same["dirty"], same["rev"]) == (0, 1)
    assert space_vcs.base_get(pc.account, SPACE, PLUGIN, "card.same")["seq"] == 1
    assert pc.data.get("card.old") == {"v": "y2"} and pc.row("card.old")["rev"] == 1
    assert pc.data.get("card.extra") == {"v": "e"}
    assert ben.doc("card.mine") == {"v": "edited here"}  # an edit on top of what was imported goes out
    assert ben.doc("card.new") == {"v": "made here"}
    assert pc.data.get("card.stale") == {"v": "t"} and pc.row("card.stale")["sync_state"] == "conflict"
    stale = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.stale")
    assert _mine(stale, pc.account) == {"v": "stale edit"} and ben.doc("card.stale") == {"v": "t"}
    assert pc.row("card.gone") is None
    gone = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.edited_gone")
    assert gone["reason"] == "deleted" and pc.row("card.edited_gone")["dirty"] == 1
    assert ben.doc("card.edited_gone") is None
    assert space_vcs.unit_seqs(pc.account, SPACE, PLUGIN, ["doc:card.same"]) == {"doc:card.same": 1}


def test_undo_never_deletes_an_item_whose_earlier_version_is_no_longer_kept(pc: PC, ben: Ben,
                                                                           world: conf.FakeWorld) -> None:
    pc.data.put("card.a", {"v": 1})
    pc.run()
    pc.data.put("card.b", {"v": 1})
    pc.run()
    pc.data.put("card.a", {"v": 3})
    pc.data.put("card.c", {"v": 1})
    pc.run()
    world.trim(SPACE, PLUGIN, 3)  # card.a's version before #3 is no longer kept
    out = vcs_engine.undo(pc.account, SPACE, PLUGIN, pc.backend, 3)
    assert out["ok"] and out["skipped"] == [["doc", "card.a"]]
    assert pc.data.get("card.a") == {"v": 3} and ben.doc("card.a") == {"v": 3}
    assert pc.data.get("card.c") is None and ben.doc("card.c") is None
    assert pc.data.get("card.b") == {"v": 1}


def test_nothing_moves_in_a_reset_space_and_upload_my_copy_sends_mine(pc: PC, ben: Ben,
                                                                     world: conf.FakeWorld) -> None:
    from backend.uefn_plugins import spaces

    pc.data.put("card.pip", {"hp": 1})
    pc.data.put("card.zed", {"hp": 1})
    pc.run()
    vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)  # this PC knows the epoch
    ben.put_doc("card.pip", {"hp": 3})
    pc.data.put("card.pip", {"hp": 2})
    assert pc.run()["conflicts"] == 1  # mine only in the conflict now
    world.server.reset_epoch(SPACE)
    assert vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)["state"] == "reset"
    assert space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.pip") is not None  # kept for the choice
    ben._push(PLUGIN, conf.put_item("doc", "card.new", b'{"v":1}'))
    out = pc.run()
    assert out["state"] == "reset" and pc.data.get("card.new") is None  # no pull before the person chose
    got = vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, [("doc:card.new", "card.new")])
    assert not got["doc:card.new"]["ok"] and pc.data.get("card.new") is None
    assert vcs_engine.restore(pc.account, SPACE, PLUGIN, pc.backend, to_seq=0)["ok"] is False
    assert spaces.settle_reset(SPACE, "upload")["ok"]
    head = space_vcs.head_get(pc.account, SPACE, PLUGIN)
    assert (head["seq"], head["remote_seq"]) == (0, 0)
    assert space_vcs.conflicts(pc.account, SPACE) == []
    assert space_vcs.unit_seqs(pc.account, SPACE, PLUGIN, ["doc:card.zed"]) == {"doc:card.zed": 0}
    assert pc.data.get("card.pip") == {"hp": 2}  # mine is what goes up
    out = pc.run()
    assert out["state"] == "ok" and pc.data.get("card.new") == {"v": 1}
    assert ben.doc("card.pip") == {"hp": 2} and ben.doc("card.zed") == {"hp": 1}


def test_unsent_conflicts_count_and_are_saved_and_a_later_loss_asks_again(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    ben.put_doc("card.pip", {"hp": 3})
    pc.data.put("card.pip", {"hp": 2})
    pc.run()  # mine is kept only in the conflict
    assert space_vcs.pending_unsent(pc.account, SPACE) == 1
    out = vcs_engine.save_unsent_to_local(pc.account, SPACE)
    assert [(s["key"], s["localKey"]) for s in out["saved"]] == [("card.pip", "card.pip")]
    assert pc.data.personal().get("card.pip") == {"hp": 2}
    assert space_vcs.pending_unsent(pc.account, SPACE) == 0
    time.sleep(0.01)
    pc.data.put("card.zed", {"hp": 1})  # access came back, then a new edit
    assert space_vcs.pending_unsent(pc.account, SPACE) == 1  # made after the choice: asked again
    repo.sync_put(pc.account, SPACE, state="ok")
    assert space_vcs.lost_choice_get(pc.account, SPACE) == ""


def test_drop_my_change_brings_the_teams_version_back(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    pc.data.put("card.pip", {"hp": 2})
    repo.set_state(pc.account, SPACE, PLUGIN, "doc", "card.pip", "refused", "Too big")
    row = repo.get(pc.account, SPACE, PLUGIN, "doc", "card.pip")
    assert repo.drop_held(pc.account, SPACE, PLUGIN, "doc", "card.pip", expect=row)
    assert pc.data.get("card.pip") is None
    assert pc.run()["state"] == "ok"
    assert pc.data.get("card.pip") == {"hp": 1}
    r = pc.row("card.pip")
    assert (r["dirty"], r["rev"]) == (0, 1) and space_vcs.blocked(pc.account, SPACE) == []


def test_a_resync_keeps_a_row_written_meanwhile_and_never_marks_a_set_aside_unit(pc: PC, ben: Ben,
                                                                                  world: conf.FakeWorld) -> None:
    pc.data.put("card.extra", {"v": 1})
    pc.data.put("card.x", {"v": 1})
    pc.run()
    world.purge(SPACE, PLUGIN, "doc", "card.extra")
    ben.put_doc("card.y", {"v": 1})
    ben.put_doc("card.z", {"v": 1})
    world.trim(SPACE, PLUGIN, 3)
    world.server.bad.add((SPACE, PLUGIN, "doc", "card.y", 2))

    def edit_during_the_download(*_: Any) -> None:
        world.server.hooks.pop("fetch", None)
        worker = threading.Thread(target=lambda: PluginData(PLUGIN).put("card.extra", {"v": 2}))
        worker.start()
        worker.join(30)

    world.server.hooks["fetch"] = edit_during_the_download
    out = pc.run(push=False)
    assert out["state"] == "ok" and pc.data.get("card.z") == {"v": 1}
    r = pc.row("card.extra")
    assert r is not None and r["dirty"] == 1 and pc.data.get("card.extra") == {"v": 2}
    assert [b["key"] for b in space_vcs.blocked(pc.account, SPACE, PLUGIN)] == ["card.y"]
    assert space_vcs.unit_seqs(pc.account, SPACE, PLUGIN, ["doc:card.y", "doc:card.z"]) == {
        "doc:card.y": 0, "doc:card.z": 3}


def test_a_doc_merges_only_against_a_base_it_knows(pc: PC, ben: Ben, world: conf.FakeWorld) -> None:
    from backend.store import db

    def forget_base(key: str) -> None:
        conn = db.connect()
        with db.write_txn(conn):
            space_vcs.base_delete(conn, pc.account, SPACE, PLUGIN, key)

    pc.data.put("card.pip", {"a": 1, "b": 1})
    pc.data.put("card.zed", {"a": 1, "b": 1})
    pc.run()
    forget_base("card.pip")
    ben.put_doc("card.pip", {"a": 1})  # Ben removed b
    pc.data.put("card.pip", {"a": 2, "b": 1})
    assert pc.run()["conflicts"] == 0  # the base was fetched: the removal holds
    assert pc.data.get("card.pip") == {"a": 2} and ben.doc("card.pip") == {"a": 2}
    forget_base("card.zed")
    ben.put_doc("card.zed", {"a": 1})
    world.trim(SPACE, PLUGIN, ben.head())  # the version mine is an edit of is no longer kept
    pc.data.put("card.zed", {"a": 2, "b": 1})
    assert pc.run()["conflicts"] == 1  # no merge without a base: b never comes back
    assert pc.data.get("card.zed") == {"a": 1} and ben.doc("card.zed") == {"a": 1}
    c = space_vcs.conflict_get(pc.account, SPACE, PLUGIN, "doc", "card.zed")
    assert _mine(c, pc.account) == {"a": 2, "b": 1}


def test_a_file_rewritten_while_it_is_sent_goes_again_with_its_new_content(pc: PC, ben: Ben,
                                                                          world: conf.FakeWorld) -> None:
    pc.run()
    pc.data.put_file("art/a.png", b"v1")

    def rewrite_before_the_upload(*_: Any) -> None:
        world.server.hooks.pop("push", None)
        worker = threading.Thread(target=lambda: PluginData(PLUGIN).put_file("art/a.png", b"v2, longer"))
        worker.start()
        worker.join(30)

    world.server.hooks["push"] = rewrite_before_the_upload
    out = pc.run()
    assert (out["state"], out["pushed"]) == ("ok", 1)
    item = ben.server.space(SPACE).repo(PLUGIN).items[("asset", "art/a.png")]
    assert item.content == b"v2, longer" and item.sha256 == hashlib.sha256(b"v2, longer").hexdigest()
    r = pc.row("art/a.png", "asset")
    assert (r["dirty"], r["attempts"]) == (0, 0)


def test_a_row_another_call_rewrites_goes_with_that_call(pc: PC, ben: Ben) -> None:
    pc.run()  # on the new sync: writes group from now on
    pc.data.put("card.a", {"v": 1})
    pc.data.put("card.b", {"v": 1})
    assert vcs_engine._build(vcs_engine.Ctx(pc.account, SPACE, PLUGIN, pc.backend), now=time.time()) == 1
    with scopes.write_group(PLUGIN, actor="agent", ducky="Builder", message="Tool tune_cards"):
        PluginData(PLUGIN).put("card.a", {"v": 2})
        assert pc.run()["pushed"] == 1  # the changeset built before goes without card.a
        assert ben.doc("card.b") == {"v": 1} and ben.doc("card.a") is None
    assert pc.run()["pushed"] == 1
    assert ben.doc("card.a") == {"v": 2}
    assert ben.client.history(SPACE, PLUGIN).entries[0].message == "Tool tune_cards"


def test_ungrouped_rows_over_one_changeset_never_hold_a_teammates_pull(pc: PC, ben: Ben, world: conf.FakeWorld,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vcs_engine, "MAX_ITEMS", 5)
    world.set_max_file_bytes(10)
    for n in range(7):
        pc.data.put(f"card.{n}", {"n": n})
    pc.data.put_file("big.bin", b"x" * 64)  # in the last slice, refused
    out = pc.run()
    assert out["pushed"] == 2 and pc.row("big.bin", "asset")["sync_state"] == "refused"
    page = ben.client.pull(SPACE, PLUGIN, 0, 50)
    assert [(cs.group, cs.last) for cs in page.changesets] == [("", True), ("", True)]
    assert not vcs_engine._groups_open(list(page.changesets), time.time())
    assert all(ben.doc(f"card.{n}") == {"n": n} for n in range(7))


class _V2Off:
    """The new sync switched off on the server: heads says ``v2`` false."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def heads(self, space: str, plugins: list[str]) -> Any:
        from dataclasses import replace

        return replace(self.inner.heads(space, plugins), v2=False)


def test_the_new_sync_switched_off_pauses_its_plugins_only(pc: PC, ben: Ben) -> None:
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    out = vcs_engine.refresh(pc.account, SPACE, [PLUGIN], _V2Off(pc.backend))
    assert out == {"state": "paused", "error": vcs_engine.SYNC_PAUSED}
    assert repo.sync_get(pc.account, SPACE)["state"] != "paused"  # the space and its older-sync plugins go on
    assert space_vcs.head_get(pc.account, SPACE, PLUGIN)["state"] == "paused"
    with pytest.raises(scopes.ReadOnlyScope, match="Team sync paused"):
        pc.data.put("card.pip", {"hp": 2})
    assert vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)["state"] == "ok"
    assert pc.data.put("card.pip", {"hp": 2})["changed"]


def test_the_drawer_shows_the_new_syncs_tables_only_on_it(pc: PC) -> None:
    from backend.uefn_plugins import spaces

    pc.data.put("card.pip", {"hp": 1})
    old = spaces.team_fields(pc.account, SPACE, PLUGIN)
    assert old["engine"] == "v1" and not {"mode", "head", "people", "locks", "nextTry"} & set(old)
    assert [o["key"] for o in old["changes"]["outgoing"]] == ["card.pip"]
    pc.run()
    new = spaces.team_fields(pc.account, SPACE, PLUGIN)
    assert new["engine"] == "v2" and {"mode", "head", "people", "locks"} <= set(new)
    assert new["changes"]["incoming"] == 0 and new["changes"]["blocked"] == []


def test_beats_go_at_most_every_ten_seconds_and_renewals_in_one_call(pc: PC, ben: Ben,
                                                                     world: conf.FakeWorld) -> None:
    now = time.time()
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], now=now)["ok"]
    space_vcs.activity_note(pc.account, SPACE, PLUGIN, "doc:card.pip", at=now + 1)
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], now=now + 5)["skipped"]  # changed, too soon
    world.server.offline = True
    assert not vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], now=now + 11)["ok"]
    world.server.offline = False
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], now=now + 15)["skipped"]  # a failed one counts
    assert vcs_engine.beat(pc.account, SPACE, pc.backend, [PLUGIN], now=now + 22)["ok"]
    units = [(f"doc:card.{n}", f"card.{n}") for n in range(4)]
    vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, units[:2], reason="auto")
    vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, units[2:])
    world.server.calls.clear()
    got = vcs_engine.renew(pc.account, SPACE, PLUGIN, pc.backend, [u for u, _ in units])
    assert all(v["ok"] for v in got.values()) and [c[0] for c in world.server.calls] == ["lock"]
    reasons = {lk["unit"]: lk["reason"] for lk in space_vcs.locks(pc.account, SPACE, PLUGIN)}
    assert reasons == {"doc:card.0": "auto", "doc:card.1": "auto", "doc:card.2": "manual", "doc:card.3": "manual"}


def test_a_lock_of_mine_that_went_is_told(pc: PC, ben: Ben, world: conf.FakeWorld,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from frontend import notifications
    from frontend.ui_web import agent_modes

    alerts: list[tuple[Any, ...]] = []
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(notifications, "alert", lambda *a, **k: alerts.append((*a, k.get("detail"))))
    monkeypatch.setattr(agent_modes, "push_ui_event", events.append)
    pc.data.put("card.pip", {"hp": 1})
    pc.run()
    vcs_engine.acquire(pc.account, SPACE, PLUGIN, pc.backend, [("doc:card.pip", "card.pip"), ("doc:card.zed", "Zed")])
    boss = world.client("u_olga", "d_olga", name="Olga", admin=True)
    boss.break_lock(SPACE, PLUGIN, "doc:card.zed")
    ben.client.lock(SPACE, PLUGIN, [LockUnit("doc:card.zed", "Zed")], "best", {})
    vcs_engine.refresh(pc.account, SPACE, [PLUGIN], pc.backend)
    assert [a[1] for a in alerts] == ["Your lock was broken."] and alerts[0][-1] == "Ben took Zed."
    lost = [e for e in events if e["type"] == "plugin_lock_lost"]
    assert [(e["unit"], e["holder"], e["kept"]) for e in lost] == [("doc:card.zed", "Ben", False)]


def test_workflow_saves_take_the_writers_checks_and_go_as_one_changeset(pc: PC, ben: Ben) -> None:
    from backend.automations import owned

    pc.run(WF)  # on the new sync
    scope = scopes.shared_scope(pc.account, SPACE)
    wf = {"id": "wf1", "name": "Daily check", "graph": {"nodes": []}, "updated": 1.0}
    ben.client.lock(SPACE, WF, [LockUnit("doc:wf1", "Daily check")], "best", {})
    vcs_engine.refresh(pc.account, SPACE, [WF], pc.backend)
    with pytest.raises(scopes.LockedOut, match="locked by Ben"):
        owned.write(scope, wf)
    assert pc.row("wf1", plugin=WF) is None
    ben.client.unlock(SPACE, WF, ["doc:wf1"])
    vcs_engine.refresh(pc.account, SPACE, [WF], pc.backend)
    owned.write(scope, wf)
    r = pc.row("wf1", plugin=WF)
    assert r["dirty"] == 1 and r["group_id"]
    assert [a["unit"] for a in space_vcs.activity(pc.account, SPACE)] == ["doc:wf1"]
    assert pc.run(WF)["pushed"] == 1
    assert ben.client.history(SPACE, WF).entries[0].message == "Workflow Daily check"
