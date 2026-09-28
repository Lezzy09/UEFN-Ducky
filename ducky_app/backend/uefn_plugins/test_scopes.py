"""P3/P4 checks: plugin data scopes on one PC + team sync against a fake Store.

Plan P3: two accounts never see each other's rows or folders; switching project
switches data; signed-out ``_local`` is separate; ``sensitive`` docs never reach a
sync request; BrainrotTCG cards sync between two members and never to a third
team; paused = read-only; access lost deletes the team scope; the inclusive
cursor is deduped; a stale push adopts the server copy.
"""

from __future__ import annotations

import hashlib
import itertools
import sys
from typing import Any

import pytest

from backend.store.repos import plugin_data as repo
from backend.uefn_plugins import scopes, team_sync
from backend.uefn_plugins.scopes import PluginData


class _Who:
    """Which account is signed in and which project is open (both read at call time)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from frontend import duckyos_account

        self.account, self.project = "", ""
        monkeypatch.setattr(duckyos_account, "account_key", lambda blob=None: self.account)
        monkeypatch.setattr(scopes, "current_project", lambda: self.project)

    def be(self, email: str, project: str = "proj") -> str:
        self.account = f"https://uefnducky.org|{email}" if email else ""
        self.project = project
        return scopes.account_id()


@pytest.fixture
def who(monkeypatch: pytest.MonkeyPatch) -> _Who:
    return _Who(monkeypatch)


class FakeStore:
    """The Store's team-data contract in memory: inclusive cursor, last write wins,
    per-team membership, paused plans."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self.rev: dict[str, int] = {}
        self.members: dict[str, set[str]] = {}
        self.paused: set[str] = set()
        self.blobs: dict[str, bytes] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []
        self._ids = itertools.count(1)

    def transport(self, account: str) -> "_Transport":
        return _Transport(self, account)

    def view(self, team: str, item: tuple[str, str, str]) -> dict[str, Any]:
        row = self.rows[(team, *item)]
        out = {"kind": item[0], "pluginId": item[1], "key": item[2], "rev": row["rev"], "size": row["size"],
               "sha256": row["sha256"], "deleted": row["deleted"]}
        if not row["deleted"]:
            url = f"get://{next(self._ids)}"
            self.blobs[url] = row["blob"]
            out["getUrl"] = url
        return out


class _Transport:
    def __init__(self, store: FakeStore, account: str) -> None:
        self.s, self.account = store, account

    def collect(self, event: str, body: dict[str, Any]) -> dict[str, Any]:
        s, team = self.s, body["teamId"]
        s.requests.append({"event": event, **body})
        if self.account not in s.members.get(team, set()):
            raise team_sync.SyncError("team not found")
        if team in s.paused:
            raise team_sync.SyncError("plan_paused: Team Private isn't active for this team.")
        if event == "team-data-commit":
            results = []
            for c in body["commits"]:
                item = (c["kind"], c["pluginId"], c["key"])
                up = next((u for u in s.uploads.values() if u["team"] == team and u["item"] == item), None)
                row = s.rows.get((team, *item))
                if up is None or (row["rev"] if row else 0) != c["rev"]:
                    results.append({**dict(zip(("kind", "pluginId", "key"), item)), "status": "stale",
                                    "server": s.view(team, item) if row else None})
                    continue
                s.rev[team] = s.rev.get(team, 0) + 1
                blob = s.blobs[up["url"]]
                s.rows[(team, *item)] = {"rev": s.rev[team], "size": len(blob), "sha256": up["sha256"],
                                         "deleted": False, "blob": blob}
                del s.uploads[up["url"]]
                results.append({**dict(zip(("kind", "pluginId", "key"), item)), "status": "committed",
                                "rev": s.rev[team]})
            return {"results": results, "usage": {"usedBytes": 1}}
        accepted, deleted, stale = [], [], []
        for p in body.get("pushes") or []:
            item = (p["kind"], p["pluginId"], p["key"])
            row = s.rows.get((team, *item))
            named = dict(zip(("kind", "pluginId", "key"), item))
            if p["baseRev"] != (row["rev"] if row else 0):
                stale.append({**named, "server": s.view(team, item) if row else None})
            elif p.get("delete"):
                s.rev[team] = s.rev.get(team, 0) + 1
                row.update(rev=s.rev[team], deleted=True, blob=b"", size=0)
                deleted.append({**named, "rev": s.rev[team]})
            else:
                url = f"put://{next(s._ids)}"
                s.uploads[url] = {"team": team, "item": item, "url": url, "sha256": p["sha256"]}
                accepted.append({**named, "rev": p["baseRev"], "putUrl": url, "expiresAt": 0})
        cursor = int(body.get("cursorRev") or 0)
        changes = [s.view(team, k[1:]) for k, r in sorted(s.rows.items(), key=lambda kv: kv[1]["rev"])
                   if k[0] == team and r["rev"] >= cursor]
        return {"cursorRev": max(s.rev.get(team, 0), cursor), "more": False, "changes": changes,
                "accepted": accepted, "deleted": deleted, "stale": stale, "refused": [],
                "usage": {"usedBytes": sum(r["size"] for k, r in s.rows.items() if k[0] == team),
                          "limitBytes": 5 << 30}}

    def put(self, url: str, data: bytes) -> None:
        self.s.blobs[url] = data

    def get(self, url: str) -> bytes:
        return self.s.blobs[url]


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """Every Store call the host makes (first pulls included) goes to this fake."""
    fake = FakeStore()
    monkeypatch.setattr(team_sync, "Transport", lambda: fake.transport(scopes.account_id()))
    monkeypatch.setattr(team_sync, "_FIRST_PULL_TRIED", set())
    return fake


