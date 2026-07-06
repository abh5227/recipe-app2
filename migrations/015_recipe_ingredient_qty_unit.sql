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
ALTER TABLE recipe_ingredients ADD COLUMN quantity TEXT;
ALTER TABLE recipe_ingredients ADD COLUMN unit TEXT;
