-- 063 — drop the retired recipes.notes column.
--
-- ⚠️ DESTRUCTIVE, SO IT RUNS AFTER THE DEPLOY. That is the 054 rule and the mirror of 062's. The
-- code that stops naming the column serves BOTH schemas, so it goes out first and this file follows.
-- The previous deploy (7d703b7) still declares `notes` on its Recipe model, so
-- `select(Recipe.__table__)` emits the name and EVERY recipe page fails with "no such column" once
-- this has run. Measured on a copy rather than reasoned: see golive/2026-10-07-drop-notes-column.md.
--
-- WHAT IT WAS. Until migration 060 a recipe's notes were one TEXT blob on this column. 060 made
-- recipe_notes rows with a kind, a step link and an ingredient-line link, and the column stayed as a
-- DERIVED COPY so the previous deploy could still serve a recipe through the window. That window
-- closed on 2026-10-06.
--
-- ⚠️ NOTHING IS LOST THAT IS NOT HELD SOMEWHERE BETTER. The rows are the notes
-- (176 over 95 recipes), and recipe_notes_original holds the author's own words as they arrived
-- (177 paragraphs, written once by the pass that made the rows and read by nothing). Measured on
-- live before the drop: 19 of the 95 recipes already carried a column that no longer agreed with
-- its own rows, because the titles round deliberately left the copy alone while the rows gained
-- titles. A derived copy that is 19 recipes out of date is a liability rather than a record.
--
-- ⚠️ NO RECIPE LEAVES THE BYTE-EQUAL SET AND NO ANNOTATION MOVES. `notes` is not in
-- snapshot_serialize.SNAPSHOT_RECIPE_FIELDS and content_blob does not emit it, so the column reaches
-- nothing recipe_snapshots.content holds. scripts/notes_to_rows.py stripped the key from all 300
-- stored baselines in lockstep when the notes became rows. tests/test_lockstep_guard.py states this
-- over every migration, this one included.
--
-- ⚠️ SQLITE WILL ACTUALLY DO THIS, which is not true of every column. DROP COLUMN needs 3.35.0 (the
-- runtime here is 3.45.3) and refuses a column that is a primary key, is UNIQUE, is named by an
-- index, a view, a trigger, a CHECK, a generated column or a foreign key. Checked against live:
-- `notes TEXT,` carries no constraint and no default, the only indexes on recipes are on id and uid,
-- and the database holds 0 views and 0 triggers.
--
-- ⚠️ AND THERE IS NO DOWN. Putting the column back is an ALTER away, but filling it again is not:
-- the rows no longer carry the label prefixes the column holds. The rollback is a whole-file restore
-- from the backup taken in step 0, which is what the go-live file says.
BEGIN;

ALTER TABLE recipes DROP COLUMN notes;

COMMIT;
