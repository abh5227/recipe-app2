-- 049_plan_ahead_waits.sql - the plan-ahead wait, and storage, as their own rows.
--
-- ⚠️ TWO TABLES, NOT COLUMNS ON recipes, because a recipe really does have SEVERAL waits.
--    pepperoni-rolls rises twice, morning-buns chills four times, and brioche has a room-temperature
--    proof and an 8 to 12 hour cold one. A single pair of columns would have to pick one and throw
--    the rest away, and the page is supposed to show the total AND the breakdown.
--
-- ⚠️ A WAIT IS NOT STORAGE AND THE TWO NEVER MIX. "keeps, refrigerated, up to 1 week" is not
--    something to plan around, it is what to do with the leftovers. Measured on the corpus before
--    this was written: 8 of the 32 excluded candidates were storage claims, and every one of them
--    would have been read as a week-long wait. They get their own table, their own row on the page,
--    and they never reach a total or a filter.
--
-- ⚠️ THE EXTENSION IS SEPARATE FROM THE RANGE AND MUST NEVER WIDEN IT. A recipe says "marinate 10
--    minutes to an hour (or overnight if time allows)". The normal range is 10 to 60. Overnight is
--    an INVITATION, not the upper bound, and folding it in would tell a cook to allow 8 hours for a
--    10-minute marinade. It runs the other way too: chocolate-chip-cookies says at least 12 hours
--    "(if you're pressed for time, a couple of hours in the refrigerator will do)", which is a
--    SHORTER extension. One nullable label plus its own min and max holds both directions.
--
-- ⚠️ `where` IS A RESERVED WORD, so the storage column is `where_kept`. The alternative is quoting
--    an identifier in every statement in two dialects.
--
-- ⚠️ min_minutes AND max_minutes ARE BOTH NULLABLE, and the two nulls mean different things.
--    A null max is OPEN-ENDED ("2 hr+", "at least overnight"), which is 45 of the 72 proposals.
--    A null min is text the time reader could not parse, kept as words with no number behind it.
--
-- ⚠️ NOTHING HERE IS DERIVED FROM STEP TEXT AT RUN TIME. step_position records WHICH step a wait was
--    read from, for a human following it back. Editing that step does not update the wait, exactly
--    as editing a step does not update prep_time.

CREATE TABLE recipe_waits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id       TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,           -- order on the page, 0-based
    kind            TEXT    NOT NULL,
    label           TEXT    NOT NULL,           -- what the cook reads: "1 hr rise", "overnight"
    min_minutes     INTEGER,                    -- NULL = the text carried no number
    max_minutes     INTEGER,                    -- NULL = open-ended
    step_position   INTEGER,                    -- the step it was read from, provenance only
    ext_label       TEXT,                       -- "or overnight if time allows"
    ext_min_minutes INTEGER,
    ext_max_minutes INTEGER,
    CHECK (kind IN ('marinating','chilling','rising','soaking','resting','freezing','brining','other')),
    CHECK (min_minutes IS NULL OR min_minutes >= 0),
    CHECK (max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes),
    CHECK (ext_max_minutes IS NULL OR ext_min_minutes IS NULL OR ext_max_minutes >= ext_min_minutes),
    CHECK (ext_label IS NOT NULL OR (ext_min_minutes IS NULL AND ext_max_minutes IS NULL)),
    UNIQUE (recipe_id, position)
);

CREATE INDEX idx_recipe_waits_recipe ON recipe_waits(recipe_id);
CREATE INDEX idx_recipe_waits_min    ON recipe_waits(min_minutes);

CREATE TABLE recipe_storage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id    TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    where_kept   TEXT    NOT NULL,              -- fridge | freezer | room temp | other
    applies_to   TEXT,                          -- "the dough", "the baked cookies". NULL = the dish
    label        TEXT    NOT NULL,              -- "up to 1 week"
    min_minutes  INTEGER,
    max_minutes  INTEGER,
    CHECK (where_kept IN ('fridge','freezer','room temp','other')),
    CHECK (min_minutes IS NULL OR min_minutes >= 0),
    CHECK (max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes),
    UNIQUE (recipe_id, position)
);

CREATE INDEX idx_recipe_storage_recipe ON recipe_storage(recipe_id);
