-- 0024: chats and duckies belong to the Ducky account signed in on this PC, the way plugin
-- data does (migration 0009). account_id is scopes.account_id() of the owner ('_local'
-- signed out); the repos read and write only the current account's rows, and what the
-- person wrote is sealed for that account (backend/store/account_rows.py). Rows from
-- before get '' here and go whole to the first account that opens them (the one signed
-- in now, else '_local'), then are sealed in place. Nothing is deleted.

-- What the copies below free is zeroed, so the old plaintext doesn't stay in the file.
PRAGMA secure_delete=ON;

ALTER TABLE conversations ADD COLUMN account_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_conv_account ON conversations(account_id, project_id, sort_order);

-- A message is its chat's; this copy of the owner is filled as rows are written or sealed.
ALTER TABLE messages ADD COLUMN account_id TEXT NOT NULL DEFAULT '';

-- Folder ids repeat across accounts (every project has an "archive" folder), so the key
-- gains the account. Every row is copied across as it is.
CREATE TABLE folders_v24 (
  account_id   TEXT NOT NULL DEFAULT '',
  project_id   TEXT NOT NULL,
  id           TEXT NOT NULL,
  name         TEXT NOT NULL DEFAULT '',
  parent_id    TEXT NOT NULL DEFAULT '',
  sort_order   REAL NOT NULL DEFAULT 0,
  group_hub_id TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (account_id, project_id, id)
);
INSERT INTO folders_v24(account_id, project_id, id, name, parent_id, sort_order, group_hub_id)
  SELECT '', project_id, id, name, parent_id, sort_order, group_hub_id FROM folders;
DROP TABLE folders;
ALTER TABLE folders_v24 RENAME TO folders;

-- The duckies table is never rebuilt: its rows stay where they are. ducky_id is the
-- ducky's id; id is now only the row key (the ducky id on rows from before,
-- '<account>~<ducky id>' on new ones), so two accounts can each edit one shipped ducky.
ALTER TABLE duckies ADD COLUMN account_id TEXT NOT NULL DEFAULT '';
ALTER TABLE duckies ADD COLUMN ducky_id TEXT NOT NULL DEFAULT '';
UPDATE duckies SET ducky_id = id;
CREATE UNIQUE INDEX IF NOT EXISTS ux_duckies_account ON duckies(account_id, ducky_id);

ALTER TABLE duckies_history ADD COLUMN account_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS duckies_history_account ON duckies_history(account_id, id, seq);

PRAGMA secure_delete=OFF;
