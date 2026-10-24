"""D20: steer and question checks go to the chat's agent host when it has one, not the app."""
import json
import statistics
import threading
import time
from multiprocessing.connection import Listener

import pytest

from backend.panel import rpc
from backend.workspace import identity

KEY = b"host-secret"


@pytest.fixture
def host():
    """A fake agent host serving the tool-server contract on its own pipe."""
    listener = Listener(authkey=KEY)
    seen: list[tuple[str, dict]] = []

    def serve():
        while True:
            try:
                conn = listener.accept()
            except OSError:
                return
            with conn:
                request = json.loads(conn.recv_bytes())
                seen.append((request["method"], request["params"]))
                answer = {"steer_take": {"lease_id": "L1", "texts": ["use blue"]},
                          "steer_ack": {"ok": True},
                          "question_gate": {"blocked": False}}[request["method"]]
                conn.send_bytes(json.dumps(answer).encode())

    threading.Thread(target=serve, daemon=True).start()
    yield listener.address, seen
    listener.close()


def _bound(extra):
    return identity.bind(identity.RunContext(run_id="r", conv_id="c1", extra=extra))


def test_host_answers_steer_and_questions_while_the_app_is_blocked(host, monkeypatch):
    address, seen = host

    def app_blocked(*args, **kwargs):
        raise AssertionError("the jammed app was asked")

    monkeypatch.setattr(rpc, "panel_rpc", app_blocked)
    token = _bound({"host_pipe": address, "host_key": KEY.hex()})
    try:
        assert rpc.take_steer_messages("c1") == ("L1", ["use blue"])
        rpc.ack_steer("c1", "L1")
        rpc.wait_for_question_answers("c1")
        assert [m for m, _ in seen] == ["steer_take", "steer_ack", "question_gate"]
        assert seen[1][1] == {"conv_id": "c1", "lease_id": "L1"}
        times = []
        for _ in range(20):
            started = time.perf_counter()
            rpc.take_steer_messages("c1")
            times.append(time.perf_counter() - started)
        assert statistics.median(times) < 0.005, f"median {statistics.median(times) * 1000:.1f} ms"
    finally:
        identity.reset(token)


def test_without_a_host_the_app_answers(monkeypatch):
    monkeypatch.delenv(rpc.HOST_PIPE_ENV, raising=False)
    calls = []
    monkeypatch.setattr(rpc, "panel_rpc", lambda method, params=None, **kw: calls.append(method) or {"texts": []})
    token = _bound({})
    try:
        assert rpc.take_steer_messages("c1") == ("", [])
    finally:
        identity.reset(token)
    assert calls == ["steer_take"]


def test_a_dead_host_falls_back_to_the_app(monkeypatch):
    calls = []
    monkeypatch.setattr(rpc, "panel_rpc", lambda method, params=None, **kw: calls.append(method) or {"texts": ["x"]})
    token = _bound({"host_pipe": r"\\.\pipe\uefn-ducky-host-gone-0", "host_key": KEY.hex()})
    try:
        assert rpc.take_steer_messages("c1") == ("", ["x"])
    finally:
        identity.reset(token)
    assert calls == ["steer_take"]


def test_hello_identity_carries_the_host_pipe(monkeypatch):
    from backend.bridge import shared_mcp
    from frontend import shared_mcp_adapter as adapter

    monkeypatch.setenv("DUCKY_AGENT_HOST_PIPE", r"\\.\pipe\uefn-ducky-host-1-2")
    monkeypatch.setenv("DUCKY_AGENT_HOST_KEY", "abcd")
    sent = adapter._identity()
    assert sent["host_pipe"] == r"\\.\pipe\uefn-ducky-host-1-2" and sent["host_key"] == "abcd"
    ctx = shared_mcp.identity_from_payload(sent)
    assert ctx.extra["host_pipe"] == r"\\.\pipe\uefn-ducky-host-1-2" and ctx.extra["host_key"] == "abcd"
