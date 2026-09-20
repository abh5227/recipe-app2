-- 046_retire_seed_ingredients.sql - delete the 36 hand-authored ingredient rows, their 65 seasons
-- and their 44 regions, in lockstep with emptying seed.py's INGREDIENTS (same change).
--
-- The 36 were written early as a demonstration of what an ingredient library would look like. The
-- library that actually shipped is 10,013 catalog rows drawn from Wikidata, Open Food Facts,
-- AGROVOC and Wiktionary, and the 36 carry model-written prose that was never rewritten. They are
-- a demo of the idea, not an early version of the data, so they are deleted rather than migrated
-- onto the catalog.
--
-- ⚠️ ingredient_weights IS NOT TOUCHED AND MUST NOT BE. Its 129 rows are the King Arthur
--    volume-to-weight chart, real reference data behind the grams converter. 0 of its 129
--    lookup_keys is one of the 36, so nothing below reaches it, and build_db.seed_weights stays
--    exactly as it is. Only seed_content's ingredient half is being retired.
--
-- ⚠️ SCOPED TO source='seed' RATHER THAN TO EVERY ROW. All 36 carry that tier and no other
--    ingredient row exists today, so right now the two are the same set. They will not stay the
--    same. An app-owned or promoted ingredient added later has to survive this file on a database
--    built from scratch, and a predicate on the tier is what makes that true by construction
--    instead of by the table happening to hold nothing else.
--
-- ⚠️ MUST LAND WITH THE seed.py EDIT, and the lockstep runs one way. seed_content upserts
--    ingredients and never deletes them, so emptying INGREDIENTS on its own changes no row and
--    this file can follow it safely. This file on its own is undone, as the next build_db
--    re-inserts all 36. Migration 016 did the same job for the 5 seed recipes and carries the
--    same warning.
--
-- ⚠️ TWO UI FEATURES GO EMPTY, KNOWINGLY. /api/ingredients backs the ingredient drawer and
--    /api/in-season backs the month chips. Both read only these rows, so both return nothing
--    afterwards. The drawer's content was the demo prose being retired here, so a drawer that
--    still opened would be the thing the ruling removes.

-- ---- 1. the catalog gains the one row the repoint below needs ----------------------------------
-- 'lemongrass' is an authored row (authored_rows.csv, 2026-09-20). No Wikidata item carries the
-- English label anywhere in sources.db, so no admission rule could create it, and the catalog held
-- only lemongrass oil, lemon grass oil and raw lemongrass. The EXISTS guard keeps this a no-op
-- wherever library_names is empty, which is every Postgres database and every fresh clone.
-- seed_library_names loads that lookup from a gitignored file only a machine holding join.db can
-- generate, so an empty table there is the normal state rather than a fault.
INSERT INTO library_names (library_id, canonical)
SELECT 'lemongrass', 'lemongrass'
 WHERE EXISTS (SELECT 1 FROM library_names)
   AND NOT EXISTS (SELECT 1 FROM library_names WHERE library_id = 'lemongrass');

-- ---- 2. re-point the two recipe lines that carry no catalog_id ---------------------------------
-- 48 of the 50 lines pointing at the 36 already carry one and need nothing here. These two do not.
--
-- The values written are exactly what a later build_links.py run produces, so a rebuild is a no-op
-- rather than a diff. gai-yang's line matches the catalog row added above unaided (linkage_matcher
-- returns tier EXACT, rule 'exact', matched 'lemongrass'). The yeast line reads 'instant or
-- rapid-rise yeast' and the matcher returns UNMATCHED on it, so that one is also recorded in
-- hand_repoints.csv, which is where a decision a rule cannot reach has to live to survive a
-- rebuild.
UPDATE recipe_ingredients
   SET catalog_id = 'lemongrass', link_confidence = 'exact',
       link_rule = 'exact', link_matched = 'lemongrass'
 WHERE recipe_id = 'gai-yang' AND position = 4 AND catalog_id IS NULL;

UPDATE recipe_ingredients
   SET catalog_id = 'Q45422', link_confidence = 'repoint',
       link_rule = 'repoint:instant-yeast-to-yeast', link_matched = 'yeast'
 WHERE recipe_id = 'no-knead-bread' AND position = 1 AND catalog_id IS NULL;

-- ---- 3. release the recipe links -------------------------------------------------------------
-- ⚠️ ALL 50 LINES ARE RELEASED, NOT ONLY THE 2 REPOINTED ABOVE. recipe_ingredients.ingredient_id
--    carries no ON DELETE clause, so with foreign_keys ON (migrate.py sets it) the delete in
--    step 5 is refused outright while any line still points at one of these rows. Each line keeps
--    its qty, label and note, so the recipe reads exactly as it did. What it loses is the button
--    that opened the drawer, which is the feature being retired.
UPDATE recipe_ingredients
   SET ingredient_id = NULL
 WHERE ingredient_id IN (SELECT id FROM ingredients WHERE source = 'seed');

-- ---- 4. children first ------------------------------------------------------------------------
-- Both cascade on delete, so step 5 would clear them on its own wherever foreign_keys is ON.
-- They are written out anyway. build_db runs seed_content with the pragma OFF, and a file that
-- only works under one pragma setting is a file that fails quietly under the other.
DELETE FROM ingredient_seasons
 WHERE ingredient_id IN (SELECT id FROM ingredients WHERE source = 'seed');

DELETE FROM ingredient_regions
 WHERE ingredient_id IN (SELECT id FROM ingredients WHERE source = 'seed');

-- ---- 5. the rows themselves -------------------------------------------------------------------
DELETE FROM ingredients WHERE source = 'seed';

-- ---- 6. the regions left behind ---------------------------------------------------------------
-- ⚠️ ONLY THE ORPHANS, for the same reason step 3 is scoped. regions has no owner column and no
--    tier, so the only honest test of whether a row is still wanted is whether an ingredient still
--    names it. All 44 are orphaned once the 36 are gone. A region an app-owned ingredient reaches
--    later is kept by the same predicate.
DELETE FROM regions
 WHERE id NOT IN (SELECT region_id FROM ingredient_regions);
