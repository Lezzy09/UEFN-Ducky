"""Plugin search records (``api.search``) sealed for their account.

A record row's scope is ``<account>~<scope id>``. What the plugin wrote (title, text, its
meta) is kept sealed for that account in ``meta`` (``{"sealed": "enc1:..."}``); the
keyword columns hold one keyed token per word (``account_rows.blind_text``), so keyword
search still works and the words aren't in ducky.db; the meaning vector is sealed with
the account's chat key. Only the signed-in account's rows are opened, so another account
on this PC finds and reads none of them. Exact words match; word stems and prefixes of
the plain index don't (meaning search covers those).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from typing import Any

from backend.store import account_rows, db

SEALED_PREFIX = '{"sealed": "enc1:'
VEC_MAGIC = b"UDV1"
# The rows a seal pass still has to seal, for one account (``?`` = that account).
PLAIN_RECORDS = (
    "kind='record' AND substr(scope, 1, length(?) + 1) = ? || '~' "
    f"AND substr(meta, 1, {len(SEALED_PREFIX)}) <> '{SEALED_PREFIX}'"
)


def owner(scope: str) -> str:
    return scope.split("~", 1)[0] if "~" in scope else ""


def is_sealed_meta(raw: object) -> bool:
    return isinstance(raw, str) and raw.startswith(SEALED_PREFIX)


def _vec_key(key: bytes) -> bytes:
    return hashlib.blake2b(b"", key=key, digest_size=32, person=b"search-vec").digest()


def keyed_hash(content_hash: str, key: bytes) -> str:
    """A record's change hash, keyed: a plain one would let anyone test a guess at its text."""
    return hashlib.blake2b(content_hash.encode("utf-8"), key=key, digest_size=32, person=b"search-rec").hexdigest()


