"""ducky_sync_project_to_uefn: the live UEFN name is the island's content mount (its
root plugin, which UEFN makes a GUID for some islands), never only the folder name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontend import project_kind as pk

GUID = "86ef2167-1111-2222-3333-444444444444"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for key in ("UEFN_VSCODE_WORKSPACE_FOLDERS", "UEFN_DUCKY_PROJECT_ROOT"):
        monkeypatch.delenv(key, raising=False)
    pk.forget_cached_kind()
    pk.forget_cached_identity()
    # Switching islands in these tests must not deploy the listener anywhere.
    monkeypatch.setattr("frontend.ui_web.project_switch._deploy_project_once", lambda *a, **k: None)
    yield
    pk.forget_cached_kind()
    pk.forget_cached_identity()


def _island(tmp_path: Path, name: str, plugin: str) -> Path:
    root = tmp_path / name
    (root / "Content" / "Verse").mkdir(parents=True)
    manifest = {"title": name, "plugins": [{"name": plugin, "bIsRoot": True, "bIsPublic": False}]}
    (root / f"{name}.uefnproject").write_text(json.dumps(manifest), encoding="utf-8")
    (root / f"{plugin}.uplugin").write_text("{}", encoding="utf-8")
    return root


def _live(monkeypatch, name: str, island_dir: str = "") -> None:
    monkeypatch.setattr(
        "backend.bridge.post_command_to_listener",
        lambda _port, _cmd, _args, timeout=5.0: {
            "project_name": name,
            "content_root": f"/{name}/",
            "project_dir": "../../../FortniteGame/",
            "island_dir": island_dir,
        },
    )


def _sync() -> dict:
    from backend.tools.panel.ducky_panel import ducky_sync_project_to_uefn

    return json.loads(ducky_sync_project_to_uefn(pretty=False))


def test_selected_island_with_guid_mount_is_already_synced(tmp_path, monkeypatch):
    from frontend.ui_web import project_switch

    island = _island(tmp_path, "MyProjectBJJJ", GUID)
    project_switch.set_panel_project_root(str(island), push_ui=False)
    _live(monkeypatch, GUID)
    out = _sync()
    assert out["status"] == "already_synced"
    assert out["uefn_project"] == GUID
    assert out["project"]["name"] == "MyProjectBJJJ"
    assert out["project"]["mount"] == GUID


def test_switches_to_the_recent_island_that_declares_the_mount(tmp_path, monkeypatch):
    from frontend.ui_web import project_switch

    guid_island = _island(tmp_path, "MyProjectBJJJ", GUID)
    other = _island(tmp_path, "Tycoony", "Tycoony")
    project_switch.set_panel_project_root(str(guid_island), push_ui=False)
    project_switch.set_panel_project_root(str(other), push_ui=False)
    _live(monkeypatch, GUID)
    out = _sync()
    assert out["status"] == "switched"
    assert out["project"]["path"] == str(guid_island.resolve())


def test_island_dir_from_the_listener_wins_over_names(tmp_path, monkeypatch):
    from frontend.ui_web import project_switch

    island = _island(tmp_path, "MyProjectBJJJ", GUID)
    project_switch.set_panel_project_root(str(island), push_ui=False)
    _live(monkeypatch, "whatever-the-editor-calls-it", island_dir=str(island))
    assert _sync()["status"] == "already_synced"


def test_unknown_mount_is_a_terminal_error_that_names_both_sides(tmp_path, monkeypatch):
    from frontend.ui_web import project_switch

    island = _island(tmp_path, "MyProjectBJJJ", GUID)
    project_switch.set_panel_project_root(str(island), push_ui=False)
    _live(monkeypatch, "aaaaaaaa-0000-0000-0000-000000000000")
    with pytest.raises(ValueError) as exc:
        _sync()
    text = str(exc.value)
    assert "aaaaaaaa-0000-0000-0000-000000000000" in text
    assert f"MyProjectBJJJ (mount {GUID})" in text
    assert "ducky_ask_user" in text
    assert "retry" not in text.lower()


def test_reserved_mount_means_no_island_open(tmp_path, monkeypatch):
    from frontend.ui_web import project_switch

    island = _island(tmp_path, "MyProjectBJJJ", GUID)
    project_switch.set_panel_project_root(str(island), push_ui=False)
    _live(monkeypatch, "Temp")
    with pytest.raises(ValueError, match="island map open"):
        _sync()


def test_project_root_arg_resolves_a_mount(tmp_path, monkeypatch):
    from backend.tools.panel.ducky_panel import _resolve_project_root_arg
    from frontend.ui_web import project_switch

    island = _island(tmp_path, "MyProjectBJJJ", GUID)
    project_switch.set_panel_project_root(str(island), push_ui=False)
    assert _resolve_project_root_arg(GUID) == str(island.resolve())
    with pytest.raises(ValueError, match="Unknown project"):
        _resolve_project_root_arg("nope-0000")
