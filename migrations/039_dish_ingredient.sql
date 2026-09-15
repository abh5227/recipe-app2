-- 039_dish_ingredient.sql
-- The dish x ingredient profile. What a dish is actually made of, counted across the corpus.
--
-- ⚠️ THE SAFEST TABLE IN THE MINED SCHEMA, and it is worth saying why before anything else. Every
--    column is a surrogate hash, a catalog id or an integer. No corpus text, no vocabulary to
--    police, no exception needed. `check_no_corpus_text` passes it without a new allowed column.
--
-- ⚠️ IT IS ALSO THE ONE MOST EXPOSED TO BOUNDARY (c), AND THAT IS NOT A CONTRADICTION. The
--    boundary docs/mining-decision.md section 2 names is the thin cell: "an aggregate over three
--    recipes with an unusual ingredient can point at those three recipes the way a reproduction
--    would." A dish x ingredient cell is a thin cell by construction. A dish seen 3 times crossed
--    with an ingredient in 1 of them IS a pointer to one recipe.
--
--    The floor is what answers it. Only rows supported by at least 10 recipes are loaded, and
--    load_dish_facets.py refuses a file that carries anything thinner.
--
-- ⚠️ MEASURED: THIS TABLE HAS NO NATURAL CEILING WITHOUT THE FLOOR. Heaps fitted over seven
--    nested checkpoints on a strided 1-in-25 sample of the whole corpus:
--
--        dish floor      beta      projected cells at 2,231,142
--             1         0.985               9,140,896
--             3         0.843               2,924,202
--            10         0.769               1,528,374
--            20         0.726               1,021,747
--
--    `mined_pairings` sits at beta 0.39, which is why it settled at 362,319 rows and stayed
--    there. A beta of 0.985 is linear growth, meaning each new recipe brings a nearly-new cell.
--    The cause is the dish side rather than the ingredient side: 876,132 distinct dishes with
--    81.8% of them seen exactly once. Flooring the dish restores saturation.
--
-- ⚠️ n_dish IS STORED RATHER THAN JOINED, the same frozen-denominator reasoning as
--    mined_pairings holding n_a and n_b. The corpus is frozen at recipenlg-2020, so the share
--    n / n_dish cannot go stale, and a reader gets `chicken marsala -> chicken breast 62%`
--    without a second lookup.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR A CLONE. Derived from RecipeNLG, gitignored, derive_only.
--    Same contract as 035 through 038.

CREATE TABLE IF NOT EXISTS mined_dish_ingredient (
    dish_id      TEXT    NOT NULL,          -- mined_dish.dish_id, the surrogate
    library_id   TEXT    NOT NULL,          -- a real catalog row. never a word, never a mark
    n            INTEGER NOT NULL,          -- recipes of this dish carrying this ingredient
    n_dish       INTEGER NOT NULL,          -- recipes of this dish. the frozen denominator
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (dish_id, library_id, source_slug)
);
CREATE INDEX IF NOT EXISTS idx_mdi_dish ON mined_dish_ingredient (dish_id, n DESC);
CREATE INDEX IF NOT EXISTS idx_mdi_ing  ON mined_dish_ingredient (library_id, n DESC);
