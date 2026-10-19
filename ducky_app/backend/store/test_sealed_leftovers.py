"""What else held chats and duckies in plaintext once they were sealed per account: free
pages of ducky.db (one rebuild), its backups from before, chat attachments of an account
not signed in, the old duckies settings, parked copies (``account_rows``, ``sealed_files``)."""

from __future__ import annotations

import json
import os
import time

import pytest

from backend.store import account_rows, db, sealed_files
from backend.store.repos import duckies
from backend.store.repos import settings as settings_repo
from backend.store.test_account_rows import (
    ALICE,
    BOB,
    ONLINE,
    WORDS,
    _database_from_before,
    _everything_stored,
    _fake_adk,
    _file_bytes,
    _Who,
    _write_chat,
)
from backend.uefn_plugins import data_crypto


@pytest.fixture
def who(monkeypatch: pytest.MonkeyPatch):
    data_crypto.reset_for_tests()
    ONLINE["on"] = True
    monkeypatch.setattr(data_crypto, "_fetch_adk", _fake_adk)
    yield _Who(monkeypatch)
    data_crypto.reset_for_tests()


def _age(path, seconds: float = 3600.0) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


# --------------------------------------------------------------------------- one sealed file


@pytest.mark.parametrize("size", [0, 1, sealed_files.CHUNK, 2 * sealed_files.CHUNK + 5])
def test_a_sealed_file_opens_whole_for_its_account_only(who: _Who, tmp_path, size: int) -> None:
    alice = who.be(ALICE)
    sealed_files.ensure_keypair(alice)
    data = os.urandom(size)
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    _age(path)
    mtime = path.stat().st_mtime
    assert sealed_files.seal_file(path, alice) and not sealed_files.seal_file(path, alice)
    assert path.read_bytes()[:4] == sealed_files.MAGIC and sealed_files.sealed_for(path) == alice
    assert abs(path.stat().st_mtime - mtime) < 1, "a backup keeps its place in the snapshot order"
    assert sealed_files.read_bytes(path, alice) == data
    bob = who.be(BOB)
    with pytest.raises(sealed_files.WrongAccount):
        sealed_files.read_bytes(path, bob)
    who.be(ALICE)
    assert sealed_files.open_file(path, alice) and path.read_bytes() == data


def test_a_cut_or_changed_sealed_file_never_opens(who: _Who, tmp_path) -> None:
    alice = who.be(ALICE)
    sealed_files.ensure_keypair(alice)
    path = tmp_path / "f.bin"
    path.write_bytes(os.urandom(sealed_files.CHUNK + 10))
    sealed_files.seal_file(path, alice)
    whole = path.read_bytes()
    path.write_bytes(whole[: len(whole) - 40])
    with pytest.raises(Exception):
        sealed_files.read_bytes(path, alice)
    changed = bytearray(whole)
    changed[-3] ^= 1
    path.write_bytes(bytes(changed))
    with pytest.raises(Exception):
        sealed_files.read_bytes(path, alice)
    path.write_bytes(whole)
    assert len(sealed_files.read_bytes(path, alice)) == sealed_files.CHUNK + 10


def test_the_keys_survive_restoring_a_backup_from_before_them(who: _Who, tmp_path) -> None:
    alice = who.be(ALICE)
    sealed_files.ensure_keypair(alice)
    path = tmp_path / "f.bin"
    path.write_bytes(b"pelican")
    sealed_files.seal_file(path, alice)
    conn = db.connect()
    with db.write_txn(conn):  # an older ducky.db swapped in: no keypair rows in it
        conn.execute("DELETE FROM meta WHERE key LIKE 'file_key_%'")
    sealed_files.forget()
    assert sealed_files.read_bytes(path, alice) == b"pelican"
    sealed_files.ensure_keypair(alice)  # writes the same pair back, never a new one
    assert sealed_files.read_bytes(path, alice) == b"pelican"


# --------------------------------------------------------------------------- chat attachments


def _attach(conv_id: str, text: bytes = b"the pelican plans") -> tuple[object, str]:
    from frontend.ui_web import conversation_attachments as ca

    saved = ca.save_chat_file(conv_id, "plans.txt", text)
    assert saved["ok"], saved
    from pathlib import Path

    return Path(saved["path"]), Path(saved["path"]).name


