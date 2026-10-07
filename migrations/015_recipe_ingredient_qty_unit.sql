-- 015_recipe_ingredient_qty_unit.sql
-- Split the single free-text `qty` into structured parts. Historically qty holds the joined
-- amount+unit ("2 tablespoons", "4 cloves", "1 1/2"); these two columns hold the SEAM the import
-- discarded: `quantity` (the amount expression: "2", "1 1/2", "2-3", "4") and `unit`
-- ("tablespoons", "", "cloves"). See import_cleanup.split_qty for the split rule.
--
-- ADDITIVE / CAPTURE ONLY: `qty` stays untouched as the source-of-truth string. Nothing reads
-- these columns for display or scaling yet (the scaler keeps recombining qty as today), so this is
-- non-breaking. Both nullable — heading rows, and the window before backfill, leave them NULL.
--
-- SQL-ONLY (migrate.py runs executescript, which cannot call Python): this migration ONLY adds the
-- columns. The data transform of the 3,300 persistent app rows is a separate Python backfill
-- (scripts/backfill_qty_unit.py), because the split needs parse_amount and can't be done in SQL.
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-07. Every database past this file is
-- unaffected (migrate.py tracks by filename and never by checksum), so this protects a FRESH
-- INSTALL, which is the only thing that still runs it. See tests/test_migration_atomicity.py.
BEGIN;

ALTER TABLE recipe_ingredients ADD COLUMN quantity TEXT;
ALTER TABLE recipe_ingredients ADD COLUMN unit TEXT;

COMMIT;
