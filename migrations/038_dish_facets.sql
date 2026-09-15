-- 038_dish_facets.sql
-- The eight dish facets. Governed by docs/mining-decision.md, which is IN FORCE.
--
-- ⚠️ SEVEN TABLES ARE SAFE BY CONSTRUCTION AND ONE IS AN EXCEPTION. That split is the whole design
--    and it is why there are eight tables instead of one wide one.
--
--    form, method, diet, structural, appliance  hold a word from a vocabulary this repo authored
--                                               and Andy reviewed. A brand is never in a
--                                               vocabulary, so boundary (g) holds without a check.
--    base, accompaniment                        hold a library_id. A catalog row is never a mark.
--                                               Measured: 0 of the resolved accompaniment ids are
--                                               a brand, across 76,475 phrases.
--
-- ⚠️ base DID NOT HOLD A LIBRARY_ID IN THE FIRST DRAFT OF THIS FILE, and the comment above said
--    it did. dish_facets.BASE is a word set, so the extractor emitted `apple` into a column named
--    library_id. Measured before the fix: 142 of 146 values were not catalog rows, 94.1% of the
--    facet weight was orphan, and the 4 that resolved did so by accident because `bread`, `egg`,
--    `gnocchi` and `pasta` happen to be bare-word ids. A partial accidental join is worse than
--    none, since a query returns 5.9% of the data and looks like it worked. dish_facets.base_id_map
--    now resolves the word through linkage_matcher before anything is emitted. 128 of 146 resolve,
--    covering 92.9% of base facet weight.
--
-- ⚠️ THE 18 THAT DO NOT RESOLVE ARE A CATALOG GAP AND ARE RECORDED, NOT FILLED. 15 of them are
--    absent from library_names entirely: turkey, mushroom, pecan, cherry, caramel, crab, lasagna,
--    artichoke, quinoa, sprout, pistachio, polenta, tortellini, gelatin, calamari. A catalog of
--    10,474 rows has no turkey. The dish keeps every other facet and carries no base row, which
--    is a true statement rather than a silent drop. docs/what-the-library-is-for.md governs
--    admitting a row, so this queue informs and never fills.
--
-- ⚠️ A MIN-N FLOOR OF 10 IS APPLIED AT LOAD, NOT IN THE SCHEMA. Boundary (c) says a row at n=1 is
--    not an aggregate. Measured before the floor: 716,535 of 876,132 dish rows sat at n=1, 81.8%
--    of them, and 253 of the 260 rows carrying a personal name sat there too. The floor is a
--    better cleaner than any regex, since a name has to appear in 10 separate recipes to survive
--    it. It lives in load_dish_facets.py because the right number is a judgement that may change,
--    and tests/test_mining_boundaries.py::MIN_N_FLOORS is what holds it to whatever it is.
--    mined_dish                                 ⚠️ holds the cleaned specific-dish STRING. This is
--                                               the one deliberate free-text exception in the
--                                               whole mined schema, recorded in
--                                               tests/test_mining_boundaries.py as an exception
--                                               rather than by widening the allowed-column list.
--
-- ⚠️ EVERY OTHER FACET REFERENCES THE DISH BY SURROGATE ID, never by its text. dish_id is the
--    first 16 hex characters of the sha256 of the cleaned string, so it is deterministic and a
--    re-run reproduces the same ids. That is what keeps the exception needed ONCE. An earlier
--    draft put a dish string on every facet table and the boundary check refused all seven.
--
-- ⚠️ THE STRING IS CLEANED BEFORE IT IS STORED, and the cleaning is not cosmetic. Measured over
--    the corpus, about 11,600 recipes carry a brand into the dish value and about 3,400 carry a
--    personal name. `Bisquick Baked Pancakes` and `Mrs. Field's Oatmeal Cookies` are the shapes.
--    Boundary (g) and the expression half of boundary (d) are enforced by that step rather than by
--    the schema, so the test checks the populated table rather than trusting the loader.
--
-- ⚠️ THE UNIT IS THE DISH, NOT THE RECIPE. RecipeNLG's 2,231,142 recipes are not stored anywhere
--    and cannot be. A row here says how many recipes in the corpus resolved to this dish, which is
--    an aggregate and satisfies boundary (c). No row refers to a recipe and none can be traced to
--    one.
--
-- ⚠️ A FACET IS A SET, NOT A VALUE, which is why each facet is its own table keyed on
--    (dish_id, value). 41% of accompaniment phrases name more than one ingredient, 19.4% of
--    base-carrying titles name more than one base, and `Stuffed Baked Potatoes` carries two
--    methods. A single column would have to arbitrate and would lose half of `broccoli and ham`.
--
-- WHAT THE VOCABULARIES REJECT, recorded because the rejections carry as much meaning as the
-- entries:
--    form         the style-not-form group is OUT. `Chicken Marsala` gets form NULL and is still
--                 captured as base chicken plus dish `chicken marsala`. Measured: rejecting the
--                 group changes only the form value and leaves base and dish identical.
--    base         cinnamon, ginger, mint, mustard and pepper are OUT. Each is a flavoring or a
--                 seasoning rather than what a dish is made of, and pepper sits in 13.7% of all
--                 recipes. Cost accepted: 702 stuffed-pepper titles come back with both facets
--                 empty.
--    method       bare verb stems are OUT. `dip` is the trailing noun 96% of the time, `stew` 95%,
--                 `bake` 78%. Those are forms. Participles only.
--    diet         `light` is OUT at 83.3% ambiguous, since `corn light bread` is a Southern white
--                 yeast bread. `lite` is in. `skinny` is in and the exact string `skinny dip` is
--                 special-cased out, which is 7 puns.
--    structural   `dump` is OUT. 86% of its 461 titles are `Dump Cake`, a dish name rather than a
--                 format, and the specific-dish facet already holds it.
--    appliance    skillet, broiler, grill, bbq, pan, oven, pot and fryer are OUT. Each is
--                 ambiguous or is already captured by another facet.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR A CLONE. Derived from RecipeNLG, 2.29 GB, gitignored,
--    derive_only in source_catalogue. Regenerated only by obtaining the corpus and re-running the
--    extractor. Same contract as 035, 036 and 037.

