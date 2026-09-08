-- 032_library_entries.sql
-- The sourced ingredient library, stage 1: the tables that hold the verified entries currently
-- living only as TOML in Library/sourced/. 56 entries, ~1,120 rows in total, which is small beside
-- recipe_ingredients at 3,555.
--
-- INERT. Nothing reads these tables. The loader is a separate module and the app read path is a
-- later stage, so a fresh clone and CI both get EMPTY tables and no page changes. Same shape as
-- migrations 029, 030 and 031, which all landed schema before anything used it.
--
-- ⚠️ NOTHING HERE TOUCHES `ingredients`. The sourced prose lands in library_prose_pieces, NOT in
--    ingredients.descr, and the loader never writes that column. The reason is measured: 9 of the 56
--    entries land on an ingredients row that already carries hand-written descr, and build_db's
--    seed_content upserts all 36 rows ON CONFLICT(id) DO UPDATE SET descr = excluded.descr on every
--    run. A description written into descr would be silently overwritten by the next rebuild. Keeping
--    the sourced prose in its own table means the rebuild cannot reach it, so the problem does not
--    need working around. The 9 legacy descriptions are left exactly as they are.
--
-- ⚠️ CLAIMS AND SAFETY FLAGS SHARE ONE TABLE, WITH A DISCRIMINATOR, AND SPLITTING THEM SILENTLY
--    LOSES DATA. Measured over the 56 entries: 6 prose pieces carry a derived_from naming a
--    safety_flag key rather than a claim key (bacon x2, crushed-red-pepper, ground-beef, lime,
--    potato), and one judgement's affects.target does the same. Claim keys and flag keys are verified
--    collision-free inside every entry, and all 172 (entry_id, key) pairs are distinct, so the union
--    is a valid namespace and library_prose_derived_from can carry ONE foreign key instead of a
--    polymorphic reference resolved at read time. Two tables would need that reference and a
--    two-table loader would drop those 7 links.
--
-- ⚠️ JUDGEMENTS HOLD TWO SHAPES AND BOTH ARE VALID. 17 use the canonical shape (id, kind, made_by,
--    decided, alternatives, reasoning, tier, falsifier). 3 use a lighter shape (key, about, author,
--    body) recording a decision that was DEFERRED rather than made. The lighter three are not
--    malformed. They lack decided, alternatives and falsifier because nothing was decided, and
--    forcing them into the canonical shape would mean inventing a decision nobody made. Every column
--    outside entry_id and position is therefore nullable, and a CHECK requires one shape or the other.
--
-- link_state IS THE DUAL-KEY RECONCILE, and it exists because library ids are not durable. Migration
-- 030 says at length that library_id dangles across a catalog rebuild (the pasta anchor rule in
-- 460cae5 destroyed 7 ids in one ordinary commit), which is why each entry also carries a
-- library_canonical snapshot. The loader resolves the id first and falls back to the snapshot:
--     linked          the stored library_id is in library_names and the canonical still matches
--     canonical_drift the id resolves, the canonical moved. The id wins, the drift is recorded
--     healed          the id is gone, the canonical matched one row, library_id_resolved is rewritten
--     unresolved      the id is gone and the canonical matched zero rows or more than one
--     no_library_id   the entry never had one (measured: salt, sugar and water, 3 of 56)
-- Measured on today's catalog: 53 of 56 carry an id, all 53 resolve, and 1 shows canonical drift
-- (tomato-puree stores 'tomato puree' against a live 'tomato purée', an accent that norm_name
-- deliberately does not fold). So today this reconcile does almost nothing, which is the point. It
-- makes the decay VISIBLE rather than silent, and it is the same name matcher that resolving
-- possible_parent into real edges will need later.
--
-- ⚠️ library_id IS STILL NOT A FOREIGN KEY TO library_names, for migration 030's reason exactly. An
--    FK would either block a catalog rebuild or cascade a sourced entry away with it. link_state is
--    how a dangle is reported instead.
--
-- possible_parent IS TEXT AND NOT AN EDGE. 15 entries carry one and every value is a bare name
-- ('pork', 'rice', 'chili pepper', 'minced meat'), not an id. Resolving those into real parent-child
-- links is a separate decision and a separate pass.
-- The Alembic revision mirrors this for Postgres.

