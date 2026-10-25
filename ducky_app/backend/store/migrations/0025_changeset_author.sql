-- 0025: a live group's leader sends its groupmates' changes for them (they never push while
-- it is in reach), so a changeset names who made it when that isn't this PC's person: their
-- name and their PC's name. The commit itself is the leader's. '' for this PC's own changes.
ALTER TABLE space_changesets ADD COLUMN author TEXT NOT NULL DEFAULT '';
ALTER TABLE space_changesets ADD COLUMN author_pc TEXT NOT NULL DEFAULT '';