CREATE TABLE IF NOT EXISTS mined_dish (
    dish_id      TEXT    NOT NULL,
    dish         TEXT    NOT NULL,          -- ⚠️ THE ONE FREE-TEXT EXCEPTION. cleaned.
    n            INTEGER NOT NULL,
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (dish_id, source_slug)
);
CREATE INDEX IF NOT EXISTS idx_mdish_n ON mined_dish (n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_form (
    dish_id TEXT NOT NULL, dish_type TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, dish_type, source_slug));
CREATE INDEX IF NOT EXISTS idx_mdf_v ON mined_dish_form (dish_type, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_method (
    dish_id TEXT NOT NULL, method TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, method, source_slug));
CREATE INDEX IF NOT EXISTS idx_mdm_v ON mined_dish_method (method, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_diet (
    dish_id TEXT NOT NULL, diet TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, diet, source_slug));
CREATE INDEX IF NOT EXISTS idx_mdd_v ON mined_dish_diet (diet, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_structural (
    dish_id TEXT NOT NULL, structural TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, structural, source_slug));
CREATE INDEX IF NOT EXISTS idx_mds_v ON mined_dish_structural (structural, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_appliance (
    dish_id TEXT NOT NULL, appliance TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, appliance, source_slug));
CREATE INDEX IF NOT EXISTS idx_mda_v ON mined_dish_appliance (appliance, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_base (
    dish_id TEXT NOT NULL, library_id TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, library_id, source_slug));
CREATE INDEX IF NOT EXISTS idx_mdb_v ON mined_dish_base (library_id, n DESC);

CREATE TABLE IF NOT EXISTS mined_dish_accompaniment (
    dish_id TEXT NOT NULL, library_id TEXT NOT NULL, n INTEGER NOT NULL, source_slug TEXT NOT NULL,
    PRIMARY KEY (dish_id, library_id, source_slug));
CREATE INDEX IF NOT EXISTS idx_mdac_v ON mined_dish_accompaniment (library_id, n DESC);