CREATE TABLE library_entries (
    entry_id            TEXT PRIMARY KEY,          -- the TOML `id`, e.g. 'black-pepper'
    name                TEXT NOT NULL,             -- the app-facing name, e.g. 'Black pepper'
    library_id          TEXT,                      -- as STORED in the file (NOT an FK, see above)
    library_canonical   TEXT,                      -- the heal snapshot taken when the entry was written
    library_id_resolved TEXT,                      -- what it resolves to NOW (rewritten when healed)
    link_state          TEXT NOT NULL,             -- linked | canonical_drift | healed | unresolved | no_library_id
    link_note           TEXT,                      -- what the reconcile saw, when it is worth saying
    review_state        TEXT NOT NULL,
    form                TEXT,
    cuisine             TEXT,
    scope_note          TEXT,
    possible_parent     TEXT,                      -- a bare NAME, deliberately not an edge
    diagnostic_verdict  TEXT NOT NULL,
    diagnostic_detail   TEXT NOT NULL,
    source_file         TEXT NOT NULL,             -- 'black-pepper.toml', for re-load and audit
    loaded_at           TEXT NOT NULL,
    CHECK (link_state IN ('linked','canonical_drift','healed','unresolved','no_library_id'))
);
CREATE INDEX idx_lib_entries_library_id ON library_entries(library_id_resolved);
CREATE INDEX idx_lib_entries_link_state ON library_entries(link_state);

-- Claims and safety flags. ONE table, discriminated by assertion_kind. The flag-only columns are
-- null on a claim and the CHECK holds that true.
CREATE TABLE library_assertions (
    entry_id       TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    key            TEXT NOT NULL,
    assertion_kind TEXT NOT NULL,                  -- 'claim' | 'safety_flag'
    text           TEXT NOT NULL,
    tier           TEXT NOT NULL,                  -- generated | curated | cited
    state          TEXT NOT NULL,                  -- settled | unresolved
    checkable      TEXT NOT NULL,                  -- kitchen | label | none
    source_class   TEXT NOT NULL,
    n              INTEGER NOT NULL,
    mode           TEXT,
    rests_on       TEXT,                           -- FREE PROSE, not a reference. See the loader
    see_also       TEXT,
    cannot_assess  TEXT,                           -- JSON array of strings, claims only
    flag_kind      TEXT,                           -- flags: certain_presence | possible_presence | food_safety | none
    surfaces       INTEGER,                        -- flags: 0/1
    allergen       TEXT,
    hazard         TEXT,
    also           TEXT,
    note           TEXT,
    needs          TEXT,
    needs_reason   TEXT,
    position       INTEGER NOT NULL,
    PRIMARY KEY (entry_id, key),
    CHECK (assertion_kind IN ('claim','safety_flag')),
    CHECK (tier  IN ('generated','curated','cited')),
    CHECK (state IN ('settled','unresolved')),
    CHECK (assertion_kind = 'safety_flag' OR (flag_kind IS NULL AND surfaces IS NULL
           AND allergen IS NULL AND hazard IS NULL)),
    CHECK (assertion_kind = 'claim' OR flag_kind IS NOT NULL)
);
CREATE INDEX idx_lib_assertions_kind ON library_assertions(assertion_kind);
CREATE INDEX idx_lib_assertions_tier ON library_assertions(tier);

-- The sources a chain points at, deduplicated. Measured: 198 chain rows over 128 distinct source
-- slugs, and 46 slugs are used more than once (us-fdca-21usc321-major-allergen alone is used 13
-- times), so this is worth its own table rather than a repeated string.
-- url is NULLABLE: one chain names 'repo: weights.py', an internal file with no URL.
CREATE TABLE library_sources (
    source_slug TEXT PRIMARY KEY,
    url         TEXT
);

