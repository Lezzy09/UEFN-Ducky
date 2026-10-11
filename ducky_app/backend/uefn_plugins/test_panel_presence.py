"""Agents are told when a plugin's panel is off screen (its panel code is paused)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.uefn_plugins import panel_presence as pp


@pytest.fixture
def docs(monkeypatch):
    store: dict[str, object] = {}
    fake = SimpleNamespace(
        get_doc=lambda table, key: store.get(key),
        set_doc=lambda table, key, value: store.__setitem__(key, value),
        delete_doc=lambda table, key: store.pop(key, None),
        list_docs=lambda table, prefix="": {k: v for k, v in store.items() if k.startswith(prefix)},
    )
    monkeypatch.setattr("backend.store.repos.kv", fake, raising=False)
    import backend.store.repos as repos

    monkeypatch.setattr(repos, "kv", fake, raising=False)
    monkeypatch.setattr(pp, "_has_panels", lambda pid: ["main"] if pid == "imk" else [])
    monkeypatch.setattr(pp, "_label", lambda pid: "Island Media Kit")
    pp._NOTED.clear()
    return store


def _as_agent(monkeypatch, chat: str) -> None:
    monkeypatch.setattr("backend.workspace.identity.resolve_context", lambda: SimpleNamespace(conv_id=chat))


def test_state_follows_the_window(docs) -> None:
    assert pp.panel_state("imk")["open"] is False
    pp.note_panel("main", "plugin:imk:main", visible=True)
    assert pp.panel_state("imk") | {"since": 0} == {"open": True, "visible": True, "since": 0, "panels": ["main"]}
    pp.note_panel("main", "plugin:imk:main", visible=False)
    assert pp.panel_state("imk")["visible"] is False and pp.panel_state("imk")["open"] is True
    pp.note_panel("main", "plugin:imk:main", visible=False, open_=False)
    assert pp.panel_state("imk")["open"] is False
    pp.note_panel("main", "plugin:imk:main", visible=True)
    pp.forget_all()
    assert pp.panel_state("imk")["open"] is False


def test_an_agent_is_told_once_while_the_panel_is_off_screen(docs, monkeypatch) -> None:
    _as_agent(monkeypatch, "lead")
    note = pp.panel_note_once("imk")
    assert "Island Media Kit panel is not open" in note
    assert 'ducky_ui_navigate("plugin_panel", "imk:main")' in note
    assert pp.panel_note_once("imk") == ""  # once per chat
    _as_agent(monkeypatch, "builder")
    assert pp.panel_note_once("imk") != ""  # another agent hears it too
    pp.note_panel("main", "plugin:imk:main", visible=True)
    assert pp.panel_note_once("imk") == ""  # on screen: nothing to say
    pp.note_panel("main", "plugin:imk:main", visible=False)
    assert "is open on a tab that is not showing" in pp.panel_note_once("imk")  # hidden again: said again


def test_no_note_for_people_or_plugins_without_panels(docs, monkeypatch) -> None:
    monkeypatch.setattr("backend.workspace.identity.resolve_context", lambda: None)
    assert pp.panel_note_once("imk") == ""
    _as_agent(monkeypatch, "lead")
    assert pp.panel_note_once("no-panels") == ""


def test_tool_results_carry_the_note(monkeypatch) -> None:
    from backend.uefn_plugins import host

    monkeypatch.setattr(pp, "panel_note_once", lambda pid: "The panel is off screen.")
    assert host._with_panel_note("imk", {"ok": True}) == {"ok": True, "panel_note": "The panel is off screen."}
    assert host._with_panel_note("imk", "done").endswith("\n\nThe panel is off screen.")
    monkeypatch.setattr(pp, "panel_note_once", lambda pid: "")
    assert host._with_panel_note("imk", {"ok": True}) == {"ok": True}


def test_agents_can_open_a_plugin_panel(monkeypatch) -> None:
    from backend.tools.panel import panel_ui

    calls = []
    monkeypatch.setattr(panel_ui, "panel_rpc", lambda method, params, **kw: calls.append((method, params)) or {"ok": True, "tab": "plugin:imk:main"})
    monkeypatch.setattr("backend.uefn_plugins.host.get_contributions",
                        lambda: {"ui_panels": [{"plugin_id": "imk", "id": "main", "title": "Island Media Kit"}]})
    assert panel_ui._navigate("plugin_panel", "imk") == {"ok": True, "route": "plugin_panel", "tab": "plugin:imk:main"}
    assert calls == [("open_plugin_panel", {"plugin_id": "imk", "panel_id": "main", "title": "Island Media Kit"})]
    assert "error" in panel_ui._navigate("plugin_panel", "nothing")
