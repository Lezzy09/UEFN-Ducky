-- 0021: a shared space's copy kept as a versioned repo (changesets, item seqs, locks,
-- presence). plugin_data stays each PC's working copy: rev is the item's seq on the
-- server, and group_id ties the rows one tool call or panel call wrote, so they go out
-- as one changeset. Every table here is per (account, space): two accounts on one PC
-- never share a row.

ALTER TABLE plugin_data ADD COLUMN group_id TEXT NOT NULL DEFAULT '';

-- Per (account, space, plugin): the seq applied here (seq), the server's head at the
-- last look (remote_seq), the engine in use, the round's state and backoff, and Auto or
-- Manual sync. moves: pushes that met a newer head in a row.
CREATE TABLE IF NOT EXISTS space_heads (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  seq        INTEGER NOT NULL DEFAULT 0,
  remote_seq INTEGER NOT NULL DEFAULT 0,
  epoch      TEXT NOT NULL DEFAULT '',
  engine     TEXT NOT NULL DEFAULT 'v1',
  state      TEXT NOT NULL DEFAULT 'ok',
  error      TEXT NOT NULL DEFAULT '',
  attempts   INTEGER NOT NULL DEFAULT 0,
  next_try   REAL NOT NULL DEFAULT 0,
  moves      INTEGER NOT NULL DEFAULT 0,
  mode       TEXT NOT NULL DEFAULT 'auto',
  synced_at  REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id)
);

-- A changeset is written here before anything is uploaded, so a crash replays the same
-- cs_id (the server answers replay when it had committed it). items_json lists what it
-- carries (kind, key, unit); the content is read from the rows when it goes out.
CREATE TABLE IF NOT EXISTS space_changesets (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  cs_id      TEXT NOT NULL,
  base_seq   INTEGER NOT NULL DEFAULT 0,
  group_id   TEXT NOT NULL DEFAULT '',
  part       INTEGER NOT NULL DEFAULT 1,
  last       INTEGER NOT NULL DEFAULT 1,
  state      TEXT NOT NULL DEFAULT 'pending',
  message    TEXT NOT NULL DEFAULT '',
  actor      TEXT NOT NULL DEFAULT 'user',
  ducky      TEXT NOT NULL DEFAULT '',
  items_json TEXT NOT NULL DEFAULT '[]',
  seq        INTEGER NOT NULL DEFAULT 0,
  error      TEXT NOT NULL DEFAULT '',
  created    REAL NOT NULL,
  updated    REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, cs_id)
);
CREATE INDEX IF NOT EXISTS space_changesets_open ON space_changesets(account_id, space_id, plugin_id, state, created);

-- A losing version kept until the person resolves it. reason: changed (both edited),
-- deleted (theirs deleted what mine changed), mine_deleted (mine deleted what theirs
-- changed), lock_broken (mine were unsent edits under a lock someone broke). A doc's
-- mine is sealed in mine_value; a file's is a sealed side copy at mine_path.
CREATE TABLE IF NOT EXISTS space_conflicts (
  account_id     TEXT NOT NULL,
  space_id       TEXT NOT NULL,
  plugin_id      TEXT NOT NULL,
  kind           TEXT NOT NULL,
  key            TEXT NOT NULL,
  unit           TEXT NOT NULL DEFAULT '',
  reason         TEXT NOT NULL DEFAULT 'changed',
  mine_value     TEXT,
  mine_path      TEXT NOT NULL DEFAULT '',
  mine_sha       TEXT NOT NULL DEFAULT '',
  mine_size      INTEGER NOT NULL DEFAULT 0,
  mine_deleted   INTEGER NOT NULL DEFAULT 0,
  base_seq       INTEGER NOT NULL DEFAULT 0,
  theirs_seq     INTEGER NOT NULL DEFAULT 0,
  theirs_by      TEXT NOT NULL DEFAULT '',
  theirs_at      REAL NOT NULL DEFAULT 0,
  theirs_deleted INTEGER NOT NULL DEFAULT 0,
  created        REAL NOT NULL,
  PRIMARY KEY (account_id, space_id, plugin_id, kind, key)
);

