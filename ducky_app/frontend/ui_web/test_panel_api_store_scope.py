"""The scope bar's bridge: switching away from a shared space sends its queued changes
first; Retry and Drop my change for changes that aren't going out; Upload my copy and
Clear my copy, for the space's whole copy, after its data was reset on the server.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")

from backend.store.repos import plugin_data as repo
from backend.uefn_plugins import scopes, spaces
from backend.uefn_plugins import test_scopes
from backend.uefn_plugins.scopes import PluginData
from backend.uefn_plugins.test_scopes import FakeSpaces, open_space
import frontend.ui_web.panel_api  # noqa: F401, E402 - panel_api_store is imported through it
from frontend.ui_web import panel_api_store
from frontend.ui_web.panel_api_store import PanelApiStoreMixin

account_keys = test_scopes.account_keys
who = test_scopes.who

PLUGIN = "brainrot-tcg"


class Sending(FakeSpaces):
    """A round sends every queued change (rev 1) and notes where the plugin was linked."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[str, bool, str]] = []
        self.hang: threading.Event | None = None

    def sync(self, account: str, space_id: str, *, force: bool = False) -> dict[str, Any]:
        self.seen.append((space_id, force, repo.link_get(account, PLUGIN)))
        if self.hang is not None:
            self.hang.wait(30)
            return {"state": "ok", "changed": [], "error": ""}
        for row in repo.dirty(account, space_id, 100):
            repo.mark_pushed(account, space_id, row["plugin_id"], row["kind"], row["key"], rev=1, sha256=row["sha256"],
                             pushed_delete=bool(row["deleted"]))
        return {"state": "ok", "changed": [], "error": ""}


class Api(PanelApiStoreMixin):
    def __init__(self) -> None:
        self.pushed: list[dict[str, Any]] = []

    def _push_panel(self, event: dict[str, Any]) -> None:
        self.pushed.append(event)


@pytest.fixture
def fake(account_keys, monkeypatch: pytest.MonkeyPatch) -> Sending:
    from backend.uefn_plugins import host

    monkeypatch.setattr(host, "reload_single_plugin", lambda pid: None)
    impl = Sending()
    spaces.install_for_tests(impl)
    yield impl
    spaces.reset_for_tests()


