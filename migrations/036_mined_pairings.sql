-- 036_mined_pairings.sql
-- Which ingredients appear together, and how much more often than chance. The second mined
-- table. Governed by docs/mining-decision.md, which is IN FORCE.
--
-- INERT. Nothing reads this yet. The app read path is Phase 4 and is not built, so a fresh clone
-- and CI get an empty table and no page changes. Same shape as 029 through 035.
--
-- ⚠️ THE NAME MUST START WITH mined_. Both boundary tests scan sqlite_master for tables LIKE
--    'mined_%'. A table called library_pairings is invisible to them, and that was measured
--    rather than assumed: a throwaway library_pairings holding a matched_sentence column passed
--    the no-corpus-text check because the scan never saw it. The prefix is what makes the
--    boundary reach this table at all.
--
-- ⚠️ LIFT IS STORED, NOT COMPUTED ON READ. lift = n * N / (n_a * n_b), where n_a and n_b come
--    from mined_occurrences and N is the 2,231,142 recipes in the corpus. The corpus is frozen
--    at recipenlg-2020 and is never updated, so a stored lift cannot go stale. Recomputing on
--    read would buy nothing and would tie every query to a join.
--
-- ⚠️ EVERY PAIR IS STORED AND n IS A COLUMN. 362,319 rows, of which 79,951 reach n>=20. The
--    floor is a DISPLAY default, not a filter applied here. Lift is unstable at low n, where a
--    pair seen once can score in the thousands, so a reader should be shown n>=20 by default.
--    Discarding the rest would have thrown away a queryable fact to save 34 MB.
--
-- WHAT THE RUN EXCLUDED, and both were decided on measured evidence:
--    k>25          352 records. 99.9% of recipes carry 25 or fewer matched ingredients and there
--                  is a clean gap above. The longest were concatenation junk: a 'Strawberry
--                  Butter' carrying 276 ingredient names is not a recipe.
--    non-food      158 records, excluded at the RECIPE level by nonfood_filter.py, never by
--                  banning an ingredient. Almost every cosmetic marker has a real food use:
--                  paraffin is in 1,534 candy recipes, lye makes hominy, argan oil is Moroccan
--                  food, and beeswax lines a canele mould. Before the filter the highest-lift
--                  pairs in the whole corpus were beeswax with emu oil and shea butter with
--                  jojoba oil, because RecipeNLG carries DIY lotion and soap. After it, 0 of the
--                  top 500 are cosmetic and the leaders are tianmianjiang with doubanjiang, malt
--                  with hops, shrimp paste with galangal.
--
-- ⚠️ IT ORDERS AND INFORMS. IT NEVER CUTS. Same rule as mined_occurrences. A pair that does not
--    appear is a fact about this corpus, not about the food.
--
-- ⚠️ A UI MUST RANK PER INGREDIENT, NOT GLOBALLY. Lift structurally favours the rare. garlic is
--    in 419,468 recipes so it co-occurs with nearly everything and its best lift is 5.1, while
--    cilantro at 70,914 reaches 23.1. A global top-lift list will never show garlic. The useful
--    question is "what does X pair with", answered by that row's own top slice.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR A CLONE. Derived from RecipeNLG, 2.29 GB, gitignored, not
--    redistributable, which is the derive_only status in source_catalogue. Regenerated only by
--    obtaining the corpus and re-running pairing_run.py. The durable record is that script plus
--    source_slug, not a replayable file. source_slug is part of the key, so a second corpus adds
--    rows rather than overwriting.

CREATE TABLE IF NOT EXISTS mined_pairings (
    a_id         TEXT    NOT NULL,
    b_id         TEXT    NOT NULL,
    n            INTEGER NOT NULL,
    n_a          INTEGER NOT NULL,
    n_b          INTEGER NOT NULL,
    lift         REAL    NOT NULL,
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (a_id, b_id, source_slug)
);

CREATE INDEX IF NOT EXISTS idx_mined_pairings_a ON mined_pairings (a_id, lift DESC);
CREATE INDEX IF NOT EXISTS idx_mined_pairings_b ON mined_pairings (b_id, lift DESC);
CREATE INDEX IF NOT EXISTS idx_mined_pairings_n ON mined_pairings (n DESC);
