"""search_docs / search_fts / search_vecs / search_state (migration 0016) through the repo."""

from __future__ import annotations

import struct

from backend.store import db
from backend.store.repos import search as repo


def _doc(key: str, title: str, body: str, *, source: str = "pack:p", kind: str = "section", **kw) -> repo.Doc:
    d = repo.Doc(doc_key=key, source_key=source, kind=kind, title=title, body=body, **kw)
    d.content_hash = f"h:{title}:{body}"
    return d


def _vec(*values: float) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def test_tables_exist_at_head_version() -> None:
    conn = db.connect()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"search_docs", "search_fts", "search_vecs", "search_state"} <= names


def test_write_source_adds_skips_unchanged_and_prunes() -> None:
    a = _doc("skill:p/a#one", "One", "starfield night sky")
    b = _doc("skill:p/a#two", "Two", "ocean water waves")
    res = repo.write_source("pack:p", [a, b], {a.doc_key: _vec(1, 0), b.doc_key: _vec(0, 1)}, model="m", revision="r1")
    assert res == {"added": 2, "changed": 0, "removed": 0}
    have = repo.existing("pack:p", "m")
    assert set(have) == {a.doc_key, b.doc_key} and all(v[2] for v in have.values())

    res = repo.write_source("pack:p", [a, b], {}, model="m", revision="r1")
    assert res == {"added": 0, "changed": 0, "removed": 0}

    b2 = _doc("skill:p/a#two", "Two", "ocean water waves foam")
    res = repo.write_source("pack:p", [b2], {}, model="m", revision="r2")
    assert res == {"added": 0, "changed": 1, "removed": 1}
    # The changed row lost its stale vector; the pruned row is gone with its vector.
    have = repo.existing("pack:p", "m")
    assert list(have) == [b2.doc_key] and have[b2.doc_key][2] is False
    assert repo.get_state("pack:p") == "r2"
    assert db.connect().execute("SELECT count(*) FROM search_vecs").fetchone()[0] == 0


def test_keep_preserves_rows_missing_from_a_refresh() -> None:
    a = _doc("tool:srv__ping", "ping", "ping the server", source="tools", kind="tool", tool_name="srv__ping")
    repo.write_source("tools", [a], {}, model="m", revision="r1")
    repo.write_source("tools", [], {}, model="m", revision="r2", keep={a.doc_key})
    assert repo.find_doc(a.doc_key) is not None


def test_keyword_ranks_by_bm25_and_filters_kinds() -> None:
    docs = [
        _doc("skill:p/a#1", "Starfield recipe", "night sky stars material"),
        _doc("skill:p/a#2", "Water", "ocean material with waves"),
        _doc("tool:create_material", "create material", "create a material asset", kind="tool", source="tools"),
    ]
    repo.write_source("pack:p", docs[:2], {}, model="", revision="r")
    repo.write_source("tools", docs[2:], {}, model="", revision="r")
    hits = repo.keyword("night sky stars")
    first = repo.get_docs([hits[0][0]])[hits[0][0]]
    assert first["doc_key"] == "skill:p/a#1"
    tools = repo.keyword("material", kinds=["tool"])
    assert [repo.get_docs([i])[i]["kind"] for i, _ in tools] == ["tool"]


def test_a_tools_summary_line_outweighs_the_same_words_in_its_body() -> None:
    # Same words and lengths; only where "place an actor" sits differs.
    lead = _doc("tool:spawn_thing", "spawn thing", "spawn thing\nWorks with meshes and devices.", kind="tool",
                source="tools", summary="Place an actor.")
    notes = _doc("tool:read_thing", "read thing", "read thing\nPlace an actor.", kind="tool", source="tools",
                 summary="Works with meshes and devices.")
    # Enough other rows that "place" and "actor" stay rare (a positive idf).
    others = [_doc(f"skill:p/a#{i}", f"Other {i}", "ocean water waves foam") for i in range(4)]
    repo.write_source("pack:p", others, {}, model="", revision="r")
    repo.write_source("tools", [notes, lead], {}, model="", revision="r")
    hits = repo.keyword("place an actor", kinds=["tool"])
    assert [repo.get_docs([i])[i]["doc_key"] for i, _ in hits] == ["tool:spawn_thing", "tool:read_thing"]


