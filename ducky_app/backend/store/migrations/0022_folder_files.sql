-- 0022: plugins that keep their own folders (a plugin.json "team_folders" entry). Each
-- declared folder has a copy per scope: Local (scopes/_pc/<plugin>/folders/<id>/, shared
-- by every account) and one per team (scopes/<account>/<space>/<plugin>/folders/<id>/).
-- The plugin's own folder becomes a junction to the copy in use. A {PROJECT} root keeps
-- one subfolder per project (its id) in each copy.

-- Every file of a team's folder copy as this PC last saw it. relpath is the real path
-- under the copy ('/'-separated; the project id first for a {PROJECT} root); unit is what
-- locks and presence are about. base_seq / base_sha: the team's version this file is
-- based on (0 / '': new here). dirty: changed here and not sent yet; deleted with dirty
-- is a delete waiting to go out. changed_at: when the change happened (the quiet rule).
-- readonly: core made the file read-only (someone else holds its unit). item_key is the
-- item's key on the server (hashed names), once known.
CREATE TABLE IF NOT EXISTS folder_files (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  folder_id  TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT '',
  unit       TEXT NOT NULL,
  relpath    TEXT NOT NULL,
  size       INTEGER NOT NULL DEFAULT 0,
  mtime_ns   INTEGER NOT NULL DEFAULT 0,
  sha256     TEXT NOT NULL DEFAULT '',
  base_seq   INTEGER NOT NULL DEFAULT 0,
  base_sha   TEXT NOT NULL DEFAULT '',
  dirty      INTEGER NOT NULL DEFAULT 0,
  deleted    INTEGER NOT NULL DEFAULT 0,
  sync_state TEXT NOT NULL DEFAULT '',
  sync_error TEXT NOT NULL DEFAULT '',
  changed_at REAL NOT NULL DEFAULT 0,
  readonly   INTEGER NOT NULL DEFAULT 0,
  item_key   TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (account_id, space_id, plugin_id, folder_id, relpath)
);
CREATE INDEX IF NOT EXISTS folder_files_unit ON folder_files(account_id, space_id, plugin_id, folder_id, unit);
CREATE INDEX IF NOT EXISTS folder_files_dirty ON folder_files(account_id, space_id, plugin_id) WHERE dirty=1;
CREATE INDEX IF NOT EXISTS folder_files_key ON folder_files(account_id, space_id, plugin_id, item_key);

-- The junctions on this PC: the plugin's own folder (root), when it was adopted, and the
-- copy it points at now (target, and whose: account '_pc' for Local).
CREATE TABLE IF NOT EXISTS folder_links (
  plugin_id  TEXT NOT NULL,
  folder_id  TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT '',
  root       TEXT NOT NULL,
  adopted_at REAL NOT NULL DEFAULT 0,
  target     TEXT NOT NULL DEFAULT '',
  account_id TEXT NOT NULL DEFAULT '',
  space_id   TEXT NOT NULL DEFAULT '',
  updated    REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (plugin_id, folder_id, project_id)
);

-- A team's folder copy on this PC: the seq it was last pulled to completion at, when this
-- PC last sent to it, and whether it may be bound (ready: the team had files, or the
-- first share into it is done or started empty). offer: the plugin was put back on Local
-- because this copy was never pulled or sent; the bar offers to copy Local into the team.
CREATE TABLE IF NOT EXISTS folder_copies (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  folder_id  TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT '',
  pulled_seq INTEGER NOT NULL DEFAULT 0,
  pulled_at  REAL NOT NULL DEFAULT 0,
  pushed_at  REAL NOT NULL DEFAULT 0,
  ready      INTEGER NOT NULL DEFAULT 0,
  offer      INTEGER NOT NULL DEFAULT 0,
  updated    REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, folder_id, project_id)
);

-- The last synced content of each folder file a declaration's "merge" globs name (valid
-- JSON, sealed): the base of a three-way merge instead of a whole-unit conflict.
CREATE TABLE IF NOT EXISTS folder_merge_base (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  folder_id  TEXT NOT NULL,
  relpath    TEXT NOT NULL,
  seq        INTEGER NOT NULL DEFAULT 0,
  sha256     TEXT NOT NULL DEFAULT '',
  value      TEXT,
  PRIMARY KEY (account_id, space_id, plugin_id, folder_id, relpath)
);
