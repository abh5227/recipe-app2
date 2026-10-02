-- 060_recipe_notes.sql - a note is a row, and it can point at a step or an ingredient line.
--
-- ⚠️ ADDITIVE ONLY, AND recipes.notes IS NOT TOUCHED. The column stays, keeps being written as a
--    derived copy, and goes in a later migration once nothing reads it. Additive before the deploy,
--    destructive after, which is the order rule and exactly what 053 and 054 did for the wait
--    pointer.
--
-- ⚠️ ONE PARAGRAPH IS ONE NOTE, MEASURED RATHER THAN CHOSEN. Of the newline runs inside the 95
--    recipes that carry notes, 82 are a blank line and 19 are a single newline INSIDE a paragraph.
--    The split is static/note-blocks.js::noteParagraphs, which the display already uses and the
--    importer already keeps to. 177 paragraphs over 95 recipes.
--
-- ⚠️ THE KIND IS A LOOKUP TABLE WITH A FOREIGN KEY, NOT A CHECK. SQLite cannot add or widen a CHECK
--    without recreating the table, so a sixth kind would be a create-copy-drop-rename on a table
--    holding every note in the database. As a row it is one INSERT. The five rows mirror
--    static/note-kinds.json, which the client and import_cleanup already share, and
--    tests/test_note_kinds_table.py fails if the three ever disagree.
--
-- ⚠️ THE TEXT IS STORED VERBATIM, LABEL AND ALL. 27 of the 177 paragraphs carry a label the kind
--    table does not know ("Blind Bake", "Tomato Bouillon", "Borlotti", "Pekmez"), against 23 that
--    carry one it does. Stripping a label would delete the only thing naming what the note is about,
--    and the display already handles both cases. Storing the kind and keeping the words is what lets
--    the move be byte-faithful, which is what makes the lockstep provable.
--
-- ⚠️ A POINTER, NOT A SNIPPET. Migration 051 gave a wait a step_check text snippet, 053 added a real
--    step_id and 054 dropped the snippet, because the snippet compared the FRONT of the step so
--    rewording a step's opening broke a link nobody meant to touch. Notes start where waits ended up.
--
-- ⚠️ ingredient_row_id IS ADDED NOW AND WRITTEN BY NOTHING. It names a line of THIS recipe
--    (recipe_ingredients), not a library row, because the line is what the note is about and the line
--    already carries its own link to the library. The picker and the marker on the ingredient are a
--    later round. It is here now so that round is a code change with no schema step in its deploy
--    window.
--
-- ⚠️ UNIQUE (recipe_id, position) MEANS A REORDER CANNOT BE WRITTEN STRAIGHT BACK. Two rows swapping
--    collide. The save pushes survivors to negative positions in one pass and into their final
--    places in a second, which is what app._apply_rows already does for waits and storage.

BEGIN;

CREATE TABLE note_kinds (
    kind     TEXT    PRIMARY KEY,
    header   TEXT    NOT NULL,
    position INTEGER NOT NULL
);

INSERT INTO note_kinds (kind, header, position) VALUES
    ('notes',      'Notes',      0),
    ('tips',       'Tips',       1),
    ('storage',    'Storage',    2),
    ('variations', 'Variations', 3),
    ('serving',    'Serving',    4);

CREATE TABLE recipe_notes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id         TEXT    NOT NULL REFERENCES recipes(id)             ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    kind              TEXT    NOT NULL DEFAULT 'notes'
                                       REFERENCES note_kinds(kind),
    text              TEXT    NOT NULL,
    step_id           INTEGER          REFERENCES recipe_steps(id)        ON DELETE SET NULL,
    ingredient_row_id INTEGER          REFERENCES recipe_ingredients(id)  ON DELETE SET NULL,
    CHECK (length(trim(text)) > 0),
    UNIQUE (recipe_id, position)
);

CREATE INDEX idx_recipe_notes_recipe ON recipe_notes (recipe_id, position);
CREATE INDEX idx_recipe_notes_step   ON recipe_notes (step_id);
CREATE INDEX idx_recipe_notes_ing    ON recipe_notes (ingredient_row_id);

-- ⚠️ A STEP MENTIONED IN A NOTE'S OWN WORDS, AS A REFERENCE RATHER THAN A FROZEN NUMBER.
--    "proceed with step 9" has to keep meaning the right step after the steps move, so what is
--    stored is the step's ID and WHICH mention in the text it belongs to. ref_index is the ordinal
--    of the mention within the note, counting matches of the shared pattern, so the text stays
--    verbatim and the number on the page is always resolved from the step's current position.
--    A reference whose step became a heading renders as plain text, the same rule waits follow.
CREATE TABLE recipe_note_step_refs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id    INTEGER NOT NULL REFERENCES recipe_notes(id)  ON DELETE CASCADE,
    ref_index  INTEGER NOT NULL,
    match_text TEXT    NOT NULL,
    step_id    INTEGER          REFERENCES recipe_steps(id)  ON DELETE SET NULL,
    CHECK (ref_index >= 0),
    UNIQUE (note_id, ref_index)
);

CREATE INDEX idx_note_step_refs_note ON recipe_note_step_refs (note_id);
CREATE INDEX idx_note_step_refs_step ON recipe_note_step_refs (step_id);

COMMIT;
