-- 005_cascade_history.sql
-- Make deleting a recipe automatically remove its cook history and rating.
--
-- cook_log and ratings reference recipes(id) but didn't say what to do when a
-- recipe is deleted, so removing a recipe meant deleting those rows by hand first.
-- SQLite can't change a foreign key in place, so each table is rebuilt the standard
-- way: make a new table with the rule, copy the rows over, drop the old one, rename.
-- Nothing else references these two tables, so this is safe with foreign keys on.

-- ⚠️ THIS FILE IS A TABLE REBUILD AND IT HAS TO BE ONE TRANSACTION. migrate.py runs each file
-- through sqlite3's executescript, which opens no transaction, so without the BEGIN below every
-- statement here auto-commits on its own and a run interrupted part way leaves the schema half
-- rebuilt. SQLite DDL is transactional, which is what makes the one-word fix work. The same
-- reasoning, and the measurement behind it, is written out at length in 056_wait_alongside.sql.
--
-- Measured by replaying this file truncated one statement after the first DROP and closing the connection, which is what a
-- Ctrl-C, a laptop sleep or a crash does:
--
--   no transaction : cook_log is GONE and cook_log_new is left behind, so every cook-history read
--                    500s. The filename was never recorded, so migrate.py retries and the retry
--                    dies forever on "table cook_log_new already exists". Recovery is hand SQL.
--                    Truncated instead before the CREATE INDEX, it is worse than an error: the
--                    rebuild LOOKS complete, idx_cook_log_recipe is simply gone, and the name IS
--                    recorded, so nothing ever re-applies it.
--   this BEGIN     : both rebuilds roll back together, cook_log and ratings are untouched, and
--                    re-running migrate.py applies the file cleanly.
--
-- ⚠️ Do NOT lift this into migrate.py as a blanket wrap. A PRAGMA foreign_keys is a NO-OP inside a
-- transaction, and 045 sets it off and back on, so wrapping every file centrally would silently
-- disarm that one. Each rebuild carries its own BEGIN, and 045 keeps its pragmas OUTSIDE it.
BEGIN;

CREATE TABLE cook_log_new (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    cooked_on TEXT NOT NULL DEFAULT (date('now'))
);
INSERT INTO cook_log_new (id, recipe_id, cooked_on)
    SELECT id, recipe_id, cooked_on FROM cook_log;
DROP TABLE cook_log;
ALTER TABLE cook_log_new RENAME TO cook_log;
CREATE INDEX idx_cook_log_recipe ON cook_log(recipe_id);

CREATE TABLE ratings_new (
    recipe_id TEXT PRIMARY KEY REFERENCES recipes(id) ON DELETE CASCADE,
    rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rated_on  TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO ratings_new (recipe_id, rating, rated_on)
    SELECT recipe_id, rating, rated_on FROM ratings;
DROP TABLE ratings;
ALTER TABLE ratings_new RENAME TO ratings;

COMMIT;
