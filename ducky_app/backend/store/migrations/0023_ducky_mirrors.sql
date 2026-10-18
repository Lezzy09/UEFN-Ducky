-- 0023: chats of your other UEFN Duckies, as this Ducky last saw them (frontend/ducky_sync.py).
-- A chat lives on the Ducky it was started on (its home: its agent runs there, with that
-- computer's tools); every other Ducky of the account keeps a read-only copy here, pulled
-- peer to peer through the sealed link while both are online. The site keeps none of it.
-- account_id: the signed-in account the copy belongs to (another account never sees it).
-- ducky: the home Ducky's key id. updated: the home's own updated time for the chat.
-- rows: its newest chat rows (load_messages); rows_of: the home's updated time those rows
-- are of (a failed pull is tried again); synced: when they were pulled here. gone: the
-- home no longer lists the chat; the copy stays, out of the lists.
CREATE TABLE IF NOT EXISTS ducky_mirror_chats (
  account_id TEXT NOT NULL,
  ducky      TEXT NOT NULL,
  conv_id    TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT '',
  updated    REAL NOT NULL DEFAULT 0,
  rows       TEXT NOT NULL DEFAULT '[]',
  rows_of    REAL NOT NULL DEFAULT -1,
  synced     REAL NOT NULL DEFAULT 0,
  gone       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, ducky, conv_id)
);

-- The other Duckies this one has synced with: its name then, and when.
CREATE TABLE IF NOT EXISTS ducky_mirror_peers (
  account_id TEXT NOT NULL,
  ducky      TEXT NOT NULL,
  name       TEXT NOT NULL DEFAULT '',
  synced     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, ducky)
);
