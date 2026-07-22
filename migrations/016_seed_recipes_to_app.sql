-- 016_seed_recipes_to_app.sql
-- Convert the 5 original "seed" example recipes into ordinary EDITABLE app recipes, in lockstep with
-- emptying seed.py's RECIPES (same change). Together these make build_db stop reverting them: with
-- source='app' they're skipped by seed_content's remove-step (which only touches source='seed'), and
-- with no dict in RECIPES they're skipped by the upsert-step — the DB becomes their source of truth.
-- Proven rebuild-safe on a copy (two rebuilds; count stable at 302, seed=0; a canary step-edit
-- survived) and the test suite is decoupled from seed content (green with RECIPES=[]) before applying.
--
-- MUST land together with the seed.py edit: on its own the next build_db upserts them back to
-- source='seed'; with seed.py edited but this NOT applied the next build_db DELETEs them. Lockstep.

UPDATE recipes SET source = 'app'
WHERE id IN ('aloo-gobhi', 'bulgogi-bowls', 'gai-yang', 'mussakhan', 'no-knead-bread');

-- bulgogi-bowls carried 3 concept-only per-person rows (the change layer is seed-only; on an app
-- recipe it's inert). Recipe-scoped deletes hit exactly those rows (verified = 1 line-change + 2
-- additions; bulgogi-bowls is the only recipe with any per-person rows).
DELETE FROM recipe_line_changes WHERE recipe_id = 'bulgogi-bowls';
DELETE FROM recipe_additions    WHERE recipe_id = 'bulgogi-bowls';
