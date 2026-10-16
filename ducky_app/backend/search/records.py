"""``api.search``: a plugin makes its own records searchable by meaning and keywords.

Records live in the same index as skills and tools (``kind = 'record'``), keyed by
plugin and data scope, so a plugin sees only its own rows in the copy it is using
(Local or one team) and they are deleted when the plugin is uninstalled. Agents do
not see records through ``skill_search``; the plugin exposes its own tool that
calls :func:`query`.
"""

from __future__ import annotations

import re
from typing import Any

from backend.search import chunker
from backend.store.repos import search as repo

MAX_RECORDS = 10_000
MAX_TEXT = 20_000
MAX_TITLE = 300
_RECORD_ID = re.compile(r"^[^\s:][^:]{0,199}$")


def _scope(plugin_id: str) -> str:
    try:
        from backend.uefn_plugins.scopes import active_scope

        return str(active_scope(plugin_id).get("id") or "personal")
    except Exception:  # noqa: BLE001
        return "personal"


def _source(plugin_id: str, scope: str) -> str:
    return f"record:{plugin_id}:{scope}"


def upsert(plugin_id: str, record_id: str, title: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    rid = str(record_id or "").strip()
    if not _RECORD_ID.match(rid):
        raise ValueError("record_id: 1-200 characters, no ':' and no leading space")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("meta must be a dict")
    scope = _scope(plugin_id)
    doc = chunker.record_doc(
        plugin_id, scope, rid, str(title or rid)[:MAX_TITLE], str(text or "")[:MAX_TEXT], dict(meta or {})
    )
    source = _source(plugin_id, scope)
    if repo.count_source(source) >= MAX_RECORDS and not repo.find_doc(doc.doc_key):
        raise ValueError(f"search holds at most {MAX_RECORDS} records per plugin; delete some first")
    vec = None
    model = ""
    from backend.search.embedder import get_embedder

    emb = get_embedder()
    if emb is not None:
        vec = emb.encode([chunker.embed_text(doc)])[0].tobytes()
        model = emb.model_id
    repo.upsert_one(doc, vec, model)
    return {"ok": True, "id": rid, "scope": scope}


def delete(plugin_id: str, record_id: str) -> bool:
    scope = _scope(plugin_id)
    return repo.delete_docs([f"record:{plugin_id}:{scope}:{str(record_id or '').strip()}"]) > 0


def clear(plugin_id: str) -> int:
    return repo.drop_source(_source(plugin_id, _scope(plugin_id)))


def query(plugin_id: str, text: str, limit: int = 10) -> list[dict[str, Any]]:
    from backend.search.query import Context, search

    ctx = Context(record_plugin=plugin_id, record_scope=_scope(plugin_id))
    rows = search(text, kinds=("record",), limit=max(1, min(int(limit or 10), 50)), context=ctx, refresh=False)
    for row in rows:
        row.pop("read", None)
    return rows


class SearchApi:
    """``api.search`` for one plugin. Every call is limited to this plugin's records in its
    active data scope (Local or the one team the plugin's data lives in)."""

    def __init__(self, plugin_id: str) -> None:
        self._plugin = plugin_id

    def upsert(self, record_id: str, title: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add or replace one record. Split long documents into one record per section:
        the meaning model reads the first ~500 words of each record, keywords read it all."""
        return upsert(self._plugin, record_id, title, text, meta)

    def delete(self, record_id: str) -> bool:
        return delete(self._plugin, record_id)

    def clear(self) -> int:
        """Delete every record of this plugin in its active scope."""
        return clear(self._plugin)

    def query(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        """Best matches first: ``[{id, title, snippet, score, meta, match}]``."""
        return query(self._plugin, text, limit)
