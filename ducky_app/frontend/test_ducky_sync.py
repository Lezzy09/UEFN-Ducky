"""Chat and Ducky sync between your UEFN Duckies (frontend.ducky_sync), the link mocked."""

from __future__ import annotations

from typing import Any

import pytest

from backend.store.repos import duckies as repo
from backend.store.repos import ducky_mirrors as mirrors
from frontend import ducky_sync

ACCOUNT = "a_test"


# --------------------------------------------------------------------------- duckies


def test_a_newer_ducky_from_another_ducky_comes_in_and_an_older_one_does_not() -> None:
    assert repo.save_synced("c1", "custom", {"name": "Builder"}, 100.0)
    assert repo.get("c1")["data"] == {"name": "Builder"} and repo.get("c1")["updated"] == 100.0
    assert not repo.save_synced("c1", "custom", {"name": "Old"}, 50.0), "older there: kept here"
    assert not repo.save_synced("c1", "custom", {"name": "Builder"}, 200.0), "same data: no write, no echo"
    assert repo.save_synced("c1", "custom", {"name": "Builder 2"}, 300.0)
    assert repo.get("c1")["data"] == {"name": "Builder 2"}
    # Every change kept the copy it replaced.
    assert [h["data"] for h in repo.history("c1")] == [{"name": "Builder"}]


def test_sync_never_archives_deletes_or_removes_here() -> None:
    repo.save("c2", "custom", {"name": "Mine"})
    repo.set_deleted("c2", True)
    repo.save("c3", "custom", {"name": "Hidden"})
    repo.set_archived("c3", "custom", True)
    changed = ducky_sync.apply_duckies([
        {"id": "c2", "kind": "custom", "data": {"name": "Mine v2"}, "archived": False, "updated": 9e12},
        {"id": "c3", "kind": "custom", "data": {"name": "Hidden v2"}, "archived": False, "updated": 9e12},
        # Archived over there and not here: it doesn't turn up.
        {"id": "c4", "kind": "custom", "data": {"name": "Archived there"}, "archived": True, "updated": 9e12},
        {"id": "", "kind": "custom", "data": {"name": "no id"}},
        {"id": "c5", "kind": "weird", "data": {"name": "bad kind"}},
        "not a row",
    ])
    assert changed == 2
    assert repo.get("c2")["deleted"] > 0 and repo.get("c2")["data"] == {"name": "Mine v2"}
    assert repo.get("c3")["archived"] is True
    assert repo.get("c4") is None and repo.get("c5") is None


def test_this_duckys_duckies_go_out_without_deleted_ones() -> None:
    repo.save("c6", "custom", {"name": "Out"})
    repo.save("c7", "custom", {"name": "Gone"})
    repo.set_deleted("c7", True)
    sent = {r["id"] for r in ducky_sync.duckies_for_sync()}
    assert "c6" in sent and "c7" not in sent


# --------------------------------------------------------------------------- chats


