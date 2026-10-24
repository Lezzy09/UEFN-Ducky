"""/__panel_rpc steer_take / steer_ack / steer_pending (panel_httpd._steer_rpc)."""

from __future__ import annotations

import pytest

from frontend.ui_web import agent_modes, steer
from frontend.ui_web import panel_httpd as httpd


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setattr(agent_modes, "is_agent_running", lambda _cid: True)
    pushed: list[dict] = []
    steer.bind_run("c1", pushed.append)
    yield pushed
    steer.end_run("c1")


def test_take_leases_and_pushes_nothing(chat):
    assert httpd._steer_rpc("steer_pending", {"conv_id": "c1"}) == {"result": {"pending": False}}
    steer.post("c1", "s1", "also fix the tests")
    assert httpd._steer_rpc("steer_pending", {"conv_id": "c1"}) == {"result": {"pending": True}}
    lease = httpd._steer_rpc("steer_take", {"conv_id": "c1"})["result"]
    assert lease["lease_id"] and lease["texts"] == ["also fix the tests"] and lease["steer_ids"] == ["s1"]
    assert chat == []
    assert httpd._steer_rpc("steer_pending", {"conv_id": "c1"}) == {"result": {"pending": False}}


def test_ack_pushes_once(chat):
    steer.post("c1", "s1", "stop after this file")
    lease_id = httpd._steer_rpc("steer_take", {"conv_id": "c1"})["result"]["lease_id"]
    assert httpd._steer_rpc("steer_ack", {"conv_id": "c1", "lease_id": lease_id}) == {"ok": True, "result": {"ok": True}}
    httpd._steer_rpc("steer_ack", {"conv_id": "c1", "lease_id": lease_id})
    assert [e["type"] for e in chat] == ["user_steered"]
    assert chat[0]["steer_id"] == "s1"


def test_positional_args_name_the_params():
    assert dict(zip(httpd._STEER_ARGS["steer_ack"], ["450a3ccd", "7f3c"])) == {"conv_id": "450a3ccd", "lease_id": "7f3c"}
