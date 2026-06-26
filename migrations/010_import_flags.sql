-- 010_import_flags.sql
-- The import REVIEW QUEUE. Phase 15 imports every recipe — but it FLAGS anything it
-- couldn't confidently structure (decline-over-guess) instead of dropping or mis-parsing
-- it. Those flags land here so they're queryable later ("what needs a human look?").
--
-- Two kinds of flag share one table, told apart by `position`:
--   - line-level  (position = the ingredient line's position): 'multiplier', 'each_multi',
--     'ambiguous_section', 'grams_declined' — the line is still WRITTEN to
--     recipe_ingredients (raw_text preserved); this row just marks it for review.
--   - recipe-level (position IS NULL): 'no_ingredients', 'no_directions', 'photo_only' —
--     an incomplete recipe that was imported anyway.
--
-- Kept OUT of recipes/recipe_ingredients so the app's rendering schema stays clean and a
-- single SELECT is the whole queue. It's app-owned data (written at import, never rebuilt
-- by build_db) and cascades away with its recipe. JOIN recipe_ingredients on
-- (recipe_id, position) to see a flagged line's original text.
CREATE TABLE import_flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id  TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position   INTEGER,            -- ingredient-line position; NULL = recipe-level flag
    flag       TEXT    NOT NULL,   -- e.g. 'multiplier', 'grams_declined', 'no_directions'
    reason     TEXT,               -- human hint (the line's flag_reason; NULL for recipe-level)
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_import_flags_recipe ON import_flags(recipe_id);