def test_attachments_are_sealed_while_their_owner_is_away(who: _Who) -> None:
    alice = who.be(ALICE)
    _write_chat("chat-a")
    path, _name = _attach("chat-a")
    account_rows.seal_pending(alice, pause_s=0)
    assert path.read_bytes() == b"the pelican plans", "plain while Alice is here: agents read it by path"

    bob = who.be(BOB)
    out = account_rows.seal_pending(bob, pause_s=0)
    assert out.get("attachments_sealed") == 1 and sealed_files.sealed_for(path) == alice
    assert b"pelican" not in path.read_bytes()

    who.be(ALICE)
    assert account_rows.seal_pending(alice, pause_s=0).get("attachments_opened") == 1
    assert path.read_bytes() == b"the pelican plans"


def test_an_attachment_read_before_the_pass_is_opened_on_the_spot(who: _Who) -> None:
    from frontend.ui_web import conversation_attachments as ca
    from frontend.ui_web.project_chats import get_conversations_dir

    alice = who.be(ALICE)
    _write_chat("chat-a")
    path, name = _attach("chat-a")
    account_rows.seal_pending(alice, pause_s=0)
    account_rows.seal_pending(who.be(BOB), pause_s=0)
    assert sealed_files.is_sealed_file(path)
    who.be(ALICE)  # no pass yet
    row = ca.hydrate_attachment_dict({"kind": "file", "path": f"attachments/{name}"}, "chat-a", get_conversations_dir())
    assert row["text"] == "the pelican plans" and path.read_bytes() == b"the pelican plans"


def test_an_owner_who_never_signed_in_here_again_is_sealed_when_they_do(who: _Who) -> None:
    alice = who.be(ALICE)
    _write_chat("chat-a")
    path, _name = _attach("chat-a")
    # No seal pass of Alice's on this build yet, so she has no file keys.
    bob = who.be(BOB)
    assert account_rows.seal_pending(bob, pause_s=0).get("attachments_left") == 1
    assert path.read_bytes() == b"the pelican plans"
    account_rows.seal_pending(who.be(ALICE), pause_s=0)
    account_rows.seal_pending(who.be(BOB), pause_s=0)
    assert sealed_files.sealed_for(path) == alice


# --------------------------------------------------------------------------- a database from before


def _with_old_extras(monkeypatch) -> None:
    """The database from before, plus the duckies settings and a deleted row whose bytes
    are still in a free page."""
    _database_from_before(monkeypatch)
    conn = db.connect()
    with db.write_txn(conn):
        conn.executemany(
            "INSERT INTO settings(key, value, updated) VALUES (?, ?, 0)",
            [("agent_profiles", json.dumps([{"id": "custom-old", "name": "Pelican builder"}])),
             ("archived_agent_profile_ids", json.dumps(["material-artist"]))],
        )
        conn.execute("INSERT OR REPLACE INTO meta(key, value, updated) VALUES ('imported:duckies', '{}', 0)")
    conn.execute("PRAGMA secure_delete=OFF")
    with db.write_txn(conn):
        conn.execute("CREATE TABLE scratch_old(t TEXT)")
        conn.executemany("INSERT INTO scratch_old VALUES (?)", [("harbour pelican " * 40,)] * 2000)
    with db.write_txn(conn):
        conn.execute("DROP TABLE scratch_old")
    settings_repo.forget_snapshot()


def test_the_old_duckies_settings_go_sealed_into_meta(who: _Who, monkeypatch) -> None:
    who.key = ALICE
    _with_old_extras(monkeypatch)
    alice = account_rows.current()
    out = account_rows.seal_pending(alice, pause_s=0)
    assert out["settings"] == 2
    conn = db.connect()
    assert conn.execute(
        "SELECT count(*) FROM settings WHERE key IN ('agent_profiles', 'archived_agent_profile_ids')"
    ).fetchone()[0] == 0
    kept = conn.execute("SELECT value FROM meta WHERE key=?", ("legacy_duckies_settings:" + alice,)).fetchone()[0]
    assert json.loads(json.loads(account_rows.open_text(kept, alice))["agent_profiles"])[0]["name"] == "Pelican builder"
    assert duckies.get("custom-old")["data"] == {"name": "Pelican builder"}, "the duckies table still has them"
    # A stale copy in memory never writes them back.
    assert settings_repo.save_fields({"agent_profiles": [{"id": "x", "name": "Stale pelican"}]}, {"agent_profiles": []}) == []
    for word in WORDS:
        assert word not in _everything_stored()


