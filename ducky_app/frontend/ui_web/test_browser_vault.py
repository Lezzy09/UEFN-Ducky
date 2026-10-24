"""Saved Browser logins: Chromium's cookie key is only on disk while Ducky runs."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI / Windows Hello are Windows-only")

KEY = bytes(range(32))


class FakeHello:
    """Stands in for the Windows Hello key: reversible, and counts the unlocks it was asked for."""

    def __init__(self, fail: bool = False) -> None:
        self.fail, self.asked, self.created = fail, 0, 0

    def encrypt(self, data: bytes) -> bytes:
        if self.fail:
            raise OSError("Locking with Windows Hello failed (0x80090030)")
        return b"HELLO" + data[::-1]

    def decrypt(self, data: bytes, hwnd: int = 0) -> bytes:
        self.asked += 1
        if self.fail:
            raise OSError("Unlocking with Windows Hello failed (0x800704C7)")
        return data[5:][::-1]

    def create(self, hwnd: int = 0) -> None:
        self.created += 1


@pytest.fixture
def profile(tmp_path, monkeypatch):
    from frontend.ui_web import browser_vault as vault

    monkeypatch.setattr(vault, "profile_dir", lambda mode: tmp_path / mode)
    monkeypatch.setattr(vault, "start_watcher", lambda: None)
    (tmp_path / "saved" / "EBWebView" / "Default" / "Network").mkdir(parents=True)
    return tmp_path / "saved"


def _write_key(profile: Path) -> None:
    from backend.agent.secrets import protect_plain

    sealed = base64.b64encode(b"DPAPI" + protect_plain(KEY)).decode()
    state = {"os_crypt": {"encrypted_key": sealed, "audit_enabled": True}, "browser": {"x": 1}}
    (profile / "EBWebView" / "Local State").write_text(json.dumps(state), encoding="utf-8")


def _state(profile: Path) -> dict:
    return json.loads((profile / "EBWebView" / "Local State").read_text(encoding="utf-8"))


def test_lock_then_unlock_round_trips_the_cookie_key(profile) -> None:
    from backend.agent.secrets import unprotect_plain
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    hello = FakeHello()
    assert vault.lock(hello) == ""
    state = _state(profile)
    assert "encrypted_key" not in state["os_crypt"]  # nothing on disk an infostealer can open
    assert state["os_crypt"]["audit_enabled"] is True and state["browser"] == {"x": 1}
    assert KEY not in (profile / "logins.hello").read_bytes()

    assert vault.unlock(0, hello) == ""
    assert hello.asked == 1
    blob = base64.b64decode(_state(profile)["os_crypt"]["encrypted_key"])
    assert blob[:5] == b"DPAPI" and unprotect_plain(blob[5:]) == KEY


def test_first_unlock_only_makes_the_hello_key(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    hello = FakeHello()
    assert vault.unlock(0, hello) == ""
    assert hello.created == 1 and hello.asked == 0
    assert "encrypted_key" in _state(profile)["os_crypt"]  # the watcher locks it when Ducky exits


def test_a_key_that_cannot_be_sealed_is_never_dropped(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    assert "not locked" in vault.lock(FakeHello(fail=True))
    assert "encrypted_key" in _state(profile)["os_crypt"]
    assert not (profile / "logins.hello").exists()


def test_no_lock_while_the_browser_holds_the_profile(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    with open(profile / "EBWebView" / "lockfile", "w"):
        assert vault.browser_running(profile)
        assert vault.lock(FakeHello()) == "the browser still has the profile open"
    assert "encrypted_key" in _state(profile)["os_crypt"]
    assert not vault.browser_running(profile)  # a stale lockfile from a crash doesn't count


def test_refused_hello_keeps_the_logins_locked(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    assert vault.lock(FakeHello()) == ""
    why = vault.unlock(0, FakeHello(fail=True))
    assert "Windows Hello" in why
    assert "encrypted_key" not in _state(profile)["os_crypt"]
    assert (profile / "logins.hello").is_file()


def test_memory_mode_deletes_logins_left_unlocked(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    cookies = profile / "EBWebView" / "Default" / "Network" / "Cookies"
    cookies.write_bytes(b"sqlite")
    vault.forget_unlocked_logins()
    assert not cookies.exists() and "encrypted_key" not in _state(profile)["os_crypt"]


def test_memory_mode_leaves_hello_locked_logins_alone(profile) -> None:
    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    assert vault.lock(FakeHello()) == ""
    cookies = profile / "EBWebView" / "Default" / "Network" / "Cookies"
    cookies.write_bytes(b"sqlite")
    vault.forget_unlocked_logins()
    assert cookies.exists()  # still sealed: turning keepLogins back on gets them back


def test_watcher_locks_once_ducky_has_exited(profile, monkeypatch) -> None:
    import subprocess

    from frontend.ui_web import browser_vault as vault

    _write_key(profile)
    monkeypatch.setattr(vault, "_Hello", FakeHello)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert vault.relock_after(gone.pid, wait_s=1.0) == 0
    assert "encrypted_key" not in _state(profile)["os_crypt"]


def test_profile_mode_defaults_to_memory_and_falls_back_when_hello_refuses(monkeypatch) -> None:
    from frontend.ui_web import browser_overlay as bo
    from frontend.ui_web import browser_vault as vault

    forgot: list[bool] = []
    monkeypatch.setattr(vault, "forget_unlocked_logins", lambda: forgot.append(True))
    monkeypatch.setattr(vault, "keep_logins", lambda: False)
    monkeypatch.setattr(bo, "_mode", "")
    assert bo.profile_mode() == "memory" and forgot == [True]

    monkeypatch.setattr(vault, "keep_logins", lambda: True)
    monkeypatch.setattr(vault, "unlock", lambda hwnd=0: "Unlocking with Windows Hello failed")
    monkeypatch.setattr(bo, "_mode", "")
    assert bo.profile_mode() == "memory" and "stayed locked" in bo._mode_note

    monkeypatch.setattr(vault, "unlock", lambda hwnd=0: "")
    monkeypatch.setattr(bo, "_mode", "")
    assert bo.profile_mode() == "saved"
    monkeypatch.setattr(bo, "_mode", "")


def test_hello_key_store_is_reachable_on_this_pc() -> None:
    """No prompt: only opens the Windows Hello key store (skips on a PC without Hello)."""
    from frontend.ui_web import browser_vault as vault

    if not vault.hello_available():
        pytest.skip("Windows Hello isn't set up on this PC")
    assert vault._Hello().name.endswith("//UEFN-Ducky/Browser/Logins")
