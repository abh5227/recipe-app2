-- 024_recipe_queue.sql
-- Want-to-make queue (docs/product-vision.md forward-looking primitive): promote the latent, GLOBAL
-- "To Make" category tag into PER-USER planning state. A queue is "I want to make this" — per-user, so
-- it CANNOT live on the recipe row; it's a per-user join, the only shape that generalizes to the friend
-- graph (each user has their own queue over the shared recipe corpus). One row = "user U wants to make
-- recipe R". user_id -> users(id) with NO ondelete (matching owner/user_id/created_by and shared_posts'
-- sharer column); recipe_id -> recipes(id) ON DELETE CASCADE so a deleted recipe can never leave an
-- orphan queue row (mirrors shared_posts' recipe_id target-cascade — the same no-orphan integrity need).
-- recipe_id is TEXT to match recipes.id (TEXT). added_at = now_utc() text, set in code (the auth-1 /
-- shared_posts pattern that avoids the SQLite datetime('now') vs Postgres default-expression divergence).
-- UNIQUE(user_id, recipe_id): a recipe is in your queue once or not at all (re-queuing is a no-op, not a
-- duplicate). Surrogate id PK (a queue entry is a first-class row; the UNIQUE carries the dedup). Schema
-- is purely ADDITIVE here — this migration only creates the empty table; the 133 latent "To Make" tags
-- are moved into it by the STANDALONE backfill (scripts/backfill_recipe_queue.py), because migrate.py
-- runs executescript and cannot do the ·-element category strip. SQLite half of the dual schema source;
-- an Alembic revision mirrors it for Postgres.

CREATE TABLE recipe_queue (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id),                 -- whose queue this entry is in
    recipe_id TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,  -- the wanted recipe (TEXT = recipes.id)
    added_at  TEXT    NOT NULL,                                       -- now_utc(): when it entered the queue
    UNIQUE (user_id, recipe_id)                                       -- in your queue once, or not at all
);
