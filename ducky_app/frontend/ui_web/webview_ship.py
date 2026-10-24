"""Store EXE WebView2 ship policy — no native right-click menu."""

from __future__ import annotations

from typing import Any

from frontend.bundle_root import is_packaged_runtime


def hides_native_menu() -> bool:
    """The Store EXE shows no WebView2 Inspect/Back/Reload menu; dev runs keep it."""
    if not is_packaged_runtime():
        return False
    from frontend.ui_web.web_dev import is_dev_panel

    return not is_dev_panel()


def apply_shipped_webview2_settings(settings: Any) -> None:
    """Hide WebView2's Inspect/Back/Reload menu in the Store EXE.

    The fallback when the native-menu hook (``webview_native_menu``, which keeps the
    spell checker's suggestions on text you type in) can't attach. Custom React
    ``ContextMenu`` still works (JS ``contextmenu``). ``open_devtools`` turns it back on.
    """
    if settings is None or not hides_native_menu():
        return
    settings.AreDefaultContextMenusEnabled = False