def test_search_rows_from_before_the_summary_column_survive_the_upgrade(monkeypatch) -> None:
    """0017 rebuilds search_fts with a summary column; rows indexed at 0016 stay findable
    until the chunker version bump rewrites them."""
    real_files = db.migration_files
    monkeypatch.setattr(db, "migration_files", lambda: [(n, p) for n, p in real_files() if n <= 16])
    db.reset_for_tests()
    conn = db.connect()
    assert db.user_version(conn) == 16
    with db.write_txn(conn):
        conn.execute(
            "INSERT INTO search_docs(doc_key, source_key, kind, title, path, body, content_hash) "
            "VALUES ('tool:spawn_actor', 'tools', 'tool', 'spawn actor', 'UEFN', 'Place an actor in the level.', 'old')"
        )
    db.reset_for_tests()
    monkeypatch.setattr(db, "migration_files", real_files)

    conn = db.connect()
    assert db.user_version(conn) == db.head_version()
    hits = repo.keyword("place an actor", kinds=["tool"])
    assert [repo.get_docs([i])[i]["doc_key"] for i, _ in hits] == ["tool:spawn_actor"]
    # The rewrite moves the first line into the summary; the delete trigger must find the old body.
    new = _doc("tool:spawn_actor", "spawn actor", "spawn actor", kind="tool", source="tools",
               summary="Place an actor in the level.")
    assert repo.write_source("tools", [new], {}, model="", revision="r")["changed"] == 1
    assert len(repo.keyword("place an actor", kinds=["tool"])) == 1
    assert repo.keyword("UEFN", kinds=["tool"]) == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.execute("INSERT INTO search_fts(search_fts) VALUES ('integrity-check')")


def test_hostile_query_text_never_raises() -> None:
    repo.write_source("pack:p", [_doc("skill:p/a#1", "Title", "body text")], {}, model="", revision="r")
    for text in ['AND OR NOT', '"unbalanced', "star*", "col:umn", "🦆🦆", "", "   ", "NEAR(a b)", "a" * 5000]:
        assert isinstance(repo.keyword(text), list)
    assert repo.fts_query("") == ""
    assert repo.fts_query("the a to") == '"the" OR "a" OR "to"'  # all stopwords: keep them
    assert repo.fts_query("wire the device") == '"wire" OR "device"*'


def test_vectors_load_in_id_order_and_cascade_on_delete() -> None:
    a = _doc("skill:p/a#1", "One", "x")
    b = _doc("skill:p/a#2", "Two", "y")
    repo.write_source("pack:p", [a, b], {a.doc_key: _vec(1, 2), b.doc_key: _vec(3, 4)}, model="m", revision="r")
    ids, kinds, blob = repo.load_vectors("m")
    assert len(ids) == 2 and kinds == ["section", "section"] and len(blob) == 16
    assert repo.drop_source("pack:p") == 2
    assert repo.load_vectors("m")[0] == []


def test_upsert_one_and_drop_sources_like() -> None:
    rec = _doc("record:wiki:personal:p1", "Page", "spawner device", source="record:wiki:personal", kind="record",
               plugin_id="wiki", scope="personal")
    repo.upsert_one(rec, _vec(1, 0), "m")
    repo.upsert_one(rec, None, "m")  # unchanged, no vector: no-op
    assert repo.load_vectors("m")[0] != []
    other = _doc("record:wiki_x:personal:p1", "Other", "x", source="record:wiki_x:personal", kind="record")
    repo.upsert_one(other, None, "m")
    # "wiki" must not match "wiki_x": LIKE escaping of _.
    assert repo.drop_sources_like("record:wiki:") == 1
    assert repo.find_doc(other.doc_key) is not None


def test_missing_vectors_and_counts() -> None:
    a = _doc("skill:p/a#1", "One", "x")
    repo.write_source("pack:p", [a], {}, model="", revision="r")
    missing = repo.missing_vectors("m")
    assert [d.doc_key for d in missing] == [a.doc_key]
    assert repo.set_vectors({a.doc_key: _vec(1)}, "m") == 1
    assert repo.missing_vectors("m") == []
    counts = repo.counts()
    assert counts["docs"] == {"section": 1} and counts["vectors"] == {"m": 1}
    assert repo.has_docs()
    repo.wipe()
    assert not repo.has_docs() and repo.states() == {}
