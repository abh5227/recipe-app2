-- 025_cook_photos.sql
-- Cook-photo ALBUM (Stage 4, build 1 — schema foundation): several photos per cook, one row per photo,
-- accumulating into a per-recipe album BESIDE the single hero (recipes.image is untouched). One row =
-- "this photo belongs to cook_log C (recipe R), added by user U". cook_log_id -> cook_log(id) ON DELETE
-- CASCADE so undoing a cook / deleting a recipe (which cascades cook_log) leaves no orphan photo rows —
-- the shared_posts.cook_log_id idiom. recipe_id -> recipes(id) ON DELETE CASCADE is DENORMALIZED (a cook
-- already carries the recipe), carried so the common "all photos for this recipe" album query is a single
-- indexed WHERE recipe_id = ? instead of a join through cook_log; its own cascade keeps it consistent.
-- recipe_id is TEXT to match recipes.id (TEXT). user_id -> users(id) with NO ondelete (reference FK,
-- matching owner/cook_log.user_id/recipe_queue.user_id) — the interim multi-user-shaped rule: present
-- from day one though single-user now, set to current_user at insert (build 2), so no rescoping debt.
-- path is the stored image path (e.g. 'images/cooks/<photo_id>.jpg'), written by build 2's save_cook_photo
-- helper — just the column here. caption is optional (nullable; ~100-char cap enforced later in build 2/UI).
-- added_at = now_utc() text, set in code (the recipe_queue / shared_posts pattern that avoids the SQLite
-- datetime('now') vs Postgres default-expression divergence). Surrogate id PK (a photo is a first-class
-- row; no natural key — several photos per cook, repeats allowed). Indexes back both query patterns:
-- per-recipe album (recipe_id) and per-cook lookup (cook_log_id). Purely ADDITIVE — this migration only
-- creates the empty table + indexes; NO change to cook_log or recipes, and NO data backfill (a new table
-- starts empty). SQLite half of the dual schema source; an Alembic revision mirrors it for Postgres.

CREATE TABLE cook_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cook_log_id INTEGER NOT NULL REFERENCES cook_log(id) ON DELETE CASCADE,   -- the cook this photo belongs to
    recipe_id   TEXT    NOT NULL REFERENCES recipes(id)  ON DELETE CASCADE,   -- denormalized (TEXT = recipes.id)
    user_id     INTEGER NOT NULL REFERENCES users(id),                        -- who added it (reference FK, no cascade)
    path        TEXT    NOT NULL,                                             -- stored image path (build 2 fills it)
    caption     TEXT,                                                         -- optional (<=100 chars, app-enforced later)
    added_at    TEXT    NOT NULL                                              -- now_utc(): when the photo was added
);

CREATE INDEX idx_cook_photos_recipe   ON cook_photos(recipe_id);    -- per-recipe album: all photos across this recipe's cooks
CREATE INDEX idx_cook_photos_cook_log ON cook_photos(cook_log_id);  -- per-cook lookup: this cook's photos
