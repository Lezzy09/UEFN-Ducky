"""ducky_get_tools(pattern=) ranks through the search index, then the old all-words matches."""

from __future__ import annotations

from types import SimpleNamespace

from backend.tools.panel import ducky_panel


def _tools(*names: str) -> list:
    return [SimpleNamespace(name=n, description=f"{n.replace('_', ' ')} tool", inputSchema={"type": "object"})
            for n in names]


def test_index_hits_lead_then_word_matches(monkeypatch) -> None:
    from backend.search import query

    tools = _tools("save_current_level", "save_all_dirty", "photoshop_save_document")
    by_name = {t.name: t for t in tools}
    monkeypatch.setattr(query, "search_tools", lambda text, allowed, limit=20: [{"tool": "save_current_level"}])
    names = ducky_panel._ranked_tool_names(tools, by_name, "save", 10)
    assert names[0] == "save_current_level"
    assert set(names) == {"save_current_level", "save_all_dirty", "photoshop_save_document"}


def test_index_failure_keeps_the_old_search(monkeypatch) -> None:
    from backend.search import query

    def boom(*a, **k):
        raise RuntimeError("index unavailable")

    tools = _tools("save_current_level", "spawn_actor")
    monkeypatch.setattr(query, "search_tools", boom)
    assert ducky_panel._ranked_tool_names(tools, {t.name: t for t in tools}, "save level", 10) == ["save_current_level"]


def test_a_new_catalog_revision_requests_a_tool_reindex(monkeypatch) -> None:
    from backend.search import indexer

    calls: list[str] = []
    monkeypatch.setattr(indexer, "request_refresh", lambda reason="": calls.append(reason))
    monkeypatch.setattr(ducky_panel, "_seen_catalog_revision", "")
    ducky_panel._note_catalog_revision("r1")  # first sight in this process: nothing changed yet
    ducky_panel._note_catalog_revision("r1")
    ducky_panel._note_catalog_revision("r2")
    assert calls == ["tools"]
