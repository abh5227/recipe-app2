-- 030_ingredient_provenance.sql
-- Add-on-save ingredient linking, stage 2: tell a PROMOTED ingredient row apart from a hand-authored
-- seed one. Until now every row in `ingredients` came from seed.py's INGREDIENTS, so there was nothing
-- to distinguish. Stage 5's save path will create rows from the library, and once two kinds of row
-- share the table, two later stages need to know which is which:
--   source      stage 6's delete path refuses a seed row and allows a promoted one.
--   library_id  a re-audit needs to know WHICH library row a promoted ingredient came from.
--
-- VOCABULARY MIRRORS recipes.source, WHICH MIGRATION 004 ADDED THE SAME WAY:
--     ALTER TABLE recipes ADD COLUMN source TEXT NOT NULL DEFAULT 'seed';
-- Same three words ('seed', 'app', 'test'), same TEXT NOT NULL DEFAULT 'seed', so a reader of one
-- column already knows the other. Stage 5 will write 'app' for a promoted row. No CHECK constraint,
-- matching recipes.
--
-- ⚠️ THE DEFAULT IS 'seed' BECAUSE THAT IS THE FAIL-SAFE DIRECTION, and the other choice is dangerous.
--    SQLite backfills every existing row with the default on ADD COLUMN, so the 36 hand-authored rows
--    read as seed-tier without a separate UPDATE. Defaulting to 'app' instead would mark all 36 as
--    promoted, and stage 6's delete path would then treat the whole curated library as deletable. With
--    'seed' as the default, a stage-5 writer that FORGETS to set source leaves a promoted row looking
--    like seed, which makes it undeletable rather than wrongly deleted. Refusing too much is a
--    nuisance. Deleting a row somebody wrote by hand is not recoverable.
--
-- ⚠️ library_id IS NOT A FOREIGN KEY TO library_names, AND THAT IS DELIBERATE. Library row ids are not
--    durable across a rebuild: the pasta anchor rule in 460cae5 destroyed 7 of them in one ordinary
--    commit (en:penne, en:lasagne, en:linguine and 4 more). An FK would either block that rebuild or
--    cascade the promoted ingredient away with it. This column is AUDIT PROVENANCE and it is expected
--    to dangle. Nothing on any page reads it, so a dangle degrades a re-audit and breaks no view. The
--    durable link target is the `ingredients` row itself, which is why recipe_ingredients points there
--    and not here.
--
-- NULLABLE, and the 36 get NULL. They are hand-authored and have no library origin, so NULL is the
-- honest value rather than a sentinel. A NULL library_id alongside source='seed' is what a curated row
-- looks like.
--
-- INERT. Nothing writes or reads either column. Stage 5 populates them, stage 6 reads source. Adding
-- them changes no behavior: seed_content's upsert names neither column, so a rebuild leaves both alone.
-- This is the SQLite half of the dual schema source, and an Alembic revision mirrors it for Postgres.
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

ALTER TABLE ingredients ADD COLUMN source     TEXT NOT NULL DEFAULT 'seed';   -- 'seed' | 'app', as recipes.source
ALTER TABLE ingredients ADD COLUMN library_id TEXT;                           -- the library row it came from (NULL when hand-authored)

COMMIT;
