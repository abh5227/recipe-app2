-- 061 — the author's original notes, kept as a RECORD and compared by nothing.
--
-- Additive. Runs BEFORE the deploy, like 060.
--
-- ⚠️ WHY A SEPARATE TABLE RATHER THAN THE BASELINE. Andy's ruling: notes are a playground. They take
-- no part in "your changes", they mint no marks, and editing one must not cost a recipe its place in
-- the byte-equal (untouched) set. That means the notes leave recipe_snapshots.content entirely, and
-- the baseline is where the author's words used to be kept. This table is where they go instead, so
-- a future "restore the original notes" is still possible.
--
-- ⚠️ WRITTEN ONCE PER RECIPE AND NEVER UPDATED. scripts/notes_to_rows.py fills it from the notes
-- column as it moves the corpus, and import_write.commit_plan fills it for a recipe as it lands.
-- Nothing else writes it, nothing reads it on the page, and snapshot_diff does not know it exists.
-- The row's position and kind are the shape the notes had when they arrived, which is what a restore
-- would need.
BEGIN;

CREATE TABLE recipe_notes_original (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'notes' REFERENCES note_kinds(kind),
    text        TEXT    NOT NULL,
    recorded_at TEXT    NOT NULL,
    CHECK (length(trim(text)) > 0),
    UNIQUE (recipe_id, position)
);

CREATE INDEX idx_recipe_notes_original_recipe ON recipe_notes_original (recipe_id);

COMMIT;
