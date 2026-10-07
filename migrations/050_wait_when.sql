-- 050_wait_when.sql - a wait can be conditional, and only an unconditional one counts.
--
-- ⚠️ ADDITIVE ONLY. 049 is already applied to live, so this adds two columns rather than restating
--    the table. Both CHECK forms below were tested on ADD COLUMN in SQLite before this was written,
--    and both bite: an unknown when_kind and an only_if with no label are each rejected.
--
-- ⚠️ `when` IS A RESERVED WORD, exactly like `where` in 049. The columns are when_kind and
--    when_label.
--
-- ⚠️ THE DEFAULT IS 'always', WHICH IS THE WHOLE POINT OF THE DEFAULT. Every wait that already
--    exists was read from a recipe that states it flatly, so every existing row is unconditional
--    and keeps counting toward the total. A backfill would say the same thing in more statements.
--
-- ⚠️ ONLY 'always' REACHES A TOTAL. An optional soak and a "only if you chilled it" rest are real
--    and worth showing, and neither is time a cook has to set aside. coconut-curried-golden-lentils
--    soaks the lentils "if you have time", and no-knead-bread rests 45 to 60 minutes only when the
--    dough went to the refrigerator. Summing either into "plan ahead" tells a cook to block out
--    time for something the recipe told them to skip. They show in the breakdown with their
--    qualifier and they stay out of the arithmetic.
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-08, in the same shape as the seven wrapped
-- on 2026-10-07 and for the same reason. These six were MISSED by that round: the rule that was
-- meant to find them split the file on ";" and dropped any fragment beginning with "--", and every
-- statement in this folder has a comment above it, so the rule counted 0 or 1 statements here and
-- reported nothing missing. Found by an independent review. See tests/test_migration_atomicity.py,
-- which now strips the comments before it counts.
-- Every database past this file is unaffected (migrate.py tracks by filename and never by
-- checksum), so this protects a FRESH INSTALL, which is the only thing that still runs it.
BEGIN;

ALTER TABLE recipe_waits ADD COLUMN when_kind TEXT NOT NULL DEFAULT 'always'
    CHECK (when_kind IN ('always','optional','only_if'));

-- when_label is the condition a cook reads after "if": "chilled", "you used dried beans".
-- It belongs to only_if and nothing else, so a bare only_if with no condition is rejected.
ALTER TABLE recipe_waits ADD COLUMN when_label TEXT
    CHECK (when_kind <> 'only_if' OR when_label IS NOT NULL);

CREATE INDEX idx_recipe_waits_when ON recipe_waits(when_kind);

COMMIT;
