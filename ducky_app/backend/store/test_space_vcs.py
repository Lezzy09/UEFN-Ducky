"""The team repo tables on this PC (migration 0021): heads, changesets, conflicts, blocked
incoming items, the lock and presence caches, activity, groups, lock requests, merge
bases, unit seqs, lost-access choices, the change log; the per-row compare-and-set after
a commit; pruning."""

from __future__ import annotations

import time

import pytest

from backend.store import db
from backend.store.repos import plugin_data as repo
from backend.store.repos import space_vcs as vcs

A, S, P = "a_1", "spaceT", "cards"


def _doc(key: str, sha: str = "s1", *, dirty: bool = True, rev: int = 0) -> dict:
    repo.put(A, S, P, "doc", key, value="sealed:" + sha, size=3, sha256=sha, dirty=dirty, rev=rev)
    return vcs.row(None, A, S, P, "doc", key)


def _snap(r: dict, op: str = "put") -> dict:
    return {"kind": r["kind"], "key": r["key"], "op": op, "sha256": r["sha256"], "deleted": r["deleted"],
            "updated": r["updated"]}


def test_heads_default_put_advance_backoff_and_ok() -> None:
    assert vcs.head_get(A, S, P) == {**vcs._HEAD_DEFAULT}
    vcs.head_put(A, S, P, engine="v2", mode="manual", remote_seq=7)
    vcs.head_put(A, S, P, seq=5)
    vcs.head_put(A, S, P, seq=3)  # never back
    head = vcs.head_get(A, S, P)
    assert (head["seq"], head["engine"], head["mode"], head["remote_seq"]) == (5, "v2", "manual", 7)
    conn = db.connect()
    with db.write_txn(conn):
        assert not vcs.head_advance(conn, A, S, P, 7, only_next=True)  # 6 is missing: a pull fills it first
        assert vcs.head_advance(conn, A, S, P, 6, only_next=True)
        assert vcs.head_advance(conn, A, S, P, 9)
        assert not vcs.head_advance(conn, A, S, P, 8)
    assert vcs.head_get(A, S, P)["seq"] == 9 and vcs.head_get(A, S, P)["remote_seq"] == 9
    now = 1000.0
    waits = [vcs.backoff(A, S, P, "offline", "no network", now=now) - now for _ in range(5)]
    assert waits == [30.0, 120.0, 300.0, 900.0, 900.0]
    assert vcs.backoff(A, S, P, "retry", "busy", after=5, now=now) == now + 5
    vcs.head_ok(A, S, P, now=now)
    head = vcs.head_get(A, S, P)
    assert (head["state"], head["attempts"], head["next_try"], head["synced_at"]) == ("ok", 0, 0.0, now)
    vcs.head_reset(A, S, P, 2)
    assert vcs.head_get(A, S, P)["seq"] == 2
    assert set(vcs.heads(A, S)) == {P}


def test_changesets_are_kept_until_answered_and_list_their_items() -> None:
    items = [{"kind": "doc", "key": "card.pip", "unit": "doc:card.pip"}]
    vcs.cs_add(A, S, P, "cs1", base_seq=3, items=items, group_id="g1", part=1, last=False, message="Edit",
               actor="agent", ducky="Builder")
    vcs.cs_add(A, S, P, "cs2", base_seq=3, items=[{"kind": "asset", "key": "a.png"}], group_id="g1", part=2)
    assert [c["cs_id"] for c in vcs.cs_open(A, S, P)] == ["cs1", "cs2"]
    first = vcs.cs_get(A, S, "cs1")
    assert (first["items"], first["last"], first["actor"], first["ducky"]) == (items, False, "agent", "Builder")
    assert vcs.cs_items_open(A, S, P) == {("doc", "card.pip"), ("asset", "a.png")}
    vcs.cs_set(A, S, "cs1", state="pushing", items=[*items, {"kind": "doc", "key": "x"}])
    assert vcs.cs_get(A, S, "cs1")["state"] == "pushing" and len(vcs.cs_get(A, S, "cs1")["items"]) == 2
    vcs.cs_set(A, S, "cs1", state="committed", seq=4)
    assert [c["cs_id"] for c in vcs.cs_open(A, S, P)] == ["cs2"]
    vcs.cs_delete(A, S, "cs2")
    assert vcs.cs_open(A, S) == [] and [c["cs_id"] for c in vcs.cs_list(A, S, P)] == ["cs1"]
    assert vcs.prune(now=time.time() + vcs.CHANGESET_KEEP_S + 10)["changesets"] == 1


