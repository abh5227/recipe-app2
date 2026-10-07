-- 033_recipe_line_catalog_link.sql
-- Linkage, stage 1: give a recipe ingredient LINE a link to a built-catalog row, so a line can
-- reach the sourced library. Measured on the built catalog: 2,753 of 3,332 non-heading lines (82.6%)
-- reach a catalog row, and 730 (21.9%) reach one of the 56 sourced entries across 50 of them. The
-- same figure today, through `ingredient_id`, is 12 lines: 7 of the 36 ingredients those 50 linked
-- lines reach are also a sourced entry_id.
--
-- INERT. Nothing reads these columns. The matcher writes them only from a reviewed proposal file,
-- and the app read path is a later stage, so a fresh clone and CI get four NULL columns and no page
-- changes. Same shape as 029 through 032.
--
-- ⚠️ `ingredient_id` IS NOT REPURPOSED, AND THAT IS DELIBERATE. It is a foreign key to
--    `ingredients(id)`, it carries 50 live links, and the 30 `[[key]]`s sitting inside recipe prose
--    (`[[bread_flour|flour]]`) resolve against that SAME id space. Pointing it at a 10,515-row
--    catalog would break both. The two columns coexist and mean different things:
--      ingredient_id  a durable app row. The link target for recipe_ingredients since 001.
--      catalog_id     a catalog row, which is documented to dangle. Audit-grade, not structural.
--
-- ⚠️ catalog_id IS NOT A FOREIGN KEY TO library_names, for migration 030's reason exactly. Library
--    ids are not durable across a rebuild: the pasta anchor rule in 460cae5 destroyed 7 of them in
--    one ordinary commit. An FK would either block that rebuild or cascade recipe lines away with
--    it. A dangling catalog_id degrades a lookup and breaks no page, which is the safe direction.
--
-- ⚠️ FOUR COLUMNS RATHER THAN ONE, AND THE THREE EXTRAS EARN THEIR KEEP.
--      link_confidence  'exact' or 'form_strip'. An exact canonical match involved no inference. A
--                       form-strip match dropped a modifier and IS an inference, so the two are not
--                       the same claim and a reader of the column should not have to guess which.
--      link_rule        what produced it, e.g. 'form_strip:ground'. This is what makes a whole CLASS
--                       of links revertible. If a stripping rule turns out to be wrong, every link
--                       it made is one DELETE away, without re-running the matcher over 3,332 lines.
--      link_matched     the canonical the line matched. A wrong link is diagnosable by reading the
--                       row instead of reproducing the match.
--
-- NO ambiguous link is ever written. A normalized name held by more than one catalog row is REFUSED
-- rather than picked: measured, 25 lines over 9 names, and all 9 are canonical collisions already
-- queued for the Phase C merges, so those refusals resolve themselves later.
-- The Alembic revision mirrors this for Postgres.
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

ALTER TABLE recipe_ingredients ADD COLUMN catalog_id      TEXT;   -- library_names.library_id, NOT an FK
ALTER TABLE recipe_ingredients ADD COLUMN link_confidence TEXT;   -- 'exact' | 'form_strip'
ALTER TABLE recipe_ingredients ADD COLUMN link_rule       TEXT;   -- what produced it, for class-revert
ALTER TABLE recipe_ingredients ADD COLUMN link_matched    TEXT;   -- the canonical matched, for audit

CREATE INDEX idx_ri_catalog ON recipe_ingredients(catalog_id);

COMMIT;