class _Peer:
    """Another UEFN Ducky answering through the link."""

    def __init__(self) -> None:
        self.chats = [
            {"id": "x1", "title": "Lobby", "updated": 10.0},
            {"id": "x2", "title": "Shop", "updated": 20.0},
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_rows: set[str] = set()

    def call(self, to: str, method: str, args: dict[str, Any] | None = None, **_kw: Any) -> dict[str, Any]:
        assert to == "k2"
        self.calls.append((method, dict(args or {})))
        if method == "ducky_sync_duckies":
            return {"ok": True, "result": [{"id": "c8", "kind": "custom", "data": {"name": "From laptop"}, "updated": 5.0}]}
        if method == "ducky_sync_chats":
            return {"ok": True, "result": list(self.chats)}
        if method == "ducky_sync_rows":
            if args["conv_id"] in self.fail_rows:
                return {"ok": False, "error": "busy"}
            return {"ok": True, "result": [{"id": 0, "role": "user", "text": f"hi {args['conv_id']}"}]}
        raise AssertionError(method)


@pytest.fixture
def peer(monkeypatch: pytest.MonkeyPatch) -> _Peer:
    from frontend import ducky_link

    p = _Peer()
    monkeypatch.setattr(ducky_link, "call", p.call)
    monkeypatch.setattr(ducky_sync, "_account", lambda: ACCOUNT)
    return p


LAPTOP = {"keyId": "k2", "name": "Laptop", "live": True}


def _pulled(p: _Peer) -> list[str]:
    return [a["conv_id"] for m, a in p.calls if m == "ducky_sync_rows"]


def test_a_round_copies_the_duckies_and_the_changed_chats(peer: _Peer) -> None:
    out = ducky_sync.sync_with(LAPTOP)
    assert out == {"ok": True, "ducky": "Laptop", "duckies": 1, "chats": 2}
    assert repo.get("c8")["data"] == {"name": "From laptop"}
    assert _pulled(peer) == ["x2", "x1"], "newest first"
    [laptop] = ducky_sync.mirror_list()
    assert laptop["name"] == "Laptop" and [c["conv_id"] for c in laptop["chats"]] == ["x2", "x1"]
    assert ducky_sync.mirror_rows("k2", "x1")["rows"] == [{"id": 0, "role": "user", "text": "hi x1"}]

    # Nothing changed there: nothing pulled again.
    peer.calls.clear()
    ducky_sync.sync_with(LAPTOP)
    assert _pulled(peer) == []

    # One chat changed there, one gone: only it is pulled, the gone one leaves the list.
    peer.chats = [{"id": "x1", "title": "Lobby v2", "updated": 30.0}]
    peer.calls.clear()
    ducky_sync.sync_with(LAPTOP)
    assert _pulled(peer) == ["x1"]
    [laptop] = ducky_sync.mirror_list()
    assert [(c["conv_id"], c["title"]) for c in laptop["chats"]] == [("x1", "Lobby v2")]
    assert ducky_sync.mirror_rows("k2", "x2") is not None, "the copy stays, out of the list"


def test_a_failed_pull_is_tried_again_next_round(peer: _Peer) -> None:
    peer.fail_rows = {"x1"}
    ducky_sync.sync_with(LAPTOP)
    assert _pulled(peer) == ["x2", "x1"]
    peer.fail_rows = set()
    peer.calls.clear()
    ducky_sync.sync_with(LAPTOP)
    assert _pulled(peer) == ["x1"]


def test_another_accounts_copies_never_show() -> None:
    mirrors.note_peer("a_other", "k9", "Theirs")
    mirrors.note_chat("a_other", "k9", "z1", "Secret", 1.0)
    assert mirrors.peers(ACCOUNT) == []
    assert mirrors.rows(ACCOUNT, "k9", "z1") is None


def test_a_long_chat_is_trimmed_to_fit_one_sealed_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from frontend.ui_web import panel_api

    big = [{"id": i, "role": "assistant", "text": "y" * 3_900} for i in range(60)]

    class _Api:
        def load_messages(self, conv_id: str, before_id: Any = None, limit: Any = None) -> list[dict[str, Any]]:
            assert limit == ducky_sync.ROWS_KEPT
            return big

    monkeypatch.setattr(panel_api, "shared_panel_api", lambda: _Api())
    rows = ducky_sync.rows_for_sync("c1")
    assert sum(len(r["text"]) for r in rows) <= ducky_sync._ROWS_TEXT_BUDGET
    assert rows[-1]["id"] == 59, "the newest rows are kept"


def test_the_mailbox_answers_the_sync_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from frontend.duckyos_account import RPC_ALLOWLIST, dispatch_desktop_rpc

    monkeypatch.setattr(ducky_sync, "chats_for_sync", lambda: [{"id": "c1"}])
    monkeypatch.setattr(ducky_sync, "rows_for_sync", lambda conv_id: [{"id": 0, "text": conv_id}])
    for name in ("ducky_sync_duckies", "ducky_sync_chats", "ducky_sync_rows"):
        assert name in RPC_ALLOWLIST
    assert dispatch_desktop_rpc("ducky_sync_chats") == {"ok": True, "result": [{"id": "c1"}]}
    assert dispatch_desktop_rpc("ducky_sync_rows", {"conv_id": "c9"}) == {"ok": True, "result": [{"id": 0, "text": "c9"}]}
    assert dispatch_desktop_rpc("ducky_sync_duckies")["ok"] is True


def test_slim_rows_keep_who_and_what() -> None:
    rows = ducky_sync.slim_rows([
        {"id": 1, "role": "user", "text": "Build it", "attachments": [{"big": "x"}]},
        {"id": 2, "role": "assistant", "text": "", "thinking": "hmm"},
        {"id": 3, "role": "tool", "text": "t" * 900, "tool": {"result": "huge"}},
        "junk",
    ])
    assert rows == [
        {"id": 1, "role": "user", "text": "Build it"},
        {"id": 3, "role": "tool", "text": "t" * 300},
    ]