def test_mark_committed_clears_only_rows_still_as_sent() -> None:
    same = _doc("card.same", "s1")
    edited = _doc("card.edit", "s1")
    gone = _doc("card.gone", "s1")
    repo.remove(A, S, P, "doc", "card.gone", tombstone=True)
    gone = vcs.row(None, A, S, P, "doc", "card.gone")
    sent = [_snap(same), _snap(edited), _snap(gone, "del")]
    _doc("card.edit", "s2")  # edited while the push was out
    out = vcs.mark_committed(A, S, P, 1, sent, bases={"card.same": ("s1", "sealed:s1")},
                             units=["doc:card.same", "doc:card.edit", "doc:card.gone"])
    assert out == {"clean": 2, "kept": 1}
    assert (vcs.row(None, A, S, P, "doc", "card.same")["dirty"], vcs.row(None, A, S, P, "doc", "card.same")["rev"]) == (0, 1)
    kept = vcs.row(None, A, S, P, "doc", "card.edit")
    assert (kept["dirty"], kept["rev"], kept["sha256"]) == (1, 1, "s2")  # stays queued, on the new base
    assert vcs.row(None, A, S, P, "doc", "card.gone") is None
    assert vcs.base_get(A, S, P, "card.same") == {"seq": 1, "sha256": "s1", "value": "sealed:s1"}
    assert vcs.base_get(A, S, P, "card.edit") is None
    assert vcs.unit_seqs(A, S, P, ["doc:card.same", "doc:card.x"]) == {"doc:card.same": 1, "doc:card.x": 0}
    assert vcs.head_get(A, S, P)["seq"] == 1


def test_a_delete_committed_after_the_item_was_made_again_keeps_it() -> None:
    r = _doc("card.pip")
    repo.remove(A, S, P, "doc", "card.pip", tombstone=True)
    tomb = vcs.row(None, A, S, P, "doc", "card.pip")
    _doc("card.pip", "s9")  # made again before the delete's answer
    vcs.mark_committed(A, S, P, 4, [_snap(tomb, "del")])
    again = vcs.row(None, A, S, P, "doc", "card.pip")
    assert r and (again["deleted"], again["dirty"], again["rev"]) == (0, 1, 4)
    assert vcs.head_get(A, S, P)["seq"] == 0  # 4 is not the next seq: a pull fills the gap first


def test_outgoing_rows_leave_out_held_sensitive_and_backing_off_rows() -> None:
    for key in ("a", "b", "c", "d", "e"):
        _doc(f"card.{key}")
    repo.set_state(A, S, P, "doc", "card.b", "refused", "too big")
    repo.set_state(A, S, P, "doc", "card.c", "conflict")
    repo.note_attempt(A, S, P, "doc", "card.d", "unreadable")
    repo.put(A, S, P, "doc", "card.s", value="x", size=1, sha256="x", dirty=True, sensitive=True)
    assert [r["key"] for r in vcs.outgoing_rows(A, S, P)] == ["card.a", "card.e"]
    assert vcs.outgoing_rows(A, S, P)[0]["group_id"] == ""


def test_apply_row_keeps_the_sync_state_given_and_tombstones() -> None:
    conn = db.connect()
    with db.write_txn(conn):
        vcs.apply_row(conn, A, S, P, "doc", "card.pip", value="v", size=1, sha256="t", rev=3, dirty=False,
                      state="conflict", error="Ben changed this too.")
    r = vcs.row(None, A, S, P, "doc", "card.pip")
    assert (r["rev"], r["dirty"], r["sync_state"], r["sync_error"]) == (3, 0, "conflict", "Ben changed this too.")
    with db.write_txn(conn):
        vcs.make_tombstone(conn, A, S, P, "doc", "card.pip")
    r = vcs.row(None, A, S, P, "doc", "card.pip")
    assert (r["deleted"], r["dirty"], r["value"], r["sync_state"]) == (1, 1, None, "")


