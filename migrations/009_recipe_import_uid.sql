-- 009_recipe_import_uid.sql
-- Phase 15 (recipe import) gives recipes two identity columns so an imported recipe
-- can be DEDUPED against what's already here and traced back to its source:
--
--   uid  — the source's stable unique id (Paprika's per-recipe UID). This is the
--          DEDUP key: re-importing the same export skips recipes whose uid we already
--          have. It is NOT the primary key — recipes.id stays the human-readable slug
--          that every child row (ingredients, steps, ratings, ...) references.
--   hash — the source's content hash (Paprika's `hash`), for later spotting that an
--          already-imported recipe changed upstream. Stored now; not yet used.
--
-- The 5 seed recipes are tagged with their matched Paprika uids (in seed.py /
-- build_db.py) so importing the native archive SKIPS their twins instead of creating
-- duplicates. Seed recipes carry uid but not hash (they aren't hash-deduped).
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-07. Every database past this file is
-- unaffected (migrate.py tracks by filename and never by checksum), so this protects a FRESH
-- INSTALL, which is the only thing that still runs it. See tests/test_migration_atomicity.py.
BEGIN;

ALTER TABLE recipes ADD COLUMN uid  TEXT;
ALTER TABLE recipes ADD COLUMN hash TEXT;

-- uid must be unique WHEN PRESENT. A partial unique index (WHERE uid IS NOT NULL) lets
-- the many app-authored recipes keep a NULL uid while guaranteeing two recipes can
-- never claim the same source uid — the guard that makes uid-dedup safe.
CREATE UNIQUE INDEX idx_recipes_uid ON recipes(uid) WHERE uid IS NOT NULL;

COMMIT;
