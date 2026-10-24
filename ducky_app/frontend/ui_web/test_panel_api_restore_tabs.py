"""After a WebView2 crash reload the window gets its last reported tabs back, once."""

from frontend.ui_web import panel_api


def test_restore_tabs_once_after_crash_reload() -> None:
    api = panel_api.PanelApi.__new__(panel_api.PanelApi)  # no __init__: no plugins or models
    tabs = ["chat:450a3ccd", "chat:80fcc09e"]
    api.report_open_tabs("main", tabs)
    assert api.get_restore_tabs("main") == []  # normal load: nothing to restore

    panel_api.mark_crash_reload()
    api.report_open_tabs("main", [])  # the reloaded page reports before it asks
    assert api.get_restore_tabs("main") == tabs
    assert api.get_restore_tabs("main") == []