def test_conflicts_keep_the_newest_local_edit() -> None:
    conn = db.connect()
    with db.write_txn(conn):
        vcs.conflict_put(conn, A, S, P, "doc", "card.pip", unit="doc:card.pip", mine_value="m1", mine_sha="1",
                         base_seq=2, theirs_seq=3, theirs_by="Ben")
        vcs.conflict_put(conn, A, S, P, "doc", "card.pip", unit="doc:card.pip", reason="deleted", mine_value="m2",
                         mine_sha="2", base_seq=3, theirs_seq=5, theirs_by="Olga", theirs_deleted=True)
    c = vcs.conflict_get(A, S, P, "doc", "card.pip")
    assert (c["mine_value"], c["reason"], c["theirs_seq"], c["theirs_by"], c["theirs_deleted"]) == (
        "m2", "deleted", 5, "Olga", 1)
    assert [x["key"] for x in vcs.conflicts(A, S, P)] == ["card.pip"] and vcs.conflicts(A, S, "other") == []
    with db.write_txn(conn):
        vcs.conflict_delete(conn, A, S, P, "doc", "card.pip")
    assert vcs.conflicts(A, S) == []


def test_blocked_items_back_off_and_can_be_retried_now() -> None:
    conn = db.connect()
    now = 1000.0
    with db.write_txn(conn):
        first = vcs.blocked_put(conn, A, S, P, "asset", "a.png", unit="asset:a.png", seq=4, error="bad", now=now)
        second = vcs.blocked_put(conn, A, S, P, "asset", "a.png", unit="asset:a.png", seq=3, error="bad", now=now)
    assert (first["attempts"], first["next_try"], second["attempts"], second["next_try"]) == (1, now + 60, 2, now + 120)
    assert vcs.blocked(A, S, P)[0]["seq"] == 4  # never back to an older seq
    assert vcs.blocked(A, S, P, due=now + 100) == []
    assert vcs.blocked_retry_now(A, S, P, "asset", "a.png")
    assert len(vcs.blocked(A, S, P, due=now)) == 1
    with db.write_txn(conn):
        vcs.blocked_delete(conn, A, S, P, "asset", "a.png")
    assert vcs.blocked(A, S) == []


def test_lock_cache_writers_check_and_replacing_reports_lost_and_freed() -> None:
    now = 1000.0
    vcs.lock_put(A, S, P, "doc:card.pip", name="card.pip", holder_user="u_ben", holder_name="Ben", since=now - 5,
                 lease_left=300, fence=4, now=now)
    vcs.lock_put(A, S, P, "doc:card.zed", name="card.zed", holder_user="u_ana", holder_name="Ana", lease_left=300,
                 fence=5, mine=True, reason="auto", now=now)
    held = vcs.foreign_lock(A, S, P, "doc:card.pip", now=now + 10)
    assert held["holder_name"] == "Ben" and held["lease_left"] == pytest.approx(290)
    assert vcs.foreign_lock(A, S, P, "doc:card.zed", now=now) is None  # mine
    assert vcs.foreign_lock(A, S, P, "doc:card.pip", now=now + 301) is None  # ran out
    conn = db.connect()
    with db.write_txn(conn):
        vcs.lock_touch(conn, A, S, P, ["doc:card.zed"], now + 20)
    mine = [lk for lk in vcs.locks(A, S, P, now=now) if lk["mine"]][0]
    assert (mine["reason"], mine["touched"], mine["fence"]) == ("auto", now + 20, 5)
    # The server now says: Ben's lock went, Olga took mine.
    change = vcs.locks_replace(A, S, [{"plugin": P, "unit": "doc:card.zed", "user": "u_olga", "user_name": "Olga",
                                       "lease_left": 300, "fence": 6}], now=now + 30)
    assert [lk["unit"] for lk in change["freed"]] == ["doc:card.pip"]
    assert [(lk["unit"], lk["now_holder"]) for lk in change["lost"]] == [("doc:card.zed", "Olga")]
    rows = vcs.locks(A, S, now=now + 30)
    assert [(lk["unit"], lk["holder_name"], lk["mine"], lk["reason"]) for lk in rows] == [
        ("doc:card.zed", "Olga", False, "")]


