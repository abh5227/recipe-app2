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
ALTER TABLE library_aliases ADD COLUMN source_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_library_aliases_slug ON library_aliases(source_slug);
