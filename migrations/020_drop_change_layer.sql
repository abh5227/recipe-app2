-- 020_drop_change_layer.sql
-- Rescoping R6 (consideration #5): DROP the vestigial change-layer. recipe_line_changes /
-- recipe_additions were the per-person overlay on read-only SEED recipes (edit a line / add an
-- ingredient without owning the recipe); the box model makes recipes owned + directly editable
-- (update_recipe rewrites lines/steps) and copy=duplicate-into-your-box, so the overlay is redundant.
-- It was gated to source='seed' (0 such recipes in production) and both tables are EMPTY — 0 rows lost.
-- The people table (the andy/vedant display-switcher) goes too: the box model has no "switch person",
-- it's just you. The source='seed' TIER stays (read-only recipes); only the change-LAYER is removed.
--
-- Drop ORDER matters: the two change tables FK to people (ON DELETE CASCADE), so drop them BEFORE
-- people or the FK blocks the people drop (with foreign_keys ON). The Alembic revision mirrors this.

DROP TABLE IF EXISTS recipe_line_changes;
DROP TABLE IF EXISTS recipe_additions;
DROP TABLE IF EXISTS people;
