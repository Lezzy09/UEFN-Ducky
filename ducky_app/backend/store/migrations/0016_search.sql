-- 0016: skill and tool search. One row per findable thing: a skill pack, a sub-skill,
-- one section of a sub-skill, an MCP tool, or a record a plugin indexed through
-- api.search. Keyword search runs on search_fts (bm25); meaning search on the
-- vectors in search_vecs. Rows are derived data: the indexer rebuilds them from the
-- skill files, the tool catalog and plugin calls, so wiping the tables loses nothing.
-- Every statement is IF NOT EXISTS so a re-run over an existing schema is a no-op.

CREATE TABLE IF NOT EXISTS search_docs (
  id           INTEGER PRIMARY KEY,
  doc_key      TEXT NOT NULL UNIQUE,      -- stable id, e.g. skill:uefn/epic_mcp#prefer-epic-first
  source_key   TEXT NOT NULL,             -- what produced it: pack:<id>, tools, record:<plugin>:<scope>
  kind         TEXT NOT NULL CHECK (kind IN ('pack', 'subskill', 'section', 'tool', 'record')),
  origin       TEXT NOT NULL DEFAULT '',  -- shipped, user, store, plugin, core, mcp
  plugin_id    TEXT NOT NULL DEFAULT '',  -- owning desktop plugin, '' for the app's own
  pack_id      TEXT NOT NULL DEFAULT '',
  subskill_id  TEXT NOT NULL DEFAULT '',
  section      TEXT NOT NULL DEFAULT '',  -- heading text of a section row
  tool_name    TEXT NOT NULL DEFAULT '',
  scope        TEXT NOT NULL DEFAULT '',  -- plugin data scope of a record row
  title        TEXT NOT NULL DEFAULT '',
  path         TEXT NOT NULL DEFAULT '',  -- heading path: pack > sub-skill > section
  body         TEXT NOT NULL DEFAULT '',
  meta         TEXT NOT NULL DEFAULT '{}', -- JSON: aliases, provider, record fields
  content_hash TEXT NOT NULL,
  updated      REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_search_docs_source ON search_docs(source_key);
CREATE INDEX IF NOT EXISTS ix_search_docs_kind ON search_docs(kind);
CREATE INDEX IF NOT EXISTS ix_search_docs_plugin ON search_docs(plugin_id);
CREATE INDEX IF NOT EXISTS ix_search_docs_skill ON search_docs(pack_id, subskill_id);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  title, path, body,
  content='search_docs', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS search_docs_ai AFTER INSERT ON search_docs BEGIN
  INSERT INTO search_fts(rowid, title, path, body) VALUES (new.id, new.title, new.path, new.body);
END;
CREATE TRIGGER IF NOT EXISTS search_docs_ad AFTER DELETE ON search_docs BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, path, body) VALUES ('delete', old.id, old.title, old.path, old.body);
END;
CREATE TRIGGER IF NOT EXISTS search_docs_au AFTER UPDATE OF title, path, body ON search_docs BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, path, body) VALUES ('delete', old.id, old.title, old.path, old.body);
  INSERT INTO search_fts(rowid, title, path, body) VALUES (new.id, new.title, new.path, new.body);
END;

-- One normalised float32 vector per row and model; a new model re-embeds every row.
CREATE TABLE IF NOT EXISTS search_vecs (
  doc_id INTEGER PRIMARY KEY REFERENCES search_docs(id) ON DELETE CASCADE,
  model  TEXT NOT NULL,
  vec    BLOB NOT NULL
);

-- What each source looked like when it was last indexed (pack stamp, catalog revision).
CREATE TABLE IF NOT EXISTS search_state (
  source_key TEXT PRIMARY KEY,
  revision   TEXT NOT NULL,
  indexed    REAL NOT NULL
);
