-- 0020: why a shared row hasn't gone out yet. sync_state is '' (queued), refused (the
-- server said no; sync_error says why), blocked (it kept failing on this PC), conflict
-- or locked_out. attempts/next_try back off a row that keeps failing so it never holds
-- up newer changes. The partial index serves the queue reads (dirty rows only).

ALTER TABLE plugin_data ADD COLUMN sync_state TEXT NOT NULL DEFAULT '';
ALTER TABLE plugin_data ADD COLUMN sync_error TEXT NOT NULL DEFAULT '';
ALTER TABLE plugin_data ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plugin_data ADD COLUMN next_try REAL NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS plugin_data_dirty ON plugin_data(account_id, scope_id) WHERE dirty=1;

-- A dropped change the team still has comes back on the next pull: the space's cursor
-- goes back to its rev (rewind_rev) and stays at most there until a round that started
-- after the drop (rewind_at) writes it.
ALTER TABLE scope_sync ADD COLUMN rewind_rev INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scope_sync ADD COLUMN rewind_at REAL NOT NULL DEFAULT 0;

-- Until now a plugin linked to a space the provider couldn't use read and wrote its Local
-- copy. Such a space now stays on screen read-only, so links already in that state go:
-- those plugins keep the Local data they have been using.
DELETE FROM plugin_scopes WHERE EXISTS (
  SELECT 1 FROM scope_sync s
  WHERE s.account_id = plugin_scopes.account_id AND s.space_id = plugin_scopes.scope_id AND s.state = 'unavailable'
);
