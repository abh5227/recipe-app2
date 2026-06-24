-- 006_people_and_changes.sql
-- Replaces the single anonymous "my changes" note per line with per-person change
-- layers: several people (you, a friend) can each keep their own version of a seed
-- recipe, and the app can show the original, any one person's version, or everyone
-- compared. Each person has a display colour; their changes render in that colour.
--
-- A change is one of three things, split across two tables so each column is always
-- meaningful (no "this only applies when kind = X" guesswork):
--   * a change to an EXISTING line   -> recipe_line_changes  (a new quantity, or a removal)
--   * a NEW line a person adds        -> recipe_additions
-- The people themselves are configuration, seeded from seed.py. The changes are your
-- data, created in the app — so, like ratings, a rebuild never wipes them.

-- The previous single-note system is superseded and nothing else references it.
DROP TABLE IF EXISTS ingredient_overrides;

-- Who can have a version of a recipe. Seeded from seed.py: id, display name, colour.
CREATE TABLE people (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    color    TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0      -- display order in the view switcher
);

-- A person's change to an EXISTING ingredient line of a seed recipe: either a new
-- quantity (kind = 'edit', new_qty set) or a removal (kind = 'remove'). At most one
-- change per (recipe, person, line), so the primary key is all three together.
CREATE TABLE recipe_line_changes (
    recipe_id TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    person_id TEXT    NOT NULL REFERENCES people(id)  ON DELETE CASCADE,
    position  INTEGER NOT NULL,                       -- which original ingredient line
    kind      TEXT    NOT NULL CHECK (kind IN ('edit', 'remove')),
    new_qty   TEXT,                                   -- the replacement quantity when kind = 'edit'
    PRIMARY KEY (recipe_id, person_id, position)
);

-- A brand-new ingredient a person adds to a seed recipe (shown at the bottom of the
-- list, in their colour). Linked to a library ingredient when ingredient_id is set;
-- otherwise it's plain text held in raw_text.
CREATE TABLE recipe_additions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id     TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    person_id     TEXT NOT NULL REFERENCES people(id)  ON DELETE CASCADE,
    qty           TEXT,
    ingredient_id TEXT REFERENCES ingredients(id),    -- set when linked to the library
    label         TEXT,                               -- display text for a linked ingredient
    note          TEXT,
    raw_text      TEXT                                -- plain-text rendering of the whole line
);

CREATE INDEX idx_line_changes_recipe ON recipe_line_changes(recipe_id);
CREATE INDEX idx_additions_recipe    ON recipe_additions(recipe_id);
