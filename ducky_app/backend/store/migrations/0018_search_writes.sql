-- 0018: one write counter for the search index, kept by triggers.
-- Every process caches the vector matrix under a revision token. The token was built
-- from row counts and the highest ids, so an in-place change (a plugin record updated
-- or deleted, a vector filled for a row) left it unchanged and every process kept
-- ranking by the old vectors. Triggers count every insert, update and delete of
-- search_docs and search_vecs, whoever writes them (an older app process, a Database
-- tab clear, a cascade), and the token is this one row, read in a fraction of a ms
-- (the old count over every vector row cost about 4 ms per search).
-- Every statement is IF NOT EXISTS or idempotent, so a re-run over this schema is a no-op.

CREATE TABLE IF NOT EXISTS search_meta (
  key   TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO search_meta(key, value) VALUES ('writes', 0);

CREATE TRIGGER IF NOT EXISTS search_docs_writes_ai AFTER INSERT ON search_docs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;
CREATE TRIGGER IF NOT EXISTS search_docs_writes_au AFTER UPDATE ON search_docs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;
CREATE TRIGGER IF NOT EXISTS search_docs_writes_ad AFTER DELETE ON search_docs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;
CREATE TRIGGER IF NOT EXISTS search_vecs_writes_ai AFTER INSERT ON search_vecs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;
CREATE TRIGGER IF NOT EXISTS search_vecs_writes_au AFTER UPDATE ON search_vecs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;
CREATE TRIGGER IF NOT EXISTS search_vecs_writes_ad AFTER DELETE ON search_vecs BEGIN
  UPDATE search_meta SET value = value + 1 WHERE key = 'writes';
END;

-- Per-model vector counts (Database tab, status) read this instead of every 1 KB vector.
CREATE INDEX IF NOT EXISTS ix_search_vecs_model ON search_vecs(model);

-- Plugin records are now keyed by account as well as data scope (scope '<account>~<id>'),
-- so one account's records are never shown to another account on the same PC. Rows
-- stored before have no account and could belong to anyone: drop them; plugins re-upsert.
DELETE FROM search_docs WHERE kind = 'record' AND instr(scope, '~') = 0;
