-- 019_ratings_composite_pk.sql
-- Rescoping R3 (docs/product-vision.md): make ratings per-user. The sole PK (recipe_id) allows only one
-- rating per recipe — it must become a composite (recipe_id, user_id) so each user rates independently.
-- SQLite can't ALTER a PK, so rebuild the standard way (the 005_cascade_history.sql pattern): new table
-- with the composite PK + PRESERVED ON DELETE CASCADE on recipe_id, copy rows carrying rated_on
-- EXPLICITLY (so the DEFAULT (datetime('now')) never fires — ratings keep their original timestamps),
-- drop, rename. Nothing FKs INTO ratings, so this is safe with foreign keys on.
--
-- FRESH-BUILD schema source: on a fresh build_db, ratings is empty (0 rows) so the copy is trivial; the
-- point is that the rebuilt table matches the composite-PK schema exactly. The EXISTING recipes.db is
-- migrated instead by scripts/backfill_rescoping.py (data-coupled — it knows the owner account and does
-- the same rebuild), which stamps THIS migration as applied there so build_db doesn't rebuild twice.
-- The Alembic revision mirrors this for Postgres (an in-place DROP/SET NOT NULL/ADD PRIMARY KEY).

CREATE TABLE ratings_new (
    recipe_id TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rated_on  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (recipe_id, user_id)
);
INSERT INTO ratings_new (recipe_id, user_id, rating, rated_on)
    SELECT recipe_id, user_id, rating, rated_on FROM ratings;
DROP TABLE ratings;
ALTER TABLE ratings_new RENAME TO ratings;
