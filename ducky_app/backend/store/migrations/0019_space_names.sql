-- 0019: generic names for shared-space bookkeeping. scope_sync keys its rows by space
-- id; the per-space meta row says whether this account may change the space's
-- workflows and names the space's web page.

ALTER TABLE scope_sync RENAME COLUMN team_id TO space_id;
ALTER TABLE team_perms RENAME TO space_meta;
ALTER TABLE space_meta RENAME COLUMN team_id TO space_id;
ALTER TABLE space_meta RENAME COLUMN manage_automations TO workflows_writable;
ALTER TABLE space_meta RENAME COLUMN slug TO web_slug;
