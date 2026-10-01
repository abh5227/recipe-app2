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

-- ⚠️ THIS FILE IS A TABLE REBUILD AND IT HAS TO BE ONE TRANSACTION. migrate.py runs each file
-- through sqlite3's executescript, which opens no transaction, so without the BEGIN below every
-- statement here auto-commits on its own and a run interrupted part way leaves the schema half
-- rebuilt. SQLite DDL is transactional, which is what makes the one-word fix work. The same
-- reasoning, and the measurement behind it, is written out at length in 056_wait_alongside.sql.
--
-- Measured by replaying this file truncated one statement after the DROP and closing the connection, which is what a
-- Ctrl-C, a laptop sleep or a crash does:
--
--   no transaction : ratings is GONE and ratings_new is left behind. Every rating read and the
--                    cook-gated star control 500s, the filename was never recorded, and the retry
--                    dies forever on "table ratings_new already exists".
--   this BEGIN     : the rebuild rolls back whole, ratings keeps its rows and its original
--                    rated_on timestamps, and re-running migrate.py applies it cleanly.
--
-- ⚠️ Do NOT lift this into migrate.py as a blanket wrap. A PRAGMA foreign_keys is a NO-OP inside a
-- transaction, and 045 sets it off and back on, so wrapping every file centrally would silently
-- disarm that one. Each rebuild carries its own BEGIN, and 045 keeps its pragmas OUTSIDE it.
BEGIN;

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

COMMIT;