def _sync(store: FakeStore) -> dict[str, Any]:
    s = scopes.active_scope()
    return team_sync.sync_team(s["account"], s["id"], force=True, transport=store.transport(s["account"]))


def _join(store: FakeStore, who: _Who, email: str, team: str, label: str) -> str:
    aid = who.be(email)
    store.members.setdefault(team, set()).add(aid)
    scopes.link_project(team, label=label, members=2)
    return aid


# --------------------------------------------------------------------------- scopes on one PC


def test_accounts_projects_and_local_never_share_rows_or_folders(who: _Who, store: FakeStore) -> None:
    from frontend.ui_web import plugin_host_api as pha

    cards = PluginData("brainrot-tcg")
    ana = who.be("ana@x.org")
    cards.put("card.pip", {"name": "Pip"})
    cards.put_file("assets/pip.png", b"PNG-ana")
    pha.cache_set("brainrot-tcg", "ui", {"tab": "cards"})
    ana_dir = cards.folder()

    bo = who.be("bo@x.org")
    assert bo != ana and cards.get("card.pip") is None and cards.keys() == [] and cards.files() == []
    assert pha.cache_get("brainrot-tcg", "ui") == {}
    assert cards.folder() != ana_dir and ana not in str(cards.folder())

    local = who.be("")
    assert local == scopes.LOCAL and cards.get("card.pip") is None
    cards.put("card.pip", {"name": "Local Pip"})

    who.be("ana@x.org", project="other")
    assert cards.get("card.pip") == {"name": "Pip"}  # Personal follows the account, any project
    assert cards.get_file("assets/pip.png") == b"PNG-ana"

    # Switching project switches data: this project → team T, the other stays Personal.
    store.members["teamT"] = {who.be("ana@x.org", project="game")}
    scopes.link_project("teamT", label="Alpha Studio")
    assert scopes.active_scope()["label"] == "Alpha Studio" and cards.keys() == []
    cards.put("card.pip", {"name": "Team Pip"})
    who.be("ana@x.org", project="other")
    assert cards.get("card.pip") == {"name": "Pip"}
    who.be("ana@x.org", project="game")
    assert cards.get("card.pip") == {"name": "Team Pip"}
    who.be("")
    assert cards.get("card.pip") == {"name": "Local Pip"}


def test_sensitive_docs_stay_personal_and_never_reach_a_sync_request(who: _Who, store: FakeStore, monkeypatch) -> None:
    from backend.agent import secrets as sec

    monkeypatch.setattr(sec, "protect_text", lambda s: b"blob-" + s.encode())
    monkeypatch.setattr(sec, "unprotect_text", lambda b: b[5:].decode())
    _join(store, who, "ana@x.org", "teamT", "Alpha Studio")
    data = PluginData("discord")
    data.put("token", {"bot": "very-secret"}, sensitive=True)
    data.put("channel", {"id": 7})
    assert data.get("token", sensitive=True) == {"bot": "very-secret"}
    assert "token" not in data.keys()
    assert _sync(store)["state"] == "ok"
    pushed = [p["key"] for r in store.requests for p in r.get("pushes") or []]
    assert pushed == ["channel"] and "very-secret" not in repr(store.requests)


# --------------------------------------------------------------------------- team sync


