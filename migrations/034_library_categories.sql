-- 034_library_categories.sql
-- The category vocabulary and the relation edges it hangs off. Decided in
-- previews/category-vocabulary-final.md, which is the spec this implements.
--
-- INERT. Nothing reads these tables. The app read path is Phase 4 and is not built, so a fresh
-- clone and CI get two empty tables and no page changes. Same shape as 029 through 033.
--
-- ⚠️ library_categories HOLDS ONLY THE FILTER VOCABULARY, and that is the whole design.
--    A FILTER category is browsable and is NOT a catalog row: 'allium', 'root vegetable', 'herb'.
--    About 80 of those, and they need a table because nothing else holds them.
--    A kind_of PARENT is already a catalog row: 'apple' has 254 cultivar children and IS
--    library_names.Q89. It needs no vocabulary entry, and a first draft of this migration gave it
--    one plus an is_filter=0 flag. Both were dead weight: flour's 65 edges pointed at Q36465 and
--    its library_categories row was referenced by nothing.
--
--    So "is X a kind_of parent?" is DERIVED, not stored: does any kind_of edge point at X's
--    library_id. There is no is_filter column, because everything in this table is a filter.
--
--    ⚠️ The browsable-versus-hierarchy distinction is still real and still load-bearing. 192 kind_of
--    parents against 80 filter categories, and before it existed 133 of them were being dropped,
--    discarding 3,197 edges. It is recorded in previews/category-vocabulary-final.md and expressed
--    here by WHICH TABLE a parent lives in rather than by a flag.
--
-- ⚠️ library_relations.parent_id IS NOT A FOREIGN KEY, for migration 030's reason exactly. It holds
--    EITHER a library_names.library_id (kind_of, made_from) OR a library_categories.category_id
--    (in_category), and library ids are not durable across a rebuild: the pasta anchor rule in
--    460cae5 destroyed 7 in one commit. A dangling edge degrades a lookup and breaks no page.
--
-- ⚠️ THE CANONICAL SNAPSHOTS ARE THE RECONCILE, reusing the pattern library_entries already proves
--    (52 of 56 'linked', 1 'canonical_drift', 0 dangling). A re-keyed row is then diagnosable by
--    reading the edge rather than by re-deriving it.
--
-- ⚠️ THE FOLD GUARD IS NOW A LIVE STANDING RULE, AND IT WAS NOT BEFORE. Phase C could run without
--    it precisely because no edges existed. After this migration every fold can break an edge, and
--    Phase C also proved a fold with a wrong anchor is a SILENT no-op. Both failure modes are
--    quiet, so any future fold must check both endpoints for edges AND post-check that the row
--    count moved by the expected amount.
--
-- FORMS INHERIT AND ARE NEVER CATEGORIZED DIRECTLY. garlic powder is made_from garlic, which is an
-- allium, so it reaches the category through its parent. A direct edge would be the almond-flour
-- error one layer up: 'almond flour is a kind of almond'.
-- The Alembic revision mirrors this for Postgres.

CREATE TABLE library_categories (
  category_id  TEXT PRIMARY KEY,          -- slug, e.g. 'allium'
  name         TEXT NOT NULL,             -- display name
  parent_slug  TEXT,                      -- categories nest. NOT an FK, same reasoning.
  note         TEXT                       -- why it is what it is
);

CREATE TABLE library_relations (
  child_id          TEXT NOT NULL,        -- library_names.library_id. NOT an FK, per 030.
  parent_id         TEXT NOT NULL,        -- a library_id, or a library_categories.category_id
  kind              TEXT NOT NULL,        -- 'kind_of' | 'in_category' | 'made_from'
  child_canonical   TEXT,                 -- dual-key snapshot
  parent_canonical  TEXT,                 -- dual-key snapshot
  source            TEXT NOT NULL,        -- possible_parent | prose | wikidata | off | read
  confidence        TEXT NOT NULL,        -- authored | read | high | picked
  note              TEXT,
  PRIMARY KEY (child_id, parent_id, kind),
  CHECK (kind IN ('kind_of','in_category','made_from'))
);

CREATE INDEX idx_lr_parent ON library_relations(parent_id, kind);
CREATE INDEX idx_lr_child  ON library_relations(child_id);
