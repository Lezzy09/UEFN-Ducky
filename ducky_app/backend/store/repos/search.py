"""``search_docs`` + ``search_fts`` + ``search_vecs``: the skill and tool search index.

Rows are derived data (``backend.search.indexer`` rebuilds them), so every write
here is an idempotent upsert keyed by ``doc_key``: two processes indexing the same
source at once end with the same rows.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.store import db

KINDS = ("pack", "subskill", "section", "tool", "record")
# bm25 column weights: title, heading path, body.
_BM25 = "bm25(search_fts, 3.0, 2.0, 1.0)"
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_QUERY_TOKENS = 16
# Words that match nearly every row; OR-ing them in only adds noise to the candidates.
_STOP = frozenset(
    "a an and are as at be by can do does for from how i in into is it its me my of on or our so that the "
    "their them then there these this to up we what when where which why will with you your".split()
)


@dataclass
class Doc:
    doc_key: str
    source_key: str
    kind: str
    title: str
    body: str
    path: str = ""
    origin: str = ""
    plugin_id: str = ""
    pack_id: str = ""
    subskill_id: str = ""
    section: str = ""
    tool_name: str = ""
    scope: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def row(self) -> tuple[Any, ...]:
        return (
            self.doc_key, self.source_key, self.kind, self.origin, self.plugin_id, self.pack_id,
            self.subskill_id, self.section, self.tool_name, self.scope, self.title, self.path,
            self.body, json.dumps(self.meta, sort_keys=True, ensure_ascii=False), self.content_hash, time.time(),
        )


_COLUMNS = (
    "doc_key, source_key, kind, origin, plugin_id, pack_id, subskill_id, section, tool_name, "
    "scope, title, path, body, meta, content_hash, updated"
)


def existing(source_key: str, model: str) -> dict[str, tuple[int, str, bool]]:
    """doc_key -> (id, content_hash, has a vector for ``model``) for one source."""
    rows = db.connect().execute(
        "SELECT d.id, d.doc_key, d.content_hash, (v.doc_id IS NOT NULL) AS has_vec FROM search_docs d "
        "LEFT JOIN search_vecs v ON v.doc_id = d.id AND v.model = ? WHERE d.source_key = ?",
        (model, source_key),
    ).fetchall()
    return {str(r["doc_key"]): (int(r["id"]), str(r["content_hash"]), bool(r["has_vec"])) for r in rows}


def write_source(
    source_key: str,
    docs: list[Doc],
    vectors: dict[str, bytes],
    *,
    model: str,
    revision: str,
    replace: bool = True,
    keep: set[str] | None = None,
) -> dict[str, int]:
    """Upsert ``docs`` and their ``vectors`` (doc_key -> float32 bytes) in one transaction.

    With ``replace`` the source's rows that are not in ``docs`` (or ``keep``) are
    deleted (a pack lost a file, a tool left the catalog). Unchanged rows are not
    rewritten.
    """
    conn = db.connect()
    added = changed = removed = 0
    keep_extra = set(keep or ())
    with db.write_txn(conn):
        have = {
            str(r["doc_key"]): (int(r["id"]), str(r["content_hash"]))
            for r in conn.execute("SELECT id, doc_key, content_hash FROM search_docs WHERE source_key=?", (source_key,))
        }
        keep: set[str] = set()
        for doc in docs:
            keep.add(doc.doc_key)
            current = have.get(doc.doc_key)
            if current is None:
                # A doc_key can move between sources (a pack moved from AppData to a plugin).
                conn.execute("DELETE FROM search_docs WHERE doc_key=?", (doc.doc_key,))
                cur = conn.execute(
                    f"INSERT INTO search_docs({_COLUMNS}) VALUES ({', '.join('?' * 16)})", doc.row()
                )
                doc_id = int(cur.lastrowid)
                added += 1
            else:
                doc_id = current[0]
                if current[1] != doc.content_hash:
                    conn.execute(
                        "UPDATE search_docs SET source_key=?, kind=?, origin=?, plugin_id=?, pack_id=?, subskill_id=?, "
                        "section=?, tool_name=?, scope=?, title=?, path=?, body=?, meta=?, content_hash=?, updated=? "
                        "WHERE id=?",
                        (*doc.row()[1:], doc_id),
                    )
                    conn.execute("DELETE FROM search_vecs WHERE doc_id=?", (doc_id,))
                    changed += 1
            vec = vectors.get(doc.doc_key)
            if vec is not None:
                conn.execute(
                    "INSERT INTO search_vecs(doc_id, model, vec) VALUES (?, ?, ?) "
                    "ON CONFLICT(doc_id) DO UPDATE SET model=excluded.model, vec=excluded.vec",
                    (doc_id, model, vec),
                )
        if replace:
            keep |= keep_extra
            for key, (doc_id, _) in have.items():
                if key not in keep:
                    conn.execute("DELETE FROM search_docs WHERE id=?", (doc_id,))
                    removed += 1
        conn.execute(
            "INSERT INTO search_state(source_key, revision, indexed) VALUES (?, ?, ?) "
            "ON CONFLICT(source_key) DO UPDATE SET revision=excluded.revision, indexed=excluded.indexed",
            (source_key, revision, time.time()),
        )
    return {"added": added, "changed": changed, "removed": removed}


def missing_vectors(model: str, limit: int = 5000) -> list[Doc]:
    """Rows with no vector for ``model`` (records added before the model loaded, a model change)."""
    rows = db.connect().execute(
        "SELECT d.* FROM search_docs d LEFT JOIN search_vecs v ON v.doc_id = d.id AND v.model = ? "
        "WHERE v.doc_id IS NULL LIMIT ?",
        (model, max(1, int(limit))),
    ).fetchall()
    out: list[Doc] = []
    for r in rows:
        try:
            meta = json.loads(r["meta"] or "{}")
        except ValueError:
            meta = {}
        out.append(Doc(
            doc_key=r["doc_key"], source_key=r["source_key"], kind=r["kind"], title=r["title"], body=r["body"],
            path=r["path"], origin=r["origin"], plugin_id=r["plugin_id"], pack_id=r["pack_id"],
            subskill_id=r["subskill_id"], section=r["section"], tool_name=r["tool_name"], scope=r["scope"],
            meta=meta, content_hash=r["content_hash"],
        ))
    return out


def set_vectors(vectors: dict[str, bytes], model: str) -> int:
    """doc_key -> vector for rows that already exist."""
    if not vectors:
        return 0
    conn = db.connect()
    n = 0
    with db.write_txn(conn):
        for key, vec in vectors.items():
            row = conn.execute("SELECT id FROM search_docs WHERE doc_key=?", (key,)).fetchone()
            if row is None:
                continue
            conn.execute(
                "INSERT INTO search_vecs(doc_id, model, vec) VALUES (?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET model=excluded.model, vec=excluded.vec",
                (int(row[0]), model, vec),
            )
            n += 1
    return n


def upsert_one(doc: Doc, vec: bytes | None, model: str) -> None:
    """One record row (api.search): insert or update in place, vector alongside."""
    conn = db.connect()
    with db.write_txn(conn):
        row = conn.execute("SELECT id, content_hash FROM search_docs WHERE doc_key=?", (doc.doc_key,)).fetchone()
        if row is None:
            cur = conn.execute(f"INSERT INTO search_docs({_COLUMNS}) VALUES ({', '.join('?' * 16)})", doc.row())
            doc_id = int(cur.lastrowid)
        else:
            doc_id = int(row[0])
            if str(row[1]) == doc.content_hash and vec is None:
                return
            conn.execute(
                "UPDATE search_docs SET source_key=?, kind=?, origin=?, plugin_id=?, pack_id=?, subskill_id=?, "
                "section=?, tool_name=?, scope=?, title=?, path=?, body=?, meta=?, content_hash=?, updated=? WHERE id=?",
                (*doc.row()[1:], doc_id),
            )
            conn.execute("DELETE FROM search_vecs WHERE doc_id=?", (doc_id,))
        if vec is not None:
            conn.execute(
                "INSERT INTO search_vecs(doc_id, model, vec) VALUES (?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET model=excluded.model, vec=excluded.vec",
                (doc_id, model, vec),
            )


def find_doc(doc_key: str) -> int | None:
    row = db.connect().execute("SELECT id FROM search_docs WHERE doc_key=?", (doc_key,)).fetchone()
    return None if row is None else int(row[0])


def count_source(source_key: str) -> int:
    row = db.connect().execute("SELECT count(*) FROM search_docs WHERE source_key=?", (source_key,)).fetchone()
    return int(row[0])


def delete_docs(doc_keys: Iterable[str]) -> int:
    keys = list(doc_keys)
    if not keys:
        return 0
    conn = db.connect()
    n = 0
    with db.write_txn(conn):
        for key in keys:
            n += conn.execute("DELETE FROM search_docs WHERE doc_key=?", (key,)).rowcount
    return n


def drop_source(source_key: str) -> int:
    conn = db.connect()
    with db.write_txn(conn):
        n = conn.execute("DELETE FROM search_docs WHERE source_key=?", (source_key,)).rowcount
        conn.execute("DELETE FROM search_state WHERE source_key=?", (source_key,))
    return n


def drop_sources_like(prefix: str) -> int:
    """Delete every source whose key starts with ``prefix`` (a plugin's records on uninstall)."""
    conn = db.connect()
    like = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db.write_txn(conn):
        n = conn.execute("DELETE FROM search_docs WHERE source_key LIKE ? ESCAPE '\\'", (like,)).rowcount
        conn.execute("DELETE FROM search_state WHERE source_key LIKE ? ESCAPE '\\'", (like,))
    return n


def source_keys() -> list[str]:
    rows = db.connect().execute("SELECT DISTINCT source_key FROM search_docs").fetchall()
    return [str(r[0]) for r in rows]


def get_state(source_key: str) -> str | None:
    row = db.connect().execute("SELECT revision FROM search_state WHERE source_key=?", (source_key,)).fetchone()
    return None if row is None else str(row[0])


def states() -> dict[str, tuple[str, float]]:
    return {
        str(r[0]): (str(r[1]), float(r[2]))
        for r in db.connect().execute("SELECT source_key, revision, indexed FROM search_state").fetchall()
    }


def wipe() -> None:
    conn = db.connect()
    with db.write_txn(conn):
        conn.execute("DELETE FROM search_docs")
        conn.execute("DELETE FROM search_state")


# --------------------------------------------------------------------------- reads


def fts_query(text: str) -> str:
    """Safe FTS5 MATCH text: quoted tokens OR'd together, the last one as a prefix.

    Quoting every token keeps FTS5 syntax (AND, NEAR, ``*``, ``:``, quotes) in the
    person's words from being parsed as operators.
    """
    tokens = [t.lower() for t in _TOKEN.findall(text or "")]
    tokens = list(dict.fromkeys([t for t in tokens if t not in _STOP] or tokens))[:_MAX_QUERY_TOKENS]
    if not tokens:
        return ""
    parts = [f'"{t}"' for t in tokens[:-1]]
    last = tokens[-1]
    parts.append(f'"{last}"*' if len(last) >= 3 else f'"{last}"')
    return " OR ".join(parts)


def keyword(text: str, kinds: Iterable[str] | None = None, limit: int = 50) -> list[tuple[int, float]]:
    """(doc id, bm25 score — lower is better) for the best keyword matches."""
    match = fts_query(text)
    if not match:
        return []
    sql = (
        f"SELECT d.id, {_BM25} AS score FROM search_fts JOIN search_docs d ON d.id = search_fts.rowid "
        "WHERE search_fts MATCH ?"
    )
    args: list[Any] = [match]
    kinds = [k for k in (kinds or []) if k in KINDS]
    if kinds:
        sql += f" AND d.kind IN ({', '.join('?' * len(kinds))})"
        args.extend(kinds)
    sql += " ORDER BY score LIMIT ?"
    args.append(max(1, int(limit)))
    try:
        rows = db.connect().execute(sql, args).fetchall()
    except db.DatabaseError:
        return []
    return [(int(r[0]), float(r[1])) for r in rows]


def load_vectors(model: str) -> tuple[list[int], list[str], bytes]:
    """Every vector of ``model``: (doc ids, kinds, concatenated float32 bytes) in id order."""
    rows = db.connect().execute(
        "SELECT v.doc_id, d.kind, v.vec FROM search_vecs v JOIN search_docs d ON d.id = v.doc_id "
        "WHERE v.model = ? ORDER BY v.doc_id",
        (model,),
    ).fetchall()
    return [int(r[0]) for r in rows], [str(r[1]) for r in rows], b"".join(bytes(r[2]) for r in rows)


def get_docs(ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    wanted = list(dict.fromkeys(int(i) for i in ids))
    out: dict[int, dict[str, Any]] = {}
    conn = db.connect()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        rows = conn.execute(
            f"SELECT id, doc_key, source_key, kind, origin, plugin_id, pack_id, subskill_id, section, tool_name, scope, "
            f"title, path, body, meta FROM search_docs WHERE id IN ({', '.join('?' * len(chunk))})",
            chunk,
        ).fetchall()
        for r in rows:
            row = dict(r)
            try:
                row["meta"] = json.loads(row.get("meta") or "{}")
            except ValueError:
                row["meta"] = {}
            out[int(r["id"])] = row
    return out


def title_words(text: str) -> str:
    """The words of ``text`` without stop words, lower case: "run a workflow" -> "run workflow"."""
    return " ".join(t for t in _TOKEN.findall(text.lower()) if t not in _STOP)


def find_ids(
    *, kind: str, pack_id: str = "", subskill_id: str = "", tool_name: str = "", title: str = ""
) -> list[int]:
    """Exact lookups for pinning: a pack or sub-skill id, a tool name, or a title (case-insensitive)."""
    sql = "SELECT id FROM search_docs WHERE kind=?"
    args: list[Any] = [kind]
    if title:
        sql += " AND lower(title)=?"
        args.append(title.lower())
    if pack_id:
        sql += " AND pack_id=?"
        args.append(pack_id)
    if subskill_id:
        sql += " AND subskill_id=?"
        args.append(subskill_id)
    if tool_name:
        sql += " AND tool_name=?"
        args.append(tool_name)
    return [int(r[0]) for r in db.connect().execute(sql, args).fetchall()]


def has_docs() -> bool:
    return db.connect().execute("SELECT 1 FROM search_docs LIMIT 1").fetchone() is not None


def counts() -> dict[str, Any]:
    conn = db.connect()
    kinds = {str(r[0]): int(r[1]) for r in conn.execute("SELECT kind, count(*) FROM search_docs GROUP BY kind")}
    vecs = {str(r[0]): int(r[1]) for r in conn.execute("SELECT model, count(*) FROM search_vecs GROUP BY model")}
    last = conn.execute("SELECT max(indexed) FROM search_state").fetchone()[0]
    return {"docs": kinds, "vectors": vecs, "last_indexed": float(last or 0), "sources": len(states())}


def data_version() -> int:
    return db.data_version(db.connect())


def revision_token() -> str:
    """Changes whenever any source was re-indexed (cheap; drives per-process caches)."""
    row = db.connect().execute("SELECT count(*), coalesce(max(indexed), 0), coalesce(sum(length(revision)), 0) FROM search_state").fetchone()
    vecs = db.connect().execute("SELECT count(*), coalesce(max(doc_id), 0) FROM search_vecs").fetchone()
    return f"{row[0]}:{row[1]}:{row[2]}:{vecs[0]}:{vecs[1]}"
