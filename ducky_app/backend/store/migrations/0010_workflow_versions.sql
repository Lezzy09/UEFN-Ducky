CREATE TABLE workflow_versions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    saved_at REAL NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE INDEX workflow_versions_by_workflow ON workflow_versions(workflow_id, sequence DESC);