def test_one_rebuild_after_sealing_leaves_no_old_plaintext_in_the_file(who: _Who, monkeypatch) -> None:
    who.key = ALICE
    _with_old_extras(monkeypatch)
    alice = account_rows.current()
    assert b"pelican" in _file_bytes()
    out = account_rows.seal_pending(alice, pause_s=0)
    assert out["rebuild_next_start"] == 1
    marker = db.db_path().parent / db.VACUUM_PENDING_NAME
    assert marker.is_file()
    assert b"pelican" in _file_bytes(), "sealed rows, but the old bytes are still in free pages"

    # The next start: another process still has ducky.db open, so it waits.
    db.reset_for_tests()
    holder = open(db.db_path(), "rb")
    try:
        db.connect()
        if os.name == "nt":
            assert json.loads(marker.read_text())["waits"] == 1
    finally:
        holder.close()
    db.reset_for_tests()
    db.connect()
    assert not marker.exists()
    raw = _file_bytes()
    assert b"pelican" not in raw and b"harbour" not in raw
    assert account_rows.seal_pending(alice, pause_s=0) == {}, "nothing left, no second rebuild"
    assert not marker.exists()


def test_backups_from_before_are_sealed_for_the_account_the_rows_went_to(who: _Who, monkeypatch) -> None:
    from frontend import store_admin

    who.key = ALICE
    _database_from_before(monkeypatch)
    alice = account_rows.current()
    [snap] = list(db.snapshot_dir().glob("ducky-*-pre-migrate-v23.db"))
    replaced = db.db_path().parent / (db.DB_NAME + ".replaced-20261001-000000-1")
    replaced.write_bytes(snap.read_bytes())
    for p in (snap, replaced):
        _age(p)
    assert b"pelican" in snap.read_bytes()
    out = account_rows.seal_pending(alice, pause_s=0)
    assert out["backups"] == 2
    for p in (snap, replaced):
        assert sealed_files.sealed_for(p) == alice and b"pelican" not in p.read_bytes()
    # Alice can still check and restore it; Bob can't.
    assert db.check_db_file(snap) == "ok"
    assert store_admin.stage_restore(snap.name)["ok"]
    store_admin.cancel_restore()
    who.be(BOB)
    staged = store_admin.stage_restore(snap.name)
    assert not staged["ok"] and "another Ducky account" in staged["error"]
    assert not (db.db_path().parent / db.RESTORE_PENDING_NAME).exists()
    # A backup made well after everything was sealed is a plain copy (its rows are sealed).
    who.be(ALICE)
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("UPDATE meta SET value=? WHERE key='rows_sealed_at'", (str(time.time() - 1000),))
    fresh = db.snapshot(label="after")
    _age(fresh, 120)
    account_rows.seal_pending(alice, pause_s=0)
    assert not sealed_files.is_sealed_file(fresh)


def test_a_corrupt_database_restores_from_a_plain_snapshot_first(who: _Who, monkeypatch) -> None:
    who.key = ALICE
    _database_from_before(monkeypatch)
    alice = account_rows.current()
    [old] = list(db.snapshot_dir().glob("ducky-*.db"))
    _age(old, 7200)
    account_rows.seal_pending(alice, pause_s=0)
    assert sealed_files.is_sealed_file(old)
    fresh = db.snapshot(label="after")
    _age(fresh, 7300)  # older than the sealed one, still tried first
    assert db.restore_snapshot() == fresh
    db.reset_for_tests()
    assert db.integrity_check(db.connect()) == "ok"


def test_parked_copies_are_sealed_for_the_account_that_claimed_them(who: _Who) -> None:
    alice = who.be(ALICE)
    duckies.save("material-artist", "bundled", {"name": "Alice's edit"})
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO duckies(id, ducky_id, kind, data, created, updated) VALUES "
            "('material-artist', 'material-artist', 'bundled', '{\"name\": \"stale pelican\"}', 0, 0)"
        )
    account_rows.current()
    account_rows.seal_pending(alice, pause_s=0)
    [(data,)] = conn.execute(
        "SELECT data FROM duckies WHERE substr(account_id, 1, 8) = ?", (account_rows.PARKED,)
    ).fetchall()
    assert data.startswith("enc1:") and "pelican" in account_rows.open_text(data, alice)