def test_a_lock_taken_after_the_list_was_asked_for_stays() -> None:
    now = 1000.0
    vcs.lock_put(A, S, P, "doc:card.new", mine=True, lease_left=300, fence=1, reason="manual", now=now)
    change = vcs.locks_replace(A, S, [], now=now + 1, asked_at=now - 1)
    assert change == {"lost": [], "freed": []}
    assert [lk["unit"] for lk in vcs.locks(A, S, now=now + 1)] == ["doc:card.new"]
    lost = vcs.locks_replace(A, S, [], now=now + 2, asked_at=now + 1)
    assert [lk["unit"] for lk in lost["lost"]] == ["doc:card.new"] and vcs.locks(A, S, now=now + 2) == []


def test_presence_and_activity() -> None:
    now = 1000.0
    vcs.presence_put(A, S, {"people": [{"user": "u_ben"}]}, now=now)
    vcs.presence_put(A, S, sent_sha="abc", now=now + 1)
    got = vcs.presence_get(A, S)
    assert (got["roster"], got["sent_sha"], got["sent_at"], got["updated"]) == (
        {"people": [{"user": "u_ben"}]}, "abc", now + 1, now)
    vcs.activity_note(A, S, P, "doc:card.pip", actor="agent", ducky="Builder", at=now)
    vcs.activity_note(A, S, P, "doc:card.pip", actor="agent", ducky="Builder", at=now + 30)
    vcs.activity_note(A, S, P, "doc:card.zed", at=now + 40)
    acts = vcs.activity(A, S, now=now + 60)
    assert [(a["unit"], a["actor"], a["since"], a["at"]) for a in acts] == [
        ("doc:card.zed", "user", now + 40, now + 40), ("doc:card.pip", "agent", now, now + 30)]
    vcs.activity_note(A, S, P, "doc:card.pip", actor="agent", ducky="Builder", at=now + 500)
    assert [a["since"] for a in vcs.activity(A, S, now=now + 500) if a["unit"] == "doc:card.pip"] == [now + 500]
    assert vcs.activity(A, S, now=now + 1000) == []
    assert vcs.last_activity(A, S) == now + 500
    assert vcs.prune(now=now + 1000)["activity"] == 2


def test_groups_lock_requests_bases_and_unit_seqs() -> None:
    vcs.group_open("g1", P, actor="agent", ducky="Builder", message="cards_upsert", at=10.0)
    assert vcs.groups(["g1", "", "nope"])["g1"]["open"] == 1
    vcs.group_close("g1", at=12.0)
    g = vcs.groups(["g1"])["g1"]
    assert (g["open"], g["closed"], g["message"]) == (0, 12.0, "cards_upsert")
    conn = db.connect()
    with db.write_txn(conn):
        vcs.group_add_closed(conn, "merge-1", P, message="Merged with Ben's change")
        vcs.base_put(conn, A, S, P, "card.pip", 3, "sha", "sealed")
        vcs.unit_seen(conn, A, S, P, "doc:card.pip", 5)
        vcs.unit_seen(conn, A, S, P, "doc:card.pip", 4)
    assert vcs.groups(["merge-1"])["merge-1"]["open"] == 0
    assert vcs.base_get(A, S, P, "card.pip") == {"seq": 3, "sha256": "sha", "value": "sealed"}
    assert vcs.unit_seqs(A, S, P, ["doc:card.pip"]) == {"doc:card.pip": 5}
    vcs.lock_request_add(A, S, P, "doc:card.pip", "card.pip")
    assert [r["unit"] for r in vcs.lock_requests_pending(A)] == ["doc:card.pip"]
    vcs.lock_request_answer(A, S, P, "doc:card.pip", "refused", "Locked by Ben")
    assert vcs.lock_requests_pending(A, S) == []
    assert vcs.lock_request_get(A, S, P, "doc:card.pip")["answer"] == "Locked by Ben"
    out = vcs.prune(now=time.time() + vcs.GROUP_KEEP_S + 10)
    assert out["groups"] == 2 and out["requests"] == 1


def test_a_group_some_row_still_names_is_kept() -> None:
    vcs.group_open("g2", P)
    vcs.group_close("g2", at=1.0)
    _doc("card.pip")
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("UPDATE plugin_data SET group_id='g2'")
    assert vcs.prune(now=time.time() + vcs.GROUP_KEEP_S + 10)["groups"] == 0


