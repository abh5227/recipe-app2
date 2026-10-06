-- 062 — an optional TITLE on a note.
--
-- Additive, and it runs BEFORE the deploy, like 060 and 061. The new code selects the column, so
-- deploying first would fail every recipe page on a column that does not exist yet. That is the rule
-- migration 053 established, and 054 established its mirror for a drop.
--
-- ⚠️ NULLABLE, AND THE DIFFERENCE BETWEEN NULL AND '' MATTERS. NULL means "this note has no title",
-- which is 148 of the 176 notes the corpus carries once this round has run. An empty string would be
-- a title the editor had cleared, and the CHECK below refuses it so the two states cannot both mean
-- "none". A cleared Title box writes NULL, not ''.
--
-- ⚠️ NO BASELINE CHANGE FROM THIS COLUMN, BECAUSE NOTES ARE NOT IN THE BASELINE. Andy's ruling is
-- that a note is a playground: the rows and the derived column are both out of
-- recipe_snapshots.content, and snapshot_diff does not compare notes at all. So the 28 titles this
-- round writes, over 18 recipes, mint no annotation entry and cost none of them their place in the
-- byte-equal set.
--
-- ⚠️ THAT DOES NOT COVER THE ROUND'S OTHER TWO ROWS. The same round strips wrapping emphasis from
-- ingredient headings 9213 and 9217 on brioche-cinnamon-rolls, and recipe_ingredients.raw_text IS
-- baseline content, so those two are patched in lockstep with their baselines or that recipe leaves
-- the byte-equal set. The column below is not what carries them.
--
-- ⚠️ THE TITLE IS NOT THE LABEL. recipe_notes.text keeps the author's words verbatim, label and all,
-- which is the rule migration 060 states. A title is lifted OUT of the text only where Andy's
-- recorded decision says so (docs/data-repairs/note-titles-2026-10-05.csv), and in that case the
-- "Title:" prefix comes off the front of the text because it would otherwise print twice.
BEGIN;

ALTER TABLE recipe_notes ADD COLUMN title TEXT
    CHECK (title IS NULL OR length(trim(title)) > 0);

COMMIT;