def test_cards_sync_between_members_and_never_to_another_team(who: _Who, store: FakeStore) -> None:
    cards = PluginData("brainrot-tcg")
    _join(store, who, "ana@x.org", "teamT", "Alpha Studio")
    cards.put("card.pip", {"name": "Pip", "attack": 1700})
    cards.put_file("assets/pip.png", b"\x89PNG pip")
    assert _sync(store)["state"] == "ok"
    assert repo.count_dirty(scopes.account_id(), "teamT") == 0

    _join(store, who, "bo@x.org", "teamT", "Alpha Studio")
    out = _sync(store)
    assert out["changed"] == ["brainrot-tcg"]
    assert cards.get("card.pip") == {"attack": 1700, "name": "Pip"}
    assert cards.get_file("assets/pip.png") == b"\x89PNG pip"

    # Bo edits and deletes; Ana gets both.
    cards.put("card.pip", {"name": "Pip", "attack": 1900})
    cards.delete_file("assets/pip.png")
    _sync(store)
    who.be("ana@x.org")
    _sync(store)
    assert cards.get("card.pip")["attack"] == 1900 and cards.get_file("assets/pip.png") is None

    # A member of team U only never sees team T's cards, and can't ask for team T.
    cy = _join(store, who, "cy@x.org", "teamU", "Beta Crew")
    _sync(store)
    assert cards.keys() == [] and cards.files() == []
    assert team_sync.sync_team(cy, "teamT", force=True, transport=store.transport(cy))["state"] == "removed"
    assert repo.rows(cy, "teamT", "brainrot-tcg", "doc") == []


def test_inclusive_cursor_is_deduped_and_stale_push_adopts_server(who: _Who, store: FakeStore) -> None:
    cards = PluginData("brainrot-tcg")
    ana = _join(store, who, "ana@x.org", "teamT", "Alpha Studio")
    cards.put("card.pip", {"v": 1})
    _sync(store)
    before = repo.get(ana, "teamT", "brainrot-tcg", "doc", "card.pip")
    # The next round gets card.pip again (rev >= cursor): nothing re-downloaded or changed.
    assert _sync(store)["changed"] == []
    assert repo.get(ana, "teamT", "brainrot-tcg", "doc", "card.pip") == before

    # Bo writes v2 first; Ana's offline edit (base rev 1) is stale → Ana adopts v2.
    _join(store, who, "bo@x.org", "teamT", "Alpha Studio")
    _sync(store)
    cards.put("card.pip", {"v": 2})
    _sync(store)
    who.be("ana@x.org")
    cards.put("card.pip", {"v": "ana-offline"})
    assert _sync(store)["changed"] == ["brainrot-tcg"]
    assert cards.get("card.pip") == {"v": 2} and repo.count_dirty(ana, "teamT") == 0


def test_paused_is_read_only_and_access_lost_deletes_the_team_scope(who: _Who, store: FakeStore) -> None:
    cards = PluginData("brainrot-tcg")
    ana = _join(store, who, "ana@x.org", "teamT", "Alpha Studio")
    cards.put("card.pip", {"v": 1})
    cards.put_file("assets/pip.png", b"pip")
    _sync(store)
    team_dir = scopes.scopes_root(ana) / "teamT"
    assert team_dir.is_dir()

    store.paused.add("teamT")
    assert _sync(store)["state"] == "paused"
    assert scopes.active_scope()["readOnly"] and cards.get("card.pip") == {"v": 1}
    with pytest.raises(scopes.ReadOnlyScope):
        cards.put("card.pip", {"v": 2})
    store.paused.clear()
    assert _sync(store)["state"] == "ok" and not scopes.active_scope()["readOnly"]

    store.members["teamT"].discard(ana)
    assert _sync(store)["state"] == "removed"
    assert not team_dir.exists() and repo.rows(ana, "teamT", "brainrot-tcg", "doc") == []
    assert scopes.active_scope()["kind"] == "personal"  # the project link went with it


def test_scope_picker_lists_only_active_team_private_and_hides_without_beta(who: _Who, monkeypatch) -> None:
    from frontend import duckyos_account

    who.be("ana@x.org")
    teams = [
        {"id": "teamT", "name": "Alpha Studio", "members": [{}, {}, {}], "private_plan": {"status": "active"}},
        {"id": "teamF", "name": "Free Team", "members": [{}], "private_plan": None},
        {"id": "teamP", "name": "Paused Crew", "members": [{}], "private_plan": {"status": "paused"}},
    ]
    monkeypatch.setattr(duckyos_account, "teams_snapshot", lambda **_: {"ok": True, "teams": teams})
    monkeypatch.setattr(team_sync, "teams_enabled", lambda: False)
    assert [c["id"] for c in team_sync.scope_choices()["choices"]] == ["personal"]
    assert team_sync.scope_status()["visible"] is False  # rule 13: no bar, no teaser
    monkeypatch.setattr(team_sync, "teams_enabled", lambda: True)
    choices = team_sync.scope_choices()["choices"]
    assert [(c["id"], c.get("members")) for c in choices] == [("personal", None), ("teamT", 3)]
    status = team_sync.link_scope("teamT")
    # Fresh link: read-only "waiting" until the first pull lands.
    assert status["scope"] == {"kind": "team", "label": "Alpha Studio", "teamId": "teamT", "readOnly": True}
    assert status["visible"] and status["state"] == "waiting" and status["members"] == 3 and status["pending"] == 0


