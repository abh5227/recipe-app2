-- 004_app_authoring.sql
-- Recipes can now be created and edited in the app, not only seeded from seed.py.
-- A recipe is therefore "owned" by one of two sources, and the app needs to tell
-- them apart: seed recipes are read-only in the app; app recipes are fully editable.
--
-- This also adds storage for "your changes" to a seed recipe — per-ingredient-line
-- overrides that leave the cookbook original intact and are shown on demand.

-- Where a recipe came from: 'seed' (from seed.py, read-only in the app) or 'app'
-- (created in the app, editable). Every existing recipe is a seed recipe.
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