-- An incoming item that couldn't be applied here (bad download, file held open, disk
-- full). The cursor moved on; it is retried on its own at its current version.
CREATE TABLE IF NOT EXISTS space_incoming_blocked (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL,
  unit       TEXT NOT NULL DEFAULT '',
  seq        INTEGER NOT NULL DEFAULT 0,
  error      TEXT NOT NULL DEFAULT '',
  attempts   INTEGER NOT NULL DEFAULT 0,
  next_try   REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, kind, key)
);

-- Live locks of the space as the server last said, read by writers in every process.
-- lease_left_at is this PC's clock. mine: held by this account on this PC; reason
-- (auto | manual), renewed and touched (its unit's last committed change) are kept
-- for those only.
CREATE TABLE IF NOT EXISTS space_locks (
  account_id    TEXT NOT NULL,
  space_id      TEXT NOT NULL,
  plugin_id     TEXT NOT NULL,
  unit          TEXT NOT NULL,
  name          TEXT NOT NULL DEFAULT '',
  holder_user   TEXT NOT NULL DEFAULT '',
  holder_name   TEXT NOT NULL DEFAULT '',
  holder_device TEXT NOT NULL DEFAULT '',
  since         REAL NOT NULL DEFAULT 0,
  lease_left_at REAL NOT NULL DEFAULT 0,
  fence         INTEGER NOT NULL DEFAULT 0,
  mine          INTEGER NOT NULL DEFAULT 0,
  reason        TEXT NOT NULL DEFAULT '',
  renewed       REAL NOT NULL DEFAULT 0,
  touched       REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, unit)
);

-- Who else is in the space (the server's roster, opened), and the last beat sent.
CREATE TABLE IF NOT EXISTS space_presence (
  account_id  TEXT NOT NULL,
  space_id    TEXT NOT NULL,
  roster_json TEXT NOT NULL DEFAULT '{}',
  updated     REAL NOT NULL DEFAULT 0,
  sent_sha    TEXT NOT NULL DEFAULT '',
  sent_at     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id)
);

-- Units changed here lately, by whom (user, or agent with the ducky's name). Pruned
-- after 2 minutes; presence says "editing" from it.
CREATE TABLE IF NOT EXISTS space_activity (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  unit       TEXT NOT NULL,
  actor      TEXT NOT NULL DEFAULT 'user',
  ducky      TEXT NOT NULL DEFAULT '',
  since      REAL NOT NULL DEFAULT 0,
  at         REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, unit, actor, ducky)
);

-- One write group per plugin tool call or panel call: its rows go out together.
CREATE TABLE IF NOT EXISTS space_groups (
  group_id  TEXT PRIMARY KEY,
  plugin_id TEXT NOT NULL,
  open      INTEGER NOT NULL DEFAULT 1,
  actor     TEXT NOT NULL DEFAULT 'user',
  ducky     TEXT NOT NULL DEFAULT '',
  message   TEXT NOT NULL DEFAULT '',
  started   REAL NOT NULL DEFAULT 0,
  closed    REAL NOT NULL DEFAULT 0
);

-- A writer that needs a lock first asks for it here and waits for the answer.
CREATE TABLE IF NOT EXISTS space_lock_requests (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  unit       TEXT NOT NULL,
  name       TEXT NOT NULL DEFAULT '',
  state      TEXT NOT NULL DEFAULT 'pending',
  answer     TEXT NOT NULL DEFAULT '',
  created    REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, unit)
);

-- The last synced content of each shared doc (sealed): the base of a three-way merge.
CREATE TABLE IF NOT EXISTS plugin_data_base (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  key        TEXT NOT NULL,
  seq        INTEGER NOT NULL DEFAULT 0,
  sha256     TEXT NOT NULL DEFAULT '',
  value      TEXT,
  PRIMARY KEY (account_id, space_id, plugin_id, key)
);

-- The seq of the last changeset applied here that touched each unit: what a lock
-- request says this PC has seen of it (a lock is granted only to a PC that is not behind).
CREATE TABLE IF NOT EXISTS space_units (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  unit       TEXT NOT NULL,
  seq        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id, plugin_id, unit)
);

-- What the person chose for unsent changes of a space they lost access to (saved to
-- Local or discarded); until then the copy here is not purged.
CREATE TABLE IF NOT EXISTS space_lost_choice (
  account_id TEXT NOT NULL,
  space_id   TEXT NOT NULL,
  choice     TEXT NOT NULL,
  at         REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, space_id)
);
