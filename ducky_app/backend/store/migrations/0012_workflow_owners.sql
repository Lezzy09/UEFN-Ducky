-- 0012: workflows are docs of the host data service (plugin id 'ducky.automations'),
-- owned by the account's Personal scope ("Local") or a team scope. What never
-- syncs lives here, per account: the run log, last run, and "Run on this PC".
-- Rows of the old 'automations' table are claimed into Personal at runtime (they
-- must be sealed for the account first).

CREATE TABLE IF NOT EXISTS workflow_runtime (
  account_id  TEXT NOT NULL,
  workflow_id TEXT NOT NULL,
  runs        TEXT NOT NULL DEFAULT '',
  last_run    REAL NOT NULL DEFAULT 0,
  run_here    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, workflow_id)
);

-- What the account may do in each team, and the team's web slug, from the last hub
-- snapshot, so the app can show read-only and link to the team without a network call.
CREATE TABLE IF NOT EXISTS team_perms (
  account_id         TEXT NOT NULL,
  team_id            TEXT NOT NULL,
  manage_automations INTEGER NOT NULL DEFAULT 0,
  slug               TEXT NOT NULL DEFAULT '',
  updated            REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, team_id)
);
