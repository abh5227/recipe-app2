-- 013: per-ingredient "convert to grams in Metric?" flag.
--
-- TRUE (the default) for weigh-it staples: flours & starches, sugars & syrups, butter,
-- soft dairy / pastes, nuts & seeds, grated cheese, pourable liquids, chocolate, oats,
-- dried fruit. FALSE for raw produce / aromatics and pure cooking oils & solid fats, where
-- a volume reads far more naturally in the kitchen than a gram weight (you scoop a clove or
-- pour a glug; you don't weigh it). build_db.seed_weights sets the per-row value from the
-- King Arthur CSV; this migration only adds the column with a safe TRUE default so existing
-- rows keep converting until a rebuild repopulates them.
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-07. Every database past this file is
-- unaffected (migrate.py tracks by filename and never by checksum), so this protects a FRESH
-- INSTALL, which is the only thing that still runs it. See tests/test_migration_atomicity.py.
BEGIN;

ALTER TABLE ingredient_weights ADD COLUMN convert_to_grams INTEGER NOT NULL DEFAULT 1;

COMMIT;