def test_switching_away_sends_the_old_spaces_changes_before_relinking(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    PluginData(PLUGIN).put("card.pip", {"name": "Pip"})
    out = Api().plugin_scope_set(PLUGIN, "personal")
    assert fake.seen[0] == ("spaceT", True, "spaceT")  # still linked to the team while it sent
    assert out["unsent"] == 0 and out["unsentLabel"] == "Alpha" and out["scope"]["kind"] == "personal"
    assert repo.link_get(aid, PLUGIN) == "personal" and repo.count_dirty(aid, "spaceT") == 0


def test_a_switch_waits_for_the_send_only_so_long_and_says_what_stayed(who, fake: Sending, monkeypatch) -> None:
    monkeypatch.setattr(panel_api_store, "SWITCH_SEND_TIMEOUT_S", 0.3)
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    PluginData(PLUGIN).put("card.pip", {"name": "Pip"})
    fake.hang = threading.Event()
    try:
        began = time.monotonic()
        out = Api().plugin_scope_set(PLUGIN, "personal")
        assert time.monotonic() - began < 2.0
    finally:
        fake.hang.set()
    assert out["unsent"] == 1 and repo.link_get(aid, PLUGIN) == "personal"
    # Nothing queued: no round before the switch, and no count.
    fake.seen.clear()
    fake.hang = None
    out = Api().plugin_scope_set(PLUGIN, "spaceT")
    assert "unsent" not in out


def test_drop_clears_a_blocked_change_and_the_team_copy_comes_back(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    data = PluginData(PLUGIN)
    data.put("card.new", {"name": "Never sent"})
    data.put("card.old", {"name": "Edited"})
    repo.set_rev(aid, "spaceT", PLUGIN, "doc", "card.old", 7)
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.old", "refused", "Too big for the team's plan.")
    repo.sync_put(aid, "spaceT", cursor_rev=20)
    for _ in range(repo.BLOCK_AFTER):
        repo.note_attempt(aid, "spaceT", PLUGIN, "doc", "card.new", "Can't read it.")
    assert spaces.scope_status(PLUGIN)["blocked"] == 1
    api = Api()
    assert api.plugin_scope_drop(PLUGIN, "doc", "card.new") == {"ok": True, "dropped": 1}
    assert repo.get(aid, "spaceT", PLUGIN, "doc", "card.new") is None
    status = spaces.scope_status(PLUGIN)
    assert status["blocked"] == 0 and [item["key"] for item in status["items"]] == ["card.old"]
    assert repo.sync_get(aid, "spaceT")["cursor_rev"] == 20  # it was never on the server
    # An item the team has: dropped here, and the next pull starts back at its rev.
    assert api.plugin_scope_drop(PLUGIN, "doc", "card.old")["ok"] is True
    assert repo.sync_get(aid, "spaceT")["cursor_rev"] == 7
    assert api.plugin_scope_drop(PLUGIN, "doc", "card.old") == {"ok": False, "error": "That change was already sent or dropped."}
    assert {"type": "plugin_scope_changed", "plugins": [PLUGIN]} in api.pushed


def test_drop_removes_a_files_change_with_its_file(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    data = PluginData(PLUGIN)
    data.put_file("art/pip.png", b"PNG")
    repo.set_state(aid, "spaceT", PLUGIN, "asset", "art/pip.png", "refused", "Team storage is full.")
    path = scopes.asset_file(scopes.active_scope(PLUGIN), PLUGIN, "art/pip.png")
    assert path.is_file()
    assert Api().plugin_scope_drop(PLUGIN, "asset", "art/pip.png")["ok"] is True
    assert not path.is_file() and repo.get(aid, "spaceT", PLUGIN, "asset", "art/pip.png") is None


def test_drop_takes_only_the_change_held_back(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    data = PluginData(PLUGIN)
    data.put("card.a", {"name": "Queued"})
    api = Api()
    gone = {"ok": False, "error": "That change was already sent or dropped."}
    assert api.plugin_scope_drop(PLUGIN, "doc", "card.a") == gone  # queued, maybe being sent: stays
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.a", "blocked", "Can't read it.")
    held = repo.get(aid, "spaceT", PLUGIN, "doc", "card.a")
    data.put("card.a", {"name": "Edited since"})  # a newer edit lands after the bar read the row
    assert repo.drop_held(aid, "spaceT", PLUGIN, "doc", "card.a", expect=held) is False
    assert data.get("card.a") == {"name": "Edited since"}


def test_a_drops_rewind_holds_against_a_round_already_running(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    PluginData(PLUGIN).put("card.old", {"name": "Edited"})
    repo.set_rev(aid, "spaceT", PLUGIN, "doc", "card.old", 7)
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.old", "refused", "Too big.")
    repo.sync_put(aid, "spaceT", cursor_rev=20, called_at=time.time() - 60)  # a round started a minute ago
    assert Api().plugin_scope_drop(PLUGIN, "doc", "card.old")["ok"] is True
    assert repo.sync_get(aid, "spaceT")["cursor_rev"] == 7
    # That round ends and writes the cursor it reached: the rewind holds.
    repo.sync_put(aid, "spaceT", cursor_rev=30)
    assert repo.sync_get(aid, "spaceT")["cursor_rev"] == 7
    # A round that started after the drop pulled from 7: its cursor stands, and the hold ends.
    repo.sync_put(aid, "spaceT", called_at=time.time() + repo.REWIND_GRACE_S + 1)
    repo.sync_put(aid, "spaceT", cursor_rev=30)
    repo.sync_put(aid, "spaceT", cursor_rev=31)
    assert repo.sync_get(aid, "spaceT")["cursor_rev"] == 31


def test_retry_puts_refused_and_blocked_changes_back_in_the_queue(who, fake: Sending) -> None:
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    data = PluginData(PLUGIN)
    data.put("card.a", {"name": "A"})
    data.put("card.b", {"name": "B"})
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.a", "refused", "Too big for the team's plan.")
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.b", "blocked", "Can't read it.")
    assert repo.count_dirty(aid, "spaceT", PLUGIN) == 0
    api = Api()
    assert api.plugin_scope_retry(PLUGIN, "card.a") == {"ok": True, "retried": 1}
    assert repo.get(aid, "spaceT", PLUGIN, "doc", "card.a")["sync_state"] == ""
    assert api.plugin_scope_retry(PLUGIN) == {"ok": True, "retried": 1}
    assert repo.count_dirty(aid, "spaceT", PLUGIN) == 2
    assert api.plugin_scope_retry(PLUGIN, "card.a")["ok"] is False  # nothing waiting any more
    api.plugin_scope_set(PLUGIN, "personal")
    assert api.plugin_scope_retry(PLUGIN) == {"ok": False, "error": "This plugin's data isn't shared."}


def _reset_copy(fake: Sending, who) -> str:
    """Alpha holds this plugin's and forge's data, all sent once; then its data is reset on
    the server."""
    aid = open_space(fake, who, "ana@x.org", "spaceT", "Alpha")
    scopes.link_plugin("forge", "spaceT")
    data = PluginData(PLUGIN)
    data.put("card.a", {"name": "A"})
    data.put("card.b", {"name": "B"})
    data.put_file("art/a.png", b"PNG")
    PluginData("forge").put("scene.one", {"name": "One"})
    data.delete("card.b")
    for row in repo.dirty(aid, "spaceT", 100):
        repo.mark_pushed(aid, "spaceT", row["plugin_id"], row["kind"], row["key"], rev=5, sha256=row["sha256"],
                         pushed_delete=bool(row["deleted"]))
    data.put("card.c", {"name": "C"})
    repo.set_state(aid, "spaceT", PLUGIN, "doc", "card.c", "refused", "Team storage is full.")
    repo.sync_put(aid, "spaceT", state="reset", error="This team's data was reset on the server.", cursor_rev=40)
    return aid


def test_after_a_reset_retry_and_drop_wait_for_upload_or_clear(who, fake: Sending) -> None:
    aid = _reset_copy(fake, who)
    api = Api()
    first = {"ok": False, "error": panel_api_store.RESET_FIRST}
    assert api.plugin_scope_retry(PLUGIN) == first  # Retry all never uploads the whole copy
    assert api.plugin_scope_retry(PLUGIN, "card.c") == first
    assert api.plugin_scope_drop(PLUGIN, "doc", "card.c") == first
    assert api.plugin_scope_drop(PLUGIN, "", "") == first
    assert repo.get(aid, "spaceT", PLUGIN, "doc", "card.c")["sync_state"] == "refused"
    assert repo.get(aid, "spaceT", "forge", "doc", "scene.one")["dirty"] == 0
    assert repo.sync_get(aid, "spaceT")["state"] == "reset"
    status = spaces.scope_status(PLUGIN)
    assert status["state"] == "reset" and status["resetContents"] == [PLUGIN, "forge"]


def test_upload_my_copy_sends_the_whole_spaces_copy_again_as_new(who, fake: Sending) -> None:
    aid = _reset_copy(fake, who)
    data = PluginData(PLUGIN)
    with pytest.raises(scopes.ReadOnlyScope):
        data.put("card.d", {"name": "D"})
    api = Api()
    assert api.space_reset_settle("spaceT", "upload") == {"ok": True, "queued": 4}
    for plugin, kind, key in ((PLUGIN, "doc", "card.a"), (PLUGIN, "asset", "art/a.png"), (PLUGIN, "doc", "card.c"),
                              ("forge", "doc", "scene.one")):
        row = repo.get(aid, "spaceT", plugin, kind, key)
        assert (row["rev"], row["dirty"], row["sync_state"]) == (0, 1, "")
    assert repo.get(aid, "spaceT", PLUGIN, "doc", "card.b") is None  # nothing is left there to delete
    st = repo.sync_get(aid, "spaceT")
    assert (st["state"], st["error"], st["cursor_rev"]) == ("ok", "", 0)
    data.put("card.d", {"name": "D"})  # writable again
    assert api.space_reset_settle("spaceT", "upload") == {"ok": False, "error": "Alpha's data wasn't reset on the server."}
    assert {"type": "plugin_scope_changed", "plugins": [PLUGIN, "forge"]} in api.pushed


def test_clear_my_copy_clears_the_whole_spaces_copy_and_sends_nothing(who, fake: Sending) -> None:
    aid = _reset_copy(fake, who)
    folder = scopes.scopes_root(aid) / "spaceT"
    assert (folder / PLUGIN).is_dir()
    api = Api()
    assert api.space_reset_settle("spaceT", "clear") == {"ok": True, "cleared": 4}
    for plugin in (PLUGIN, "forge"):
        assert repo.rows(aid, "spaceT", plugin, "doc") == [] and repo.rows(aid, "spaceT", plugin, "asset") == []
    assert repo.count_dirty(aid, "spaceT") == 0 and not folder.exists()
    st = repo.sync_get(aid, "spaceT")
    assert (st["state"], st["cursor_rev"], st["label"]) == ("ok", 0, "Alpha")
    assert repo.links(aid) == {PLUGIN: "spaceT", "forge": "spaceT"}  # still linked: the team's data comes down
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(e.get("switched") for e in api.pushed):
        time.sleep(0.02)
    assert {"type": "plugin_scope_changed", "plugins": [PLUGIN, "forge"], "switched": True} in api.pushed
    assert api.space_reset_settle("spaceT", "throw away")["ok"] is False
