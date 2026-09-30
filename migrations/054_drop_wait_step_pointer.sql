-- 054_drop_wait_step_pointer.sql - the old step pointer goes, now that nothing reads it.
--
-- ⚠️ DESTRUCTIVE, AND THIS IS THE CHEAPEST MOMENT IT WILL EVER BE. Live holds 0 recipe_waits rows, so
--    these two columns contain nothing anywhere. 053 replaced them with step_id and left them in place
--    so that migration could stay additive. This is the follow-up that removes them.
--
-- ⚠️ WHAT THEY WERE. step_position was a slot number and step_check a snippet of the step's text. A
--    save renumbers every step, so the position drifted, and the snippet existed only to notice the
--    drift and drop the link rather than describe the wrong step. It also compared the FRONT of the
--    step, so rewording a step's opening broke a link nobody meant to touch. A step row's id does
--    neither, which is what 053 moved to.
--
-- ⚠️ TESTED ON BOTH DIALECTS ON A COPY OF LIVE BEFORE THIS FILE WAS WRITTEN. SQLite has supported
--    ALTER TABLE DROP COLUMN since 3.35 and this build is 3.45.3. Neither column is indexed, part of a
--    key, or named in any CHECK, which are the cases SQLite refuses. After both drops: all four
--    indexes, all seven CHECKs, UNIQUE (recipe_id, position) and step_id's ON DELETE SET NULL all
--    survive, and integrity_check and foreign_key_check are clean. On Postgres both fks and all
--    checks survive.
--
-- ⚠️ ONE PENDING SCRIPT WROTE THESE COLUMNS AND IS PORTED IN THE SAME COMMIT.
--    scripts/apply_plan_ahead_proposals.py holds 105 proposed waits over 100 recipes, every one
--    carrying a step_position, and it has never been applied to live. It now resolves that position to
--    the step row's id at apply time and writes step_id. Without that port this migration would have
--    broken the only thing that still wrote here.

ALTER TABLE recipe_waits DROP COLUMN step_position;
ALTER TABLE recipe_waits DROP COLUMN step_check;