def test_a_group_left_open_closes_and_closed_groups_say_when_their_changes_may_go() -> None:
    vcs.group_open("g3", P, at=time.time() - 7200)  # its call never returned
    vcs.group_open("g4", P)  # still running
    assert vcs.groups_close_stale(3600) == 1
    assert (vcs.groups(["g3"])["g3"]["open"], vcs.groups(["g4"])["g4"]["open"]) == (0, 1)
    repo.put(A, S, P, "doc", "card.a", value="x", size=1, sha256="a", dirty=True, group_id="g3")
    repo.put(A, S, P, "doc", "card.b", value="x", size=1, sha256="b", dirty=True, group_id="g4")
    assert vcs.row(None, A, S, P, "doc", "card.a")["group_id"] == "g3"
    assert vcs.groups_closed(A) == {S: vcs.groups(["g3"])["g3"]["closed"]}  # g4 is still open
    assert vcs.has_outgoing(A, S, P)
    repo.set_state(A, S, P, "doc", "card.a", "conflict")
    repo.set_state(A, S, P, "doc", "card.b", "refused", "too big")
    assert not vcs.has_outgoing(A, S, P)
    repo.remove(A, S, P, "doc", "card.b", tombstone=True)  # a write outside any group leaves its group
    assert vcs.row(None, A, S, P, "doc", "card.b")["group_id"] == ""


def test_pending_unsent_until_the_person_chooses() -> None:
    _doc("card.a")
    _doc("card.b", dirty=False)
    repo.put(A, S, P, "doc", "card.s", value="x", size=1, sha256="x", dirty=True, sensitive=True)
    _doc("card.t")
    repo.remove(A, S, P, "doc", "card.t", tombstone=True)
    assert vcs.pending_unsent(A, S) == 1
    assert [r["key"] for r in vcs.unsent_rows(A, S)] == ["card.a"]
    vcs.lost_choice_put(A, S, "saved")
    assert vcs.pending_unsent(A, S) == 0 and vcs.lost_choice_get(A, S) == "saved"
    vcs.lost_choice_clear(A, S)
    assert vcs.pending_unsent(A, S) == 1
    with pytest.raises(ValueError):
        vcs.lost_choice_put(A, S, "maybe")


def test_change_log_keeps_the_last_entries_and_says_what_was_trimmed() -> None:
    conn = db.connect()
    with db.write_txn(conn):
        for n in range(vcs.CHANGE_LOG_KEEP + 3):
            vcs.change_log_bump(conn, P, [f"card.{n}"])
        vcs.change_log_bump(conn, P, [f"k{n}" for n in range(vcs.CHANGE_KEYS_MAX + 1)])
    log = vcs.change_log(P)
    assert log["epoch"] == vcs.CHANGE_LOG_KEEP + 4
    assert len(log["changes"]) == vcs.CHANGE_LOG_KEEP and log["trimmed"] == 4
    assert log["changes"][-1] == [log["epoch"], None]  # too many to list
    assert vcs.change_log("other") == {"epoch": 0, "changes": [], "trimmed": 0}


def test_device_id_is_made_once() -> None:
    first = vcs.device_id()
    assert len(first) == 32 and vcs.device_id() == first


def test_forget_space_and_reset_epoch() -> None:
    _doc("card.pip")
    vcs.head_put(A, S, P, seq=7, epoch="e1")
    vcs.cs_add(A, S, P, "cs1", base_seq=7, items=[])
    vcs.lock_put(A, S, P, "doc:card.pip", mine=True, lease_left=300)
    conn = db.connect()
    with db.write_txn(conn):
        vcs.base_put(conn, A, S, P, "card.pip", 7, "s", "v")
    vcs.reset_epoch(A, S, "e2")
    head = vcs.head_get(A, S, P)
    assert (head["seq"], head["epoch"]) == (0, "e2")
    assert vcs.cs_open(A, S) == [] and vcs.locks(A, S) == [] and vcs.base_get(A, S, P, "card.pip") is None
    assert vcs.row(None, A, S, P, "doc", "card.pip") is not None  # the rows wait for the person's choice
    vcs.forget_space(A, S)
    assert vcs.heads(A, S) == {}