def seal_vec(vec: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return VEC_MAGIC + nonce + AESGCM(_vec_key(key)).encrypt(nonce, vec, VEC_MAGIC)


def open_vec(raw: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(_vec_key(key)).decrypt(raw[4:16], raw[16:], VEC_MAGIC)


def seal_doc(doc: Any, account: str, key: bytes) -> Any:
    """The row ``doc`` (a plain ``repos.search.Doc``) is stored as: sealed, words blinded."""
    payload = json.dumps(
        {"title": doc.title, "path": doc.path, "body": doc.body, "summary": doc.summary, "meta": doc.meta},
        ensure_ascii=False,
    )
    blind = account_rows.blind_text
    return replace(
        doc,
        title=blind(doc.title, key),
        path=blind(doc.path, key),
        body=blind(doc.body, key),
        summary=blind(doc.summary, key),
        meta={"sealed": account_rows.seal(payload, account)},
        content_hash=keyed_hash(doc.content_hash, key),
    )


def open_row(row: dict[str, Any], account: str) -> dict[str, Any]:
    """A sealed record row as ``get_docs`` returns it: opened for its account when that is
    ``account`` (the signed-in one), emptied otherwise."""
    meta = row.get("meta")
    sealed = meta.get("sealed") if isinstance(meta, dict) else None
    if not isinstance(sealed, str):
        return row
    if owner(str(row.get("scope") or "")) != account:
        return {**row, "title": "", "path": "", "body": "", "meta": {}}
    plain = json.loads(account_rows.open_cached(sealed, account))
    return {
        **row,
        "title": str(plain.get("title") or ""),
        "path": str(plain.get("path") or ""),
        "body": str(plain.get("body") or ""),
        "meta": plain.get("meta") if isinstance(plain.get("meta"), dict) else {},
    }


def blind_match(text: str, key: bytes) -> str:
    """The FTS5 query for ``text`` over blinded rows: any of its words."""
    from backend.store.repos.search import _STOP

    tokens = list(dict.fromkeys(account_rows._token(w, key) for w in account_rows.words(text) if w not in _STOP))
    return " OR ".join(f'"{t}"' for t in tokens[:16])


def seal_existing(account: str, *, batch: int = 40) -> int:
    """Seal in place the account's records written before they were sealed (and their
    vectors). Resumable; a row rewritten meanwhile is left to the write that did it."""
    from backend.store.repos.search import Doc

    key = account_rows.ready(account)
    conn = db.connect()
    sealed = 0
    cursor = 0
    while True:
        rows = conn.execute(
            f"SELECT * FROM search_docs WHERE id > ? AND {PLAIN_RECORDS} ORDER BY id LIMIT ?",
            (cursor, account, account, batch),
        ).fetchall()
        if not rows:
            break
        todo = []
        for r in rows:
            try:
                meta = json.loads(r["meta"] or "{}")
            except ValueError:
                meta = {}
            doc = Doc(
                doc_key=r["doc_key"], source_key=r["source_key"], kind="record", title=r["title"], body=r["body"],
                path=r["path"], summary=r["summary"], origin=r["origin"], plugin_id=r["plugin_id"], scope=r["scope"],
                meta=meta if isinstance(meta, dict) else {}, content_hash=r["content_hash"],
            )
            todo.append((int(r["id"]), str(r["content_hash"]), seal_doc(doc, account, key)))
        with db.write_txn(conn):
            for doc_id, old_hash, new in todo:
                done = conn.execute(
                    "UPDATE search_docs SET title=?, path=?, body=?, summary=?, meta=?, content_hash=? "
                    "WHERE id=? AND content_hash=?",
                    (new.title, new.path, new.body, new.summary, new.row()[14], new.content_hash, doc_id, old_hash),
                ).rowcount
                if not done:
                    continue
                vec = conn.execute("SELECT vec FROM search_vecs WHERE doc_id=?", (doc_id,)).fetchone()
                if vec is not None and not bytes(vec[0]).startswith(VEC_MAGIC):
                    conn.execute("UPDATE search_vecs SET vec=? WHERE doc_id=?", (seal_vec(bytes(vec[0]), key), doc_id))
                sealed += 1
        cursor = todo[-1][0]
    if sealed:
        with db.write_txn(conn):
            conn.execute("INSERT INTO search_fts(search_fts) VALUES('optimize')")
    return sealed


def fill_missing_vectors(account: str, limit: int = 2000) -> int:
    """Vectors for ``account``'s sealed records that have none for the current meaning
    model (written before it loaded, or a model change): embedded from the opened text."""
    from backend.search import chunker
    from backend.search.embedder import get_embedder
    from backend.store.repos import search as repo

    emb = get_embedder()
    if emb is None:
        return 0
    key = account_rows.ready(account)
    rows = db.connect().execute(
        "SELECT d.id, d.doc_key, d.kind, d.scope, d.title, d.path, d.body, d.meta, d.content_hash FROM search_docs d "
        "LEFT JOIN search_vecs v ON v.doc_id = d.id AND v.model = ? "
        f"WHERE v.doc_id IS NULL AND d.kind = 'record' AND substr(d.meta, 1, {len(SEALED_PREFIX)}) = ? "
        "AND substr(d.scope, 1, length(?) + 1) = ? || '~' LIMIT ?",
        (emb.model_id, SEALED_PREFIX, account, account, max(1, int(limit))),
    ).fetchall()
    docs: list[Any] = []
    hashes: dict[str, str] = {}
    for r in rows:
        row = dict(r)
        try:
            row["meta"] = json.loads(row["meta"])
            opened = open_row(row, account)
        except Exception:  # noqa: BLE001 — sealed with a key this database no longer has
            continue
        docs.append(repo.Doc(
            doc_key=row["doc_key"], source_key="", kind="record", title=opened["title"], body=opened["body"],
            path=opened["path"], meta=opened["meta"],
        ))
        hashes[row["doc_key"]] = str(row["content_hash"])
    if not docs:
        return 0
    vectors = emb.encode([chunker.embed_text(d) for d in docs])
    sealed = {d.doc_key: seal_vec(vectors[i].tobytes(), key) for i, d in enumerate(docs)}
    return repo.set_vectors(sealed, emb.model_id, hashes)


def plain_left(account: str) -> int:
    row = db.connect().execute(f"SELECT count(*) FROM search_docs WHERE {PLAIN_RECORDS}", (account, account)).fetchone()
    return int(row[0])
