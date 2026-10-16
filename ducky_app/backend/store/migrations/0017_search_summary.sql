-- 0017: a tool's summary line gets its own keyword column. A tool row's body is its whole
-- docstring plus parameter names, so bm25 sank a tool whose first line says exactly what
-- the question asks ("Place an actor ..." for "place an actor in the level") under shorter
-- rows that only shared a word. search_fts is rebuilt with a fourth column, summary, that
-- ranking weights on its own; the body keeps the full text. Skill and record rows leave it
-- empty. Rows are derived data: the chunker version bump re-indexes every source.

ALTER TABLE search_docs ADD COLUMN summary TEXT NOT NULL DEFAULT '';

DROP TRIGGER IF EXISTS search_docs_ai;
DROP TRIGGER IF EXISTS search_docs_ad;
DROP TRIGGER IF EXISTS search_docs_au;
DROP TABLE IF EXISTS search_fts;

CREATE VIRTUAL TABLE search_fts USING fts5(
  title, path, body, summary,
  content='search_docs', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2'
);
INSERT INTO search_fts(search_fts) VALUES ('rebuild');

CREATE TRIGGER search_docs_ai AFTER INSERT ON search_docs BEGIN
  INSERT INTO search_fts(rowid, title, path, body, summary) VALUES (new.id, new.title, new.path, new.body, new.summary);
END;
CREATE TRIGGER search_docs_ad AFTER DELETE ON search_docs BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, path, body, summary)
    VALUES ('delete', old.id, old.title, old.path, old.body, old.summary);
END;
CREATE TRIGGER search_docs_au AFTER UPDATE OF title, path, body, summary ON search_docs BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, path, body, summary)
    VALUES ('delete', old.id, old.title, old.path, old.body, old.summary);
  INSERT INTO search_fts(rowid, title, path, body, summary) VALUES (new.id, new.title, new.path, new.body, new.summary);
END;
