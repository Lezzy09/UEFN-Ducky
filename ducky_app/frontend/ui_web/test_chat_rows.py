"""chat_rows owns the row conversion; panel_api re-exports it for mixins."""

from frontend.ui_web import chat_rows, panel_api


def test_panel_api_reexports_chat_rows() -> None:
    assert panel_api._messages_to_ui is chat_rows._messages_to_ui
    assert panel_api._tool_result_text is chat_rows._tool_result_text
