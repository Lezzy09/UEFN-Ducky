"""``api.search``: a plugin makes its own records searchable by meaning and keywords.

Records live in the same index as skills and tools (``kind = 'record'``), keyed by
plugin, signed-in account and data scope, so a plugin sees only its own rows in the
copy it is using (Local or one team) for the person signed in. They are deleted when
the plugin is uninstalled (and refused from then on), when a team copy is purged and
when a plugin-test sandbox ends. Agents do not see records through ``skill_search``;
the plugin exposes its own tool that calls :func:`query`.
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


def _scope(plugin_id: str) -> tuple[str, str]:
    """(storage key ``<account>~<scope id>``, the scope id the plugin sees).

    Every account's Local scope is "personal", so the account is part of the key: on a
    PC shared by two people, one never reads or clears the other's records. Raises when
    the scope cannot be resolved; records never fall back to a shared bucket.
    """
    from backend.uefn_plugins.scopes import active_scope

    scope = active_scope(plugin_id)
    sid = str(scope.get("id") or "personal")
    return f"{scope.get('account') or '_local'}~{sid}", sid


def _source(plugin_id: str, scope_key: str) -> str:
    return f"record:{plugin_id}:{scope_key}"


def upsert(plugin_id: str, record_id: str, title: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    rid = str(record_id or "").strip()
    if not _RECORD_ID.match(rid):
        raise ValueError("record_id: 1-200 characters, no ':' and no leading space")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("meta must be a dict")
    key, sid = _scope(plugin_id)
    doc = chunker.record_doc(
        plugin_id, key, rid, str(title or rid)[:MAX_TITLE], str(text or "")[:MAX_TEXT], dict(meta or {})
    )
    from backend.search.embedder import get_embedder

    emb = get_embedder()
    model = emb.model_id if emb is not None else ""
    state = repo.record_state(doc.doc_key, model)
    if state is not None and state[0] == doc.content_hash and (state[1] or not model):
        return {"ok": True, "id": rid, "scope": sid}  # unchanged: no re-embed, no write
    if state is None and repo.count_source(_source(plugin_id, key)) >= MAX_RECORDS:
        raise ValueError(f"search holds at most {MAX_RECORDS} records per plugin; delete some first")
    vec = emb.encode([chunker.embed_text(doc)])[0].tobytes() if emb is not None else None
    # The cap and the uninstalled-plugin check are repeated inside the write transaction.
    try:
        repo.upsert_one(doc, vec, model, max_in_source=MAX_RECORDS)
    except repo.PluginGone:
        from backend.uefn_plugins.store import is_plugin_installed

        if not is_plugin_installed(plugin_id):
            raise  # a thread or bridge copy that outlived the uninstall
        # Installed again, but the mark outlived it (the clear at install did not land).
        repo.clear_plugin_gone(plugin_id)
        repo.upsert_one(doc, vec, model, max_in_source=MAX_RECORDS)
    return {"ok": True, "id": rid, "scope": sid}


def delete(plugin_id: str, record_id: str) -> bool:
    key, _ = _scope(plugin_id)
    return repo.delete_docs([f"record:{plugin_id}:{key}:{str(record_id or '').strip()}"]) > 0


def clear(plugin_id: str) -> int:
    key, _ = _scope(plugin_id)
    return repo.drop_source(_source(plugin_id, key))


def query(plugin_id: str, text: str, limit: int = 10) -> list[dict[str, Any]]:
    from backend.search.query import Context, search

    try:
        key, _ = _scope(plugin_id)
    except Exception:  # noqa: BLE001 — no scope, no rows (never another account's)
        return []
    ctx = Context(record_plugin=plugin_id, record_scope=key)
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
