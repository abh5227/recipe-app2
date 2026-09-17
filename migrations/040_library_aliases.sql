-- 040_library_aliases.sql
-- The names a catalog row also answers to. One row, many names.
--
-- ⚠️ THE GAP THIS CLOSES, MEASURED. library_names is (library_id, canonical) with library_id as
--    the primary key, so the shipped catalog carries exactly ONE name per row. Variations exist
--    inside build_library, which is why hand_removals.csv has a drop_variation action, but they
--    have never shipped. Consequence: 4,060 English names the sources give to catalog rows reach
--    no canonical, spread over 2,035 rows, 19% of the catalog. A cook writing `turkey` reaches
--    nothing while `turkey meat` (Q4200953) sits in the catalog unreachable by that word.
--
-- ⚠️ IT IS NOT A RENAME AND IT IS NOT A MERGE, and the difference is the whole point. A rename
--    moves a canonical and keeps the id. A merge collapses two rows and DESTROYS an id. The
--    staged dish tables (mined_dish_base, mined_dish_ingredient) hold catalog ids, and
--    load_dish_facets.py refuses orphan ids before opening its transaction, so a merge would
--    orphan mined data that a rename and an alias both leave untouched. Merges are refused.
--
-- ⚠️ THE HAND FILE IS THE ONLY WRITER, the same contract as hand_links.csv into
--    library_relations and hand_substitutions.csv into library_substitutions. An alias stored
--    only here is orphaned by the next load with nothing in the build to notice it.
--
-- ⚠️ AMBIGUITY IS REPRESENTABLE ON PURPOSE, AND THIS IS DELIBERATE RATHER THAN LAX. There is no
--    UNIQUE on alias. The catalog ALREADY holds six names carried by two rows each (brown sauce,
--    gnocchi, ice cream, milkshake, mus, turnip) and linkage_matcher handles that by refusing:
--    "AMBIGUOUS - the name is held by more than one catalog row. REFUSED, never picked." A
--    UNIQUE here would make the table unable to describe a catalog state that already exists,
--    and would push the failure into the loader as a crash instead of into the matcher as a
--    refusal. The LOADER reports an alias that would newly resolve to two rows. The MATCHER
--    declines to pick. Both fail toward the miss, which is the pipeline's standing direction.
--
-- ⚠️ canonical_at_load IS THE DUAL-KEY SNAPSHOT, reusing the pattern library_relations proves
--    with child_canonical and parent_canonical. A row that is later renamed stays diagnosable by
--    reading the alias rather than by re-deriving it.
--
-- ⚠️ EMPTY IS SAFE AND IS THE NORMAL STATE FOR A FRESH CLONE. library_names is itself loaded
--    from a gitignored, server-side CSV, so a clone has no rows for an alias to point at. The
--    loader skips rather than raising, exactly as build_db.seed_library_names does, and every
--    read path degrades to today's canonical-only behavior.

CREATE TABLE IF NOT EXISTS library_aliases (
    library_id        TEXT NOT NULL,        -- library_names.library_id. NOT an FK, per 030.
    alias             TEXT NOT NULL,        -- a name this row also answers to, verbatim
    canonical_at_load TEXT,                 -- dual-key snapshot, as library_relations does
    source            TEXT NOT NULL,        -- wikidata | off | authored | read
    confidence        TEXT NOT NULL,        -- authored | read | high | picked
    note              TEXT,                 -- why, when it is not obvious
    PRIMARY KEY (library_id, alias),
    CHECK (confidence IN ('authored','read','high','picked'))
);

CREATE INDEX IF NOT EXISTS idx_la_alias ON library_aliases(alias);