class _Offline:
    def collect(self, event: str, body: dict[str, Any]) -> dict[str, Any]:
        raise team_sync.SyncError("Network error: offline", offline=True)


def test_first_use_of_a_team_pulls_before_a_plugin_can_seed_defaults(who: _Who, store: FakeStore, monkeypatch) -> None:
    def load_or_seed(data: PluginData) -> dict[str, Any]:
        """What BrainrotTCG's load_db does: an empty scope gets the bundled defaults."""
        docs = data.items()
        if not docs:
            data.put("meta", {"seeded": True})
            data.put("card.default", {"name": "Seed"})
            return data.items()
        return docs

    cards = PluginData("brainrot-tcg")
    _join(store, who, "ana@x.org", "teamT", "Alpha Studio")
    cards.put("meta", {"team": True})
    cards.put("card.pip", {"name": "Pip"})
    _sync(store)

    # Bo links the team for the first time: the first pull lands before the plugin reads.
    _join(store, who, "bo@x.org", "teamT", "Alpha Studio")
    assert load_or_seed(cards) == {"card.pip": {"name": "Pip"}, "meta": {"team": True}}

    # Cy's first use is offline: read-only "waiting", the seed is refused, nothing reaches the team.
    cy = _join(store, who, "cy@x.org", "teamT", "Alpha Studio")
    monkeypatch.setattr(team_sync, "Transport", _Offline)
    with pytest.raises(scopes.ReadOnlyScope, match="Waiting for team data"):
        load_or_seed(cards)
    assert scopes.active_scope()["state"] == "waiting"
    # Back online, the minute sync brings the team's copy and the scope opens.
    assert team_sync.sync_team(cy, "teamT", force=True, transport=store.transport(cy))["state"] == "ok"
    assert load_or_seed(cards)["card.pip"] == {"name": "Pip"}
    assert not scopes.active_scope()["readOnly"]
    assert not any(k[3] == "card.default" for k in store.rows)


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")
def test_a_bridge_process_follows_an_account_switch_made_in_the_app(monkeypatch) -> None:
    """The MCP bridge caches secrets per process: after the app signs in as another
    account, the bridge's next tool write lands in the new account's scope."""
    import json

    from backend.agent import secrets as sec
    from backend.store.repos import secrets as secrets_repo

    monkeypatch.setattr(scopes, "current_project", lambda: "")
    login = lambda email: json.dumps({"base_url": "https://uefnducky.org", "email": email, "device_key": "dky_v1_x"})  # noqa: E731
    sec.set_key("duckyos_account", login("ana@x.org"))
    cards = PluginData("brainrot-tcg")
    cards.put("card.a", {"by": "ana"})
    ana = scopes.account_id()
    # The app (another process) signs in as Bo: only the stored row changes; this process's cache still says Ana.
    secrets_repo.set_blob("duckyos_account", sec.protect_text(login("bo@x.org")))
    assert "ana@x.org" in (sec.get_key("duckyos_account") or "")
    cards.put("card.b", {"by": "bo"})
    bo = scopes.account_id()
    assert bo != ana
    assert repo.get(bo, "personal", "brainrot-tcg", "doc", "card.b") is not None
    assert repo.get(ana, "personal", "brainrot-tcg", "doc", "card.b") is None


def test_ids_and_paths_cannot_climb() -> None:
    assert scopes.valid_asset_path("assets/cards/pip.png")
    for bad in ("../x", "a/../b", ".hidden", "a//b", "A.png", "a\\b", "x" * 257):
        assert not scopes.valid_asset_path(bad), bad
    assert not scopes.valid_doc_key("a/b") and not scopes.valid_team_id("personal")
    assert hashlib.sha256(scopes.encode_doc({"b": 1, "a": 2})).hexdigest() == hashlib.sha256(
        b'{"a":2,"b":1}').hexdigest()
