-- 002_cooking_features.sql
-- Your first data that is NOT derived from seed.py: ratings you set and a log of
-- times you've cooked each recipe. This is the data a full rebuild must never wipe,
-- which is the whole reason migrations exist.

-- One row per time you cook something. The "number of times cooked" is just
-- COUNT(*) of these rows, and "last cooked" is MAX(cooked_on) — both derived,
-- so they can never drift out of sync with reality.
CREATE TABLE cook_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT NOT NULL REFERENCES recipes(id),
    cooked_on TEXT NOT NULL DEFAULT (date('now'))
);

-- Your rating for a recipe: one current value each, 1-5 stars.
CREATE TABLE ratings (
    recipe_id TEXT PRIMARY KEY REFERENCES recipes(id),
    rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rated_on  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_cook_log_recipe ON cook_log(recipe_id);
