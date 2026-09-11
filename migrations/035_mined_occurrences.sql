-- 035_mined_occurrences.sql
-- The first mined table. How often each catalog row appears across a scraped recipe corpus.
-- Governed by docs/mining-decision.md, which is IN FORCE.
--
-- INERT. Nothing reads this yet. The app read path is Phase 4 and is not built, so a fresh clone
-- and CI get an empty table and no page changes. Same shape as 029 through 034.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR A CLONE, and that is not a defect. Every other table in this
--    schema is rebuilt from something committed: seed.py, hand_links.csv, hand_repoints.csv. This
--    one is not, and cannot be. It is derived from RecipeNLG, 2.29 GB, gitignored, and carrying a
--    license that forbids redistribution, which is the whole point of the derive_only status in
--    source_catalogue. A clone regenerates these rows only by obtaining that corpus independently
--    and re-running occurrence_run.py. The durable record is the reducer plus source_slug, not a
--    replayable file, and the migration is written so an empty table is a correct outcome.
--
-- ⚠️ AGGREGATE ONLY. Boundary (c) of the decision. `n` counts occurrences and `n_recipes` counts
--    distinct recipes, both across the whole corpus. No row here refers to a recipe, and none can
--    be traced back to one. There is no text column, which boundary (f) has a test for.
--
-- ⚠️ IT ORDERS, IT NEVER CUTS, and the full run made the reason concrete rather than theoretical.
--    Atlantic salmon counted 8 and baker's yeast counted 3 across 2.2 million recipes, sitting
--    among 399 rows counted once and 7,456 counted zero, indistinguishable from
--    'anti-obesity medication'. A low count is a fact about the corpus and never about the row.
--    See docs/what-the-library-is-for.md, which forbids recipe-line count as a cut signal, and
--    the founding-principle line in docs/mining-decision.md.
--
-- ⚠️ source_slug IS PART OF THE KEY, so a second corpus becomes a second set of rows rather than
--    overwriting the first. Two corpora disagreeing about an ingredient is a fact worth keeping.

CREATE TABLE IF NOT EXISTS mined_occurrences (
    library_id   TEXT    NOT NULL,
    n            INTEGER NOT NULL,
    n_recipes    INTEGER NOT NULL,
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (library_id, source_slug)
);

CREATE INDEX IF NOT EXISTS idx_mined_occurrences_n ON mined_occurrences (n DESC);
