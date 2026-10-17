"""Shared folders on one PC: whole folder trees copied or moved to and from a shared
space keep their nesting and working Run workflow steps, a failed move leaves the
source intact, and a space's folder list keeps empty folders and renames."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")

from backend.automations import bundles, owned, shared, store, test_workflow_owners
from backend.automations.test_workflow_owners import CRON, join
from backend.store.repos import plugin_data as repo
from backend.uefn_plugins import test_scopes
from backend.uefn_plugins.test_scopes import _Who

account_keys = test_scopes.account_keys
who = test_scopes.who
fake = test_workflow_owners.fake
quiet = test_workflow_owners.quiet


@pytest.fixture(autouse=True)
def plain_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundles, "workflow_fields", lambda: {"workflow.call": ("workflow_id",)})


def call(node_id: str, target: str) -> dict:
    return {"id": node_id, "type": "workflow.call", "x": 0, "y": 0, "config": {"workflow_id": target}}


def tree() -> dict[str, dict]:
    """Local "Kit": Main → Lib/Helper, plus an empty Kit/Lib/Later."""
    helper = store.save_workflow({"name": "Helper", "folder": "Kit/Lib", "graph": CRON})
    main = store.save_workflow({"name": "Main", "folder": "Kit", "graph": {"nodes": [call("n", helper["id"])], "edges": []}})
    store.add_folder("local", "Kit/Lib/Later")
    return {"main": main, "helper": helper}


def space_folders() -> list[str]:
    return next(o["folders"] for o in shared.owners()["owners"] if o["id"] == "spaceT")


def by_name(owner: str) -> dict[str, dict]:
    return {wf["name"]: store.get_workflow(wf["id"]) for wf in store.list_workflows() if wf["owner"]["id"] == owner}


def test_copy_folder_to_a_space_keeps_tree_and_calls(who: _Who, fake) -> None:
    join(fake, who, "ana@x.org")
    made = tree()
    out = bundles.copy_folder("local", "Kit", "spaceT", "Shared")
    assert out["folder"] == "Shared/Kit" and out["moved"] == 0
    copies = by_name("spaceT")
    assert copies["Main"]["folder"] == "Shared/Kit" and copies["Helper"]["folder"] == "Shared/Kit/Lib"
    assert copies["Main"]["graph"]["nodes"][0]["config"]["workflow_id"] == copies["Helper"]["id"]
    assert copies["Helper"]["run_here"] is True
    assert space_folders() == ["Shared", "Shared/Kit", "Shared/Kit/Lib", "Shared/Kit/Lib/Later"]
    assert store.get_workflow(made["main"]["id"])["owner"]["id"] == "local"  # a copy leaves the source


def test_move_folder_to_a_space_and_back_keeps_ids_tree_and_calls(who: _Who, fake) -> None:
    join(fake, who, "ana@x.org")
    made = tree()
    out = bundles.copy_folder("local", "Kit", "spaceT", "", move=True)
    assert out["moved"] == 2 and out["folder"] == "Kit"
    main = store.get_workflow(made["main"]["id"])
    assert main["owner"]["id"] == "spaceT" and main["folder"] == "Kit"
    assert main["graph"]["nodes"][0]["config"]["workflow_id"] == made["helper"]["id"]
    assert store.get_workflow(made["helper"]["id"])["folder"] == "Kit/Lib"
    assert [w for w in store.list_workflows() if w["owner"]["id"] == "local"] == []
    assert "Kit" not in store.folders_of("local")
    assert "Kit/Lib/Later" in space_folders()

    back = bundles.copy_folder("spaceT", "Kit", "local", "Home", move=True)
    assert back["folder"] == "Home/Kit"
    assert store.get_workflow(made["helper"]["id"])["owner"]["id"] == "local"
    assert store.get_workflow(made["helper"]["id"])["folder"] == "Home/Kit/Lib"
    assert "Home/Kit/Lib/Later" in store.folders_of("local") and "Kit" not in space_folders()


def test_a_failed_move_leaves_the_source_intact(who: _Who, fake, monkeypatch) -> None:
    join(fake, who, "ana@x.org")
    made = tree()
    real = owned.write
    writes: list[str] = []

    def flaky(scope, doc, **kw):
        if scope["kind"] == "shared" and writes:
            raise ValueError("This workflow is over 1 MB. Split it into smaller workflows.")
        if scope["kind"] == "shared":
            writes.append(str(doc["id"]))
        return real(scope, doc, **kw)

    monkeypatch.setattr(owned, "write", flaky)
    with pytest.raises(ValueError, match="1 MB"):
        bundles.copy_folder("local", "Kit", "spaceT", "", move=True)
    monkeypatch.setattr(owned, "write", real)
    for wf in made.values():
        kept = store.get_workflow(wf["id"])
        assert kept["owner"]["id"] == "local" and kept["folder"] == wf["folder"]
    assert [w for w in store.list_workflows() if w["owner"]["id"] == "spaceT"] == []
    assert "Kit/Lib/Later" in store.folders_of("local")
    assert space_folders() == []


def test_custom_code_and_read_only_spaces_are_refused_before_anything_moves(who: _Who, fake) -> None:
    from backend.store.repos import workflows as runtime

    aid = join(fake, who, "ana@x.org")
    code = store.save_workflow({"name": "Coded", "folder": "Code", "graph": {"nodes": [
        {"id": "c", "type": "code.js", "x": 0, "y": 0, "config": {"code": "export default () => ({});"}}], "edges": []}})
    with pytest.raises(ValueError):
        bundles.copy_folder("local", "Code", "spaceT", move=True)
    assert store.get_workflow(code["id"])["owner"]["id"] == "local"
    tree()
    runtime.meta_put(aid, "spaceT", workflows_writable=False)
    with pytest.raises(PermissionError):
        bundles.copy_folder("local", "Kit", "spaceT")
    with pytest.raises(PermissionError):
        store.add_folder("spaceT", "Nope")
    assert [w for w in store.list_workflows() if w["owner"]["id"] == "spaceT"] == []
    # Reading a space you can't change still works: copy its folder to Local.
    runtime.meta_put(aid, "spaceT", workflows_writable=True)
    bundles.copy_folder("local", "Kit", "spaceT")
    runtime.meta_put(aid, "spaceT", workflows_writable=False)
    assert bundles.copy_folder("spaceT", "Kit", "local", "From space")["folder"] == "From space/Kit"


def test_empty_folders_and_renames_are_kept_and_queued(who: _Who, fake) -> None:
    ana = join(fake, who, "ana@x.org")
    store.add_folder("spaceT", "Plans/Later")
    wf = store.save_workflow({"name": "Nightly", "folder": "Plans", "graph": CRON}, owner="spaceT")
    assert repo.count_dirty(ana, "spaceT") >= 2  # the folder list goes up with the workflow
    assert space_folders() == ["Plans", "Plans/Later"]
    store.move_folder("spaceT", "Plans", "Ideas")
    store.add_folder("spaceT", "Ideas/Empty")
    assert space_folders() == ["Ideas", "Ideas/Empty", "Ideas/Later"]
    assert store.get_workflow(wf["id"])["folder"] == "Ideas"
    assert [w["name"] for w in store.list_workflows()] == ["Nightly"]  # the folder list is never a workflow


def test_signed_out_empty_folders_come_along_into_the_account(who: _Who) -> None:
    who.be("")
    store.add_folder("local", "Offline/Empty")
    store.save_workflow({"name": "Offline flow", "folder": "Offline", "graph": CRON})
    ana = who.be("ana@x.org")
    assert owned.local_import_count(ana) == 1
    assert shared.import_local()["moved"] == 1
    assert store.folders_of("local") == ["Offline", "Offline/Empty"]
