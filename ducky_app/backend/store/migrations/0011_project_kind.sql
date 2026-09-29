-- Folder projects: 'uefn' (an island with <Name>.uefnproject) or 'folder' (any other
-- folder). Rows saved before kinds existed were all accepted as islands, so they stay 'uefn'.
ALTER TABLE projects ADD COLUMN kind TEXT NOT NULL DEFAULT 'uefn';
