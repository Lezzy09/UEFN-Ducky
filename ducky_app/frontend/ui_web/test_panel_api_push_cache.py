"""Every push tells call_pools which cached lists went stale."""

from frontend.ui_web import call_pools, panel_api


def test_pushes_call_on_push_once(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(call_pools, "on_push", seen.append)
    monkeypatch.setattr("frontend.ui_web.panel_httpd.publish_panel_events", lambda events: None)
    api = panel_api.PanelApi.__new__(panel_api.PanelApi)  # no __init__: no plugins or models
    api._all_windows = lambda: []

    api._push({"type": "chats_changed", "conv_id": "c1"})
    assert seen == ["chats_changed"]

    api._push_panel({"type": "uefn_plugins_changed"})
    assert seen == ["chats_changed", "uefn_plugins_changed"]
