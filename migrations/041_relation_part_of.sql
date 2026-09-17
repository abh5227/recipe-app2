-- 041_relation_part_of.sql
-- Add 'part_of' to the relation kinds library_relations will accept.
--
-- ⚠️ 865 CLAIMS CANNOT BE STORED WITHOUT THIS. The CHECK reads
--    kind IN ('kind_of','in_category','made_from'), and sources.db holds 815 Wikidata P527
--    (has part) and 50 P361 (part of) claims where BOTH ends are already catalog rows. Today
--    they have nowhere to go: `cinnamon stick` to `cinnamon` and `chicken drumstick` to
--    `chicken leg` are part-of facts, and forcing them into kind_of would state that a
--    cinnamon stick is a KIND of cinnamon, which is a different and wrong claim.
--
-- ⚠️ WHY THE THIRD KIND EARNS ITS PLACE RATHER THAN BEING TIDINESS. docs/parent-child-gap.md
--    records that the relationship model stayed unbuilt because honey's 37 varietal children
--    and sesame oil's 4 distinct products are different relationships and nothing separated
--    them. The sources separate them already: P279 is subclass, P186 is made from, P527 and
--    P361 are part of. Loading only kind_of would flatten back out the exact distinction that
--    file is waiting for.
--
-- ⚠️ THE SCRATCH TABLE IS NOT NAMED library_relations_new, AND THAT IS NOT COSMETIC. The parity
--    test test_every_sqlite_migration_has_an_alembic_revision reads CREATE TABLE statements out
--    of these files and demands an Alembic counterpart for anything named library_* or mined_*.
--    It cannot tell a transient rebuild table from a real one, and it should not have to, so the
--    scratch table is named outside both prefixes. It exists for three statements and is renamed
--    away before the file ends.
--
-- ⚠️ SQLITE CANNOT ALTER A CHECK CONSTRAINT, so the table is rebuilt: create, copy, drop,
--    rename, and recreate both indexes because DROP TABLE takes its indexes with it. The column
--    list is copied explicitly rather than with SELECT *, so a future column added to one side
--    and not the other fails here instead of silently shifting values across.
--
-- ⚠️ NOTHING REFERENCES library_relations BY FOREIGN KEY, checked before writing this: no table
--    in the schema carries REFERENCES library_relations. The rename is therefore safe under
--    PRAGMA foreign_keys = ON, which migrate.py sets.
--
-- ⚠️ IT PRESERVES EVERY EXISTING ROW. The copy is unconditional and the CHECK only widens, so no
--    row can fail it. A count assertion runs in the dry-run rather than here, because a
--    migration that raises leaves a half-built schema.

CREATE TABLE relations_rebuild_041 (
  child_id          TEXT NOT NULL,        -- library_names.library_id. NOT an FK, per 030.
  parent_id         TEXT NOT NULL,        -- a library_id, or a library_categories.category_id
  kind              TEXT NOT NULL,        -- 'kind_of' | 'in_category' | 'made_from' | 'part_of'
  child_canonical   TEXT,                 -- dual-key snapshot
  parent_canonical  TEXT,                 -- dual-key snapshot
  source            TEXT NOT NULL,        -- possible_parent | prose | wikidata | off | read
  confidence        TEXT NOT NULL,        -- authored | read | high | picked
  note              TEXT,
  PRIMARY KEY (child_id, parent_id, kind),
  CHECK (kind IN ('kind_of','in_category','made_from','part_of'))
);

INSERT INTO relations_rebuild_041
    (child_id, parent_id, kind, child_canonical, parent_canonical, source, confidence, note)
SELECT child_id, parent_id, kind, child_canonical, parent_canonical, source, confidence, note
FROM library_relations;

DROP TABLE library_relations;

ALTER TABLE relations_rebuild_041 RENAME TO library_relations;

CREATE INDEX idx_lr_parent ON library_relations(parent_id, kind);
CREATE INDEX idx_lr_child  ON library_relations(child_id);
