-- 043_dish_cuisine_and_course.sql
-- Two facets the corpus could never answer, and a second source can. Both populated first by
-- Wikibooks, both governed by docs/mining-decision.md.
--
-- ⚠️ WHY THESE TWO WERE MISSING AND NOT SIMPLY UNBUILT. RecipeNLG is titles and ingredient names.
--    A title says what a dish IS, so form, method and diet fall out of it. It does not say where
--    the dish is from, and it does not say when in a meal you eat it. Those are facts an editor
--    states and a title does not carry. Wikibooks states both as categories:
--    2,248 cuisine tags on 52% of its recipes and 998 course tags on 26%.
--
-- ⚠️ CUISINE AND COURSE ARE FREE TEXT AND THAT NEEDED NO NEW EXCEPTION. Both column names were
--    already on tests/test_mining_boundaries.ALLOWED_MINED_TEXT_COLS, listed there before either
--    table existed, which is the pattern that file asks for. They hold a region and a meal
--    position, never a consumable and never a span the extractor read.
--
-- ⚠️ 156 CUISINES ARE KEPT ACROSS FIVE LEVELS OF GRANULARITY, ON PURPOSE. The source mixes
--    continents (african 81), countries (indian 154), sub-national regions (southern u.s. 65,
--    louisiana 17), ethnic groups inside a country (hausa 33, yoruba 23, sindhi 16) and diaspora
--    forms (tex-mex 41, italian-american 7). Flattening them to countries would throw away the
--    only rows that say hausa. Coarse and true beats absent. The owner's ruling.
--
--    Four merges were applied and each is a duplicate rather than a level: United States 130 with
--    American 2, Nigerian 58 with National Nigerian 38, Ghanaian 5 with the misspelling Ghanian 2,
--    and Inexpensive 196 with its lowercase twin.
--
-- ⚠️ `baking` IS A COURSE VALUE AND `baked` IS A METHOD VALUE, AND THEY ARE DIFFERENT AXES.
--    Wikibooks carries Baking recipes at 337 and Baked recipes at 245 as separate categories.
--    Baked is how the heat was applied. Baking is the kind of recipe it is, the shelf it sits on,
--    the same sort of label as dessert. A cake is both, and the facets are not exclusive, so
--    storing it twice on two axes is the correct outcome rather than a double count.
--
-- ⚠️ THE FLOOR ON BOTH IS THE COMBINED COUNT, NOT THE PER-SOURCE COUNT. See load_dish_facets.py.
--    A cell is not thin because one of its two sources is small.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR A CLONE, same as every other mined table. Derived from
--    en.wikibooks Cookbook pages under CC-BY-SA-4.0, which is recorded in sources.db. No recipe
--    text is stored: a cuisine is a category the editors chose and a course is a meal position.

CREATE TABLE IF NOT EXISTS mined_dish_cuisine (
    dish_id      TEXT    NOT NULL,
    cuisine      TEXT    NOT NULL,
    n            INTEGER NOT NULL,
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (dish_id, cuisine, source_slug)
);

CREATE TABLE IF NOT EXISTS mined_dish_course (
    dish_id      TEXT    NOT NULL,
    course       TEXT    NOT NULL,
    n            INTEGER NOT NULL,
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (dish_id, course, source_slug)
);

CREATE INDEX IF NOT EXISTS idx_mined_dish_cuisine_v ON mined_dish_cuisine (cuisine, n DESC);
CREATE INDEX IF NOT EXISTS idx_mined_dish_course_v  ON mined_dish_course  (course,  n DESC);
