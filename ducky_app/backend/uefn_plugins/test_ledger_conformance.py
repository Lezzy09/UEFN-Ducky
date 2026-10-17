"""The ledger conformance suite against FakeLedger, the in-memory model of the server
rules (a provider's backend runs the same checks with its own world)."""

from __future__ import annotations

from typing import Callable

import pytest

from backend.uefn_plugins import ledger, ledger_conformance as conf


@pytest.fixture
def world():
    w = conf.FakeWorld()
    yield w
    w.server.rmtree()


@pytest.mark.parametrize("check", conf.CHECKS, ids=lambda c: c.__name__)
def test_fake_ledger_passes(check: Callable[[conf.World], None], world: conf.FakeWorld) -> None:
    check(world)


def test_fake_ledger_is_a_ledger_backend(world: conf.FakeWorld) -> None:
    assert isinstance(world.client("ana"), ledger.LedgerBackend)
    assert world.client("ana").capabilities() == set(ledger.CAPABILITIES)


def test_every_call_answers_offline_instead_of_raising(world: conf.FakeWorld) -> None:
    a = world.client("ana")
    world.server.offline = True
    cs = conf.changeset(conf.put_item("doc", "k", b"1"))
    assert isinstance(a.push(conf.SPACE, conf.PLUGIN, cs), ledger.Offline)
    assert isinstance(a.pull(conf.SPACE, conf.PLUGIN, 0, 50), ledger.Offline)
    assert isinstance(a.heads(conf.SPACE, [conf.PLUGIN]), ledger.Offline)
    assert isinstance(a.fetch(conf.SPACE, conf.PLUGIN, "doc", "k"), ledger.Offline)
    assert isinstance(a.lock(conf.SPACE, conf.PLUGIN, [ledger.LockUnit("doc:k")], "best", {}), ledger.Offline)
    assert isinstance(a.beat(conf.SPACE, {}), ledger.Offline)
    assert ledger.failed(a.push(conf.SPACE, conf.PLUGIN, cs))


def test_a_reader_that_fails_is_an_error_answer_not_an_exception(world: conf.FakeWorld) -> None:
    def boom() -> bytes:
        raise OSError("file is gone")

    item = ledger.OutgoingItem("asset", "a.png", "asset:a.png", "put", reader=boom)
    out = world.client("ana").push(conf.SPACE, conf.PLUGIN, conf.changeset(item))
    assert isinstance(out, ledger.Error) and "file is gone" in out.reason


def test_workflows_from_a_member_without_rights_are_refused(world: conf.FakeWorld) -> None:
    world.server.no_workflow_rights.add("ben")
    out = world.client("ben").push(conf.SPACE, conf.WORKFLOWS, conf.changeset(conf.put_item("doc", "wf1", b"{}")))
    assert isinstance(out, ledger.Refused) and out.items[0].reason == conf.NO_WORKFLOW_RIGHTS
