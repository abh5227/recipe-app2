-- 005_cascade_history.sql
-- Make deleting a recipe automatically remove its cook history and rating.
--
-- cook_log and ratings reference recipes(id) but didn't say what to do when a
-- recipe is deleted, so removing a recipe meant deleting those rows by hand first.
-- SQLite can't change a foreign key in place, so each table is rebuilt the standard
-- way: make a new table with the rule, copy the rows over, drop the old one, rename.
-- Nothing else references these two tables, so this is safe with foreign keys on.

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
