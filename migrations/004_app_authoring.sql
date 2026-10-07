-- 004_app_authoring.sql
-- Recipes can now be created and edited in the app, not only seeded from seed.py.
-- A recipe is therefore "owned" by one of two sources, and the app needs to tell
-- them apart: seed recipes are read-only in the app; app recipes are fully editable.
--
-- This also adds storage for "your changes" to a seed recipe — per-ingredient-line
-- overrides that leave the cookbook original intact and are shown on demand.

-- Where a recipe came from: 'seed' (from seed.py, read-only in the app) or 'app'
-- (created in the app, editable). Every existing recipe is a seed recipe.
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

ALTER TABLE recipes ADD COLUMN source TEXT NOT NULL DEFAULT 'seed';

-- Your per-line changes to a seed recipe's ingredients, keyed by the line's
-- position. The original line is never modified. Like ratings and cook history,
-- this is data you create in the app, so a rebuild must NEVER wipe it.
CREATE TABLE ingredient_overrides (
    recipe_id TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    override  TEXT    NOT NULL,
    PRIMARY KEY (recipe_id, position)
);

COMMIT;
