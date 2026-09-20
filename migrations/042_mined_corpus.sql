-- 042_mined_corpus.sql
-- How many recipes each mined source was read from. The denominator N, stored at last.
--
-- ⚠️ WITHOUT THIS TABLE EVERY COMBINED LIFT IS SILENTLY WRONG. lift = n_ab * N / (n_a * n_b),
--    and N is the corpus size. It has never been stored anywhere. pairing_run.py computes it,
--    uses it, writes it to a JSON file as `recipes_read`, and the loader drops it. Nothing in
--    recipes.db records that RecipeNLG holds 2,231,142 recipes.
--
--    One source hides the gap, because a single corpus makes N a constant that cancels out of
--    every comparison. A second source ends that. Combining RecipeNLG with Wikibooks means
--    N = 2,231,142 + 3,792, and any code that has to guess N will reach for the largest count it
--    can see. MAX(n_recipes) in mined_occurrences is 960,395, the salt row. Using that as N
--    inflates every lift by 2.32x today and, once a small second source is added, the error runs
--    to roughly 588x on the Wikibooks side. No exception is raised and the numbers stay
--    plausible, which is what makes it worth a table of its own.
--
-- ⚠️ THE COLUMN IS `n`, NOT `n_recipes`, AND THE NAME WAS NOT A PREFERENCE.
--    tests/test_mining_boundaries.py::check_no_corpus_text asserts that every table matching
--    mined_% carries a column literally named `n`, on the rule that a row which cannot say how
--    many recipes it came from is not an aggregate. mined_corpus is the one table where that
--    question has the simplest possible answer, so `n` is exactly right: the recipes this source
--    was read from.
--
-- ⚠️ mined_at IS AN INTEGER, unix epoch seconds. A TEXT timestamp would be refused on sight by
--    the same boundary check, which admits a text column on a mined table only by a recorded
--    decision. Widening that list for a clock reading would spend a security guard on
--    convenience.
--
-- ⚠️ THE BACKFILL IS CONDITIONAL AND THAT IS THE POINT. A fresh clone has no corpus, so its
--    mined tables are empty, and a row asserting 2,231,142 recipes would be a claim about data
--    that is not there. The INSERT fires only where mined_pairings already holds recipenlg-2020
--    rows. Empty clone, no row. Andy's copy, one row.
--
-- ⚠️ 2,231,142 IS DERIVED FROM THE STORED DATA, NOT COPIED FROM A DOC. Every row of
--    mined_pairings satisfies lift = n * N / (n_a * n_b), so each one implies N = lift * n_a *
--    n_b / n. Solved across all 361,138 rows the median is exactly 2,231,142. The spread of
--    roughly 0.04% either side is rounding noise, because lift is stored to 4 decimal places.
--    tests/test_mined_combine.py re-derives it rather than trusting this file.

CREATE TABLE IF NOT EXISTS mined_corpus (
    source_slug  TEXT    NOT NULL,
    n            INTEGER NOT NULL,
    mined_at     INTEGER,
    PRIMARY KEY (source_slug)
);

INSERT OR IGNORE INTO mined_corpus (source_slug, n, mined_at)
SELECT 'recipenlg-2020', 2231142, NULL
WHERE EXISTS (SELECT 1 FROM mined_pairings WHERE source_slug = 'recipenlg-2020');
