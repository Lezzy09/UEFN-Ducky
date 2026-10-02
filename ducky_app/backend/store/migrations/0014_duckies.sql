-- 0014: duckies get their own table, apart from settings. They lived inside the settings
-- rows (agent_profiles, agent_profile_overrides, a hide list for the shipped ones), where
-- any settings save holding a stale or empty copy wiped them, and one switch hid every
-- shipped ducky. Rows here are never deleted: a removed ducky is archived (shipped) or
-- marked deleted (custom), and every change keeps the previous copy in duckies_history.
-- backend.store.importers.duckies copies the old settings rows in once; it leaves them as they are.

CREATE TABLE IF NOT EXISTS duckies (
  id       TEXT PRIMARY KEY,
  kind     TEXT NOT NULL,                -- 'custom', or 'bundled' (the user's edits to a shipped ducky)
  data     TEXT NOT NULL DEFAULT '{}',   -- custom: the whole profile; bundled: the edited fields
  archived INTEGER NOT NULL DEFAULT 0,
  deleted  REAL NOT NULL DEFAULT 0,      -- custom only: when the user deleted it (row kept)
  created  REAL NOT NULL DEFAULT 0,
  updated  REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS duckies_history (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  id       TEXT NOT NULL,
  kind     TEXT NOT NULL,
  data     TEXT NOT NULL,
  archived INTEGER NOT NULL,
  deleted  REAL NOT NULL,
  saved    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS duckies_history_id ON duckies_history(id, seq);
