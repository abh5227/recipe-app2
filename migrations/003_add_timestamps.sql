-- 003_add_timestamps.sql
-- Record when a recipe or ingredient was first added. Once a row exists without
-- this, the information is gone for good, so it's worth adding while the project
-- is small even though we don't display it yet.
--
-- Note: SQLite's ALTER TABLE ADD COLUMN can't use a dynamic default like
-- datetime('now'), so the column is plain TEXT and build_db.py fills it in
-- (preserving the original value across rebuilds — see seed_content there).
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-08, in the same shape as the seven wrapped
-- on 2026-10-07 and for the same reason. These six were MISSED by that round: the rule that was
-- meant to find them split the file on ";" and dropped any fragment beginning with "--", and every
-- statement in this folder has a comment above it, so the rule counted 0 or 1 statements here and
-- reported nothing missing. Found by an independent review. See tests/test_migration_atomicity.py,
-- which now strips the comments before it counts.
-- Every database past this file is unaffected (migrate.py tracks by filename and never by
-- checksum), so this protects a FRESH INSTALL, which is the only thing that still runs it.
BEGIN;

ALTER TABLE recipes     ADD COLUMN created_at TEXT;
ALTER TABLE ingredients ADD COLUMN created_at TEXT;

COMMIT;
