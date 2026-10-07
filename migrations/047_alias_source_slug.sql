-- 047_alias_source_slug.sql - an alias may be scoped to one source.
--
-- ⚠️ WHY. 'corn flour' means cornstarch to an Indian recipe writer and cornmeal to an American
--    one. Both rows exist (Q41415 cornstarch, Q10943 cornmeal, separate concepts), and the name
--    reaches neither today. An unscoped alias would have to pick one and be wrong for the other
--    source, which is the resolved-but-wrong failure the matcher is built to avoid.
--
-- ⚠️ NULL MEANS EVERY SOURCE, which is what all 183 existing rows are and what most rows should
--    stay. A scope is the exception, written only when two sources genuinely disagree about what
--    a name means. Scoping by default would fragment the catalog for no gain.
--
-- ⚠️ THE PRIMARY KEY IS UNCHANGED, (library_id, alias). A row carries at most one scope. Two
--    rows may share an alias when they carry different library_ids, which is exactly the
--    cornstarch/cornmeal case, and load_aliases.py holds the constraint that no alias resolves
--    to two rows WITHIN ONE SOURCE'S EFFECTIVE SET. The schema cannot express that and does not
--    try, the same reasoning migration 030 gave for leaving UNIQUE(alias) off.
--
-- A nullable column with no default, so SQLite adds it in place and no table is rebuilt.
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-08, in the same shape as the seven wrapped
-- on 2026-10-07 and for the same reason. These six were MISSED by that round: the rule that was
-- meant to find them split the file on ";" and dropped any fragment beginning with "--", and every
-- statement in this folder has a comment above it, so the rule counted 0 or 1 statements here and
-- reported nothing missing. Found by an independent review. See tests/test_migration_atomicity.py,
-- which now strips the comments before it counts.
-- Every database past this file is unaffected (migrate.py tracks by filename and never by
-- checksum), so this protects a FRESH INSTALL, which is the only thing that still runs it.
BEGIN;

ALTER TABLE library_aliases ADD COLUMN source_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_library_aliases_slug ON library_aliases(source_slug);

COMMIT;
