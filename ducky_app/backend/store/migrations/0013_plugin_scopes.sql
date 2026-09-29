-- 0013: where a plugin's data lives is picked per plugin (plan §15.1), no longer per
-- project: Local (scope 'personal') or exactly one team. Each plugin that already has
-- data in a team some project was linked to keeps showing that team's copy.

CREATE TABLE IF NOT EXISTS plugin_scopes (
  account_id TEXT NOT NULL,
  plugin_id  TEXT NOT NULL,
  scope_id   TEXT NOT NULL,
  updated    REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, plugin_id)
);

-- A replay of this file (tests rewind user_version) finds project_scopes already gone.
CREATE TABLE IF NOT EXISTS project_scopes (
  account_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  scope_id   TEXT NOT NULL,
  updated    REAL NOT NULL,
  PRIMARY KEY (account_id, project_id)
);

INSERT OR IGNORE INTO plugin_scopes(account_id, plugin_id, scope_id, updated)
  SELECT DISTINCT d.account_id, d.plugin_id, d.scope_id, p.updated
  FROM plugin_data d
  JOIN project_scopes p ON p.account_id = d.account_id AND p.scope_id = d.scope_id
  WHERE d.plugin_id NOT LIKE 'ducky.%';

DROP TABLE project_scopes;
