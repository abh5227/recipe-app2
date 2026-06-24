-- 001_initial_schema.sql
-- The content tables — everything derived from seed.py. This is the schema you
-- already had; it's now "migration 1" so the database is built up by migrations
-- in order rather than from one schema.sql file.
-- (No PRAGMA here — the migration runner sets foreign_keys on the connection.)

CREATE TABLE ingredients (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    descr TEXT,
    pairs TEXT
);

CREATE TABLE ingredient_seasons (
    ingredient_id TEXT    NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    month         INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    PRIMARY KEY (ingredient_id, month)
);

CREATE TABLE regions (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE ingredient_regions (
    ingredient_id TEXT    NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    region_id     INTEGER NOT NULL REFERENCES regions(id),
    position      INTEGER NOT NULL,
    PRIMARY KEY (ingredient_id, region_id)
);

CREATE TABLE recipes (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    author     TEXT,
    source_url TEXT,
    category   TEXT,
    servings   TEXT,
    prep_time  TEXT,
    cook_time  TEXT,
    total_time TEXT,
    descr      TEXT,
    notes      TEXT,
    image      TEXT
);

CREATE TABLE recipe_ingredients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id     TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    is_heading    INTEGER NOT NULL DEFAULT 0,
    qty           TEXT,
    ingredient_id TEXT REFERENCES ingredients(id),
    label         TEXT,
    note          TEXT,
    raw_text      TEXT
);

CREATE TABLE recipe_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id  TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    is_heading INTEGER NOT NULL DEFAULT 0,
    text       TEXT NOT NULL
);

CREATE INDEX idx_ri_recipe       ON recipe_ingredients(recipe_id);
CREATE INDEX idx_ri_ingredient   ON recipe_ingredients(ingredient_id);
CREATE INDEX idx_rs_recipe       ON recipe_steps(recipe_id);
CREATE INDEX idx_seasons_month   ON ingredient_seasons(month);
CREATE INDEX idx_iregions_region ON ingredient_regions(region_id);
