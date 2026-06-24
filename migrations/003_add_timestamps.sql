-- 003_add_timestamps.sql
-- Record when a recipe or ingredient was first added. Once a row exists without
-- this, the information is gone for good, so it's worth adding while the project
-- is small even though we don't display it yet.
--
-- Note: SQLite's ALTER TABLE ADD COLUMN can't use a dynamic default like
-- datetime('now'), so the column is plain TEXT and build_db.py fills it in
-- (preserving the original value across rebuilds — see seed_content there).

ALTER TABLE recipes     ADD COLUMN created_at TEXT;
ALTER TABLE ingredients ADD COLUMN created_at TEXT;
