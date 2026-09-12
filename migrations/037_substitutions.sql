-- 037_substitutions.sql
-- Substitutions, in two tables that are not the same kind of thing. Governed by
-- docs/mining-decision.md, which is IN FORCE.
--
-- ⚠️ ONE IS A QUEUE AND ONE IS A RECORD, and keeping them apart is the whole design. The 3d
--    diagnostic measured substitution text as thin and error-prone even after the fixes: 54.1%
--    of matches survive cleaning, direction reverses on a preposition, and a wrong row does not
--    average out the way a wrong pairing does. It tells a cook to replace the thing they have
--    with the thing they do not. So the corpus proposes into mined_substitution_candidates and a
--    person disposes into library_substitutions. Nothing crosses without a decision.
--
--    mined_substitution_candidates  DISPOSABLE. Rebuilt whole by the next mining run. Losing it
--                                   costs 622 seconds of CPU and nothing else.
--    library_substitutions          REPLAYED from hand_substitutions.csv on every build, the
--                                   same contract as hand_links.csv and library_relations. The
--                                   hand file is the only writer. A row that exists only here is
--                                   orphaned by the next load with nothing to notice it.
--
-- ⚠️ BOTH ARE GUARDED, AND THE CONFIRMED TABLE IS THE REASON THE GUARD CHANGED. The boundary
--    tests used to scan `mined_%` and nothing else, so a corpus-derived table called
--    library_something was invisible to them. Proved rather than supposed: a library_substitutions
--    carrying a free-text `note` passed the no-corpus-text check, and the identical table named
--    mined_substitution_candidates was refused. Both names are now in GUARDED_TABLES in
--    tests/test_mining_boundaries.py, and both were listed BEFORE either table existed.
--
-- ⚠️ NO NOTE COLUMN, ON EITHER TABLE. A note is a person's words about a swap and it belongs in
--    hand_substitutions.csv, where a person wrote it. A free-text column on a corpus-derived
--    table is the documented way boundary (b) erodes: it starts as somewhere to keep a reason
--    and ends holding the sentence the extractor read.
--
-- ⚠️ `pattern` IS PROVENANCE, NOT TEXT. It holds the name of the rule that fired, drawn from
--    five labels the extractor declares, joined with + when several fired for one pair. `sub X
--    for Y` is a label. The clause it matched is never returned by substitution_run.py, never
--    written here, and is not kept for debugging. A test asserts every stored value splits into
--    those five labels, so a sentence landing in this column fails the suite rather than sitting
--    there unnoticed.
--
-- ⚠️ to_id IS NULLABLE, AND A NULL IS A FLAGGED GAP RATHER THAN A MISSING VALUE. 143 matches read
--    as one ingredient replaced by two, `use honey and applesauce instead of sugar`. A
--    (from_id, to_id) row cannot say that. Dropping them would hide the shape of what this schema
--    cannot hold, so they are stored with to_id NULL and one_to_many set, and the queue shows them
--    as a gap. 213 sightings across 123 distinct from_ids.
--
--    That nullable column is why uniqueness is an expression index rather than a primary key.
--    SQLite permits NULL in a PRIMARY KEY column and counts every NULL as distinct, so
--    PRIMARY KEY (from_id, to_id, source_slug) would let the same one-to-many row be inserted
--    twice without complaint. IFNULL folds them to one key.
--
-- ⚠️ DIRECTION IS THE FACT, so the pair is ordered and the reverse count rides beside it. 631
--    pairs were seen both ways. water -> chicken broth was seen 137 times against 5 the other
--    way, and that asymmetry is the evidence the preposition rule works rather than noise to
--    average away. Both directions are stored as their own rows, each carrying the other's count
--    in n_reverse, so a reviewer sees the ratio without a self-join.
--
-- ⚠️ n ON THE CONFIRMED TABLE IS THE SUPPORT AT THE MOMENT OF CONFIRMATION, and NULL for an
--    authored row, which never had corpus support at all. Boundary (c) asks that a stored fact
--    can say how many recipes it came from. A confirmed row answers with a number, an authored
--    row answers by being honest that the question does not apply to it.
--
-- ⚠️ EMPTY IS THE NORMAL STATE FOR BOTH ON A CLONE. The candidates derive from RecipeNLG, 2.29 GB,
--    gitignored, derive_only in source_catalogue, regenerated only by obtaining the corpus and
--    re-running substitution_run.py. library_substitutions is empty until somebody confirms
--    something: on the day this migration lands, nothing has been confirmed, and that is correct.

CREATE TABLE IF NOT EXISTS mined_substitution_candidates (
    from_id      TEXT    NOT NULL,
    to_id        TEXT,                      -- NULL means one-to-many, see one_to_many
    n            INTEGER NOT NULL,
    n_reverse    INTEGER NOT NULL DEFAULT 0,
    one_to_many  INTEGER NOT NULL DEFAULT 0,
    pattern      TEXT    NOT NULL,
    source_slug  TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_msc_key
    ON mined_substitution_candidates (from_id, IFNULL(to_id, ''), source_slug);
CREATE INDEX IF NOT EXISTS idx_msc_n ON mined_substitution_candidates (n DESC);
CREATE INDEX IF NOT EXISTS idx_msc_from ON mined_substitution_candidates (from_id, n DESC);

CREATE TABLE IF NOT EXISTS library_substitutions (
    from_id      TEXT    NOT NULL,
    to_id        TEXT    NOT NULL,
    origin       TEXT    NOT NULL,          -- mined-confirmed | authored
    ratio        REAL,                      -- how much of `to` stands in for one of `from`
    n            INTEGER,                   -- corpus support when confirmed, NULL when authored
    source_slug  TEXT    NOT NULL,
    PRIMARY KEY (from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_lsub_from ON library_substitutions (from_id);
CREATE INDEX IF NOT EXISTS idx_lsub_to ON library_substitutions (to_id);
