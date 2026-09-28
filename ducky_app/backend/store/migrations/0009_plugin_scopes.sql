-- 0009: plugin data belongs to one (account, scope): two accounts on one PC and
-- two teams of one account never share rows (team plans P3). scope_id is
-- 'personal' or a team id. Existing rows move with account_id '' and are claimed
-- by the first account (or '_local' when signed out) that opens plugin data.

CREATE TABLE plugin_kv_scoped (
  account_id TEXT NOT NULL,
  scope_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  encrypted  INTEGER NOT NULL DEFAULT 0,
  updated    REAL NOT NULL,
  PRIMARY KEY (account_id, scope_id, plugin_id, key)
);

INSERT INTO plugin_kv_scoped(account_id, scope_id, plugin_id, key, value, encrypted, updated)
  SELECT '', 'personal', plugin_id, key, value, encrypted, updated FROM plugin_kv;

DROP TABLE plugin_kv;

ALTER TABLE plugin_kv_scoped RENAME TO plugin_kv;

-- Host data service: one doc per entity (JSON in value) and asset files (bytes in
-- the scope folder, metadata here). rev = the server rev this copy matches;
-- dirty/deleted = a local change waiting to push. sensitive rows are Personal only.
CREATE TABLE plugin_data (
  account_id TEXT NOT NULL,
  scope_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL,
  value      TEXT,
  size       INTEGER NOT NULL DEFAULT 0,
  sha256     TEXT NOT NULL DEFAULT '',
  rev        INTEGER NOT NULL DEFAULT 0,
  dirty      INTEGER NOT NULL DEFAULT 0,
  deleted    INTEGER NOT NULL DEFAULT 0,
  sensitive  INTEGER NOT NULL DEFAULT 0,
  updated    REAL NOT NULL,
  PRIMARY KEY (account_id, scope_id, plugin_id, kind, key)
);
CREATE INDEX ix_plugin_data_dirty ON plugin_data(account_id, scope_id, dirty);

-- One row per (account, team) the PC syncs: cursor, state, last usage.
CREATE TABLE scope_sync (
  account_id TEXT NOT NULL,
  team_id    TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  members    INTEGER NOT NULL DEFAULT 0,
  cursor_rev INTEGER NOT NULL DEFAULT 0,
  state      TEXT NOT NULL DEFAULT 'ok',
  error      TEXT NOT NULL DEFAULT '',
  usage      TEXT NOT NULL DEFAULT '{}',
  synced_at  REAL NOT NULL DEFAULT 0,
  called_at  REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, team_id)
);

-- Which scope a desktop project shows, per account (no row = Personal).
CREATE TABLE project_scopes (
  account_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  scope_id   TEXT NOT NULL,
  updated    REAL NOT NULL,
  PRIMARY KEY (account_id, project_id)
);
