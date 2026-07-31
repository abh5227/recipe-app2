-- 026_cook_photos_cook_log_nullable.sql
-- Stage 4 build 2a: a cook photo may be attached to a cook OR stand ALONE in the album (no cook / no date),
-- so cook_photos.cook_log_id must become NULLABLE — it shipped NOT NULL in migration 025 (commit 86b353d).
-- SQLite can't ALTER a column to drop NOT NULL, so rebuild the standard way (the 019_ratings_composite_pk /
-- 005_cascade_history pattern): a new table with cook_log_id NULLABLE and the SAME FKs (both ON DELETE
-- CASCADE) and column shape, copy rows carrying id EXPLICITLY (empty today — nothing has been inserted; the
-- endpoints are build 2b), drop, rename, recreate the two indexes. Nothing FKs INTO cook_photos, so this is
-- safe with foreign keys ON. Never edit a shipped migration — this is the additive follow-up. The Alembic
-- revision mirrors it for Postgres with a trivial in-place ALTER COLUMN ... DROP NOT NULL (no rebuild).

CREATE TABLE cook_photos_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cook_log_id INTEGER          REFERENCES cook_log(id) ON DELETE CASCADE,   -- now NULLABLE: standalone album photo
    recipe_id   TEXT    NOT NULL REFERENCES recipes(id)  ON DELETE CASCADE,   -- denormalized (TEXT = recipes.id)
    user_id     INTEGER NOT NULL REFERENCES users(id),                        -- who added it (reference FK, no cascade)
    path        TEXT    NOT NULL,                                             -- stored image path
    caption     TEXT,                                                         -- optional (<=100 chars, app-enforced later)
    added_at    TEXT    NOT NULL                                              -- now_utc(): when the photo was added
);
INSERT INTO cook_photos_new (id, cook_log_id, recipe_id, user_id, path, caption, added_at)
    SELECT id, cook_log_id, recipe_id, user_id, path, caption, added_at FROM cook_photos;
DROP TABLE cook_photos;
ALTER TABLE cook_photos_new RENAME TO cook_photos;

CREATE INDEX idx_cook_photos_recipe   ON cook_photos(recipe_id);    -- per-recipe album: all photos across this recipe's cooks
CREATE INDEX idx_cook_photos_cook_log ON cook_photos(cook_log_id);  -- per-cook lookup: this cook's photos
