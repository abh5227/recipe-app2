-- 027_cook_photo_position.sql
-- Stage 4 build 3d-i: a STORED per-recipe album order (Model B). cook_photos.position holds the display
-- order; today's computed order (cooked_on desc, undated last) SEEDS it via a standalone backfill
-- (scripts/backfill_cook_photo_position.py — NOT here: migrate.py runs executescript, which can't do the
-- per-recipe windowed ordering), and once a user drags (3d-ii/iii) position becomes the source of truth.
-- Purely ADDITIVE: a plain ADD COLUMN (nullable) — NO table rebuild (026 rebuilt only because SQLite can't
-- DROP NOT NULL; ADDing a column has no such limit). NO data change IN this migration (the backfill is
-- separate + gated). A composite (recipe_id, position) index backs the album read (WHERE recipe_id = ?
-- ORDER BY position). SQLite half of the dual schema source; an Alembic revision mirrors it for Postgres.

ALTER TABLE cook_photos ADD COLUMN position INTEGER;   -- nullable: the backfill seeds existing rows; the app sets new rows on insert (append)

CREATE INDEX idx_cook_photos_recipe_position ON cook_photos(recipe_id, position);   -- per-recipe album order