CREATE TABLE library_chains (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id      TEXT NOT NULL,
    key           TEXT NOT NULL,
    source_slug   TEXT NOT NULL REFERENCES library_sources(source_slug),
    mode          TEXT NOT NULL,                   -- read | fetch_blocked | search_snippet | snippet
    read_depth    TEXT NOT NULL,                   -- full | snippet | abstract | cannot_assess
    taken         TEXT NOT NULL,                   -- what was actually read. The load-bearing field
    cannot_assess INTEGER,
    slug          TEXT,
    position      INTEGER NOT NULL,
    FOREIGN KEY (entry_id, key) REFERENCES library_assertions(entry_id, key) ON DELETE CASCADE
);
CREATE INDEX idx_lib_chains_assertion ON library_chains(entry_id, key);
CREATE INDEX idx_lib_chains_source    ON library_chains(source_slug);

-- Per-piece prose. derived_tier is STORED rather than computed on read, and the loader asserts it
-- recomputes to the same value. The rule: no derived_from is generated, one key is that key's tier,
-- several keys is the WEAKEST of them.
CREATE TABLE library_prose_pieces (
    entry_id      TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    slot          TEXT NOT NULL,                   -- 'descr' on all 56 today
    position      INTEGER NOT NULL,
    text          TEXT NOT NULL,
    resolved_note TEXT,
    cut_note      TEXT,
    derived_tier  TEXT NOT NULL,
    PRIMARY KEY (entry_id, slot, position),
    CHECK (derived_tier IN ('generated','curated','cited'))
);

-- A piece may cite a claim key OR a safety flag key. One FK covers both because they share a
-- namespace. See the header.
CREATE TABLE library_prose_derived_from (
    entry_id TEXT NOT NULL,
    slot     TEXT NOT NULL,
    position INTEGER NOT NULL,
    key      TEXT NOT NULL,
    PRIMARY KEY (entry_id, slot, position, key),
    FOREIGN KEY (entry_id, slot, position)
        REFERENCES library_prose_pieces(entry_id, slot, position) ON DELETE CASCADE,
    FOREIGN KEY (entry_id, key)
        REFERENCES library_assertions(entry_id, key) ON DELETE CASCADE
);

CREATE TABLE library_discussions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    author   TEXT NOT NULL,
    body     TEXT NOT NULL,
    position INTEGER NOT NULL,
    FOREIGN KEY (entry_id, key) REFERENCES library_assertions(entry_id, key) ON DELETE CASCADE
);
CREATE INDEX idx_lib_discussions_assertion ON library_discussions(entry_id, key);

-- Both judgement shapes. shape='canonical' carries id/decided/alternatives/reasoning/tier,
-- shape='deferred' carries judgement_key/author/body. Nothing is forced across.
CREATE TABLE library_judgements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id      TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    shape         TEXT NOT NULL,                   -- 'canonical' | 'deferred'
    judgement_id  TEXT,                            -- canonical: the TOML `id`, e.g. 'j-bp-white-pungency'
    kind          TEXT,
    made_by       TEXT,
    decided       TEXT,
    alternatives  TEXT,                            -- JSON array of strings
    reasoning     TEXT,
    tier          TEXT,
    falsifier     TEXT,
    affects       TEXT,                            -- JSON array of {target, effect}
    needs         TEXT,
    needs_reason  TEXT,
    judgement_key TEXT,                            -- deferred: the TOML `key`
    about         TEXT,                            -- deferred: the claim key it concerns (optional)
    author        TEXT,
    body          TEXT,
    position      INTEGER NOT NULL,
    CHECK (shape IN ('canonical','deferred')),
    CHECK (shape = 'deferred'  OR decided IS NOT NULL),
    CHECK (shape = 'canonical' OR body    IS NOT NULL)
);
CREATE INDEX idx_lib_judgements_entry ON library_judgements(entry_id);

CREATE TABLE library_forms (
    entry_id TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    form     TEXT NOT NULL,
    kind     TEXT NOT NULL,                        -- alias | belongs_elsewhere | ambiguous | ... (12 seen)
    note     TEXT,
    PRIMARY KEY (entry_id, position)
);

-- One entry carries this today (ice-cream, naming a Wikidata row it is deliberately NOT merged with).
-- It gets a table rather than a JSON blob so a strict loader has somewhere to put it.
CREATE TABLE library_siblings (
    entry_id      TEXT NOT NULL REFERENCES library_entries(entry_id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    sibling_id    TEXT NOT NULL,
    why_separate  TEXT,
    PRIMARY KEY (entry_id, position)
);
