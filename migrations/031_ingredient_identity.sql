-- 031_ingredient_identity.sql
-- The Panel, stage 1: split ingredient identity into a ROW key and a CONCEPT key (Option D, decided in
-- docs/panel-design.md). `ingredients.id` was doing two jobs at once, saying which row this is AND which
-- concept it is, and the panel model needs those to differ: a user's personal gochujang and the shared
-- gochujang are two rows for one concept.
--
-- ⚠️ `id` DOES NOT CHANGE, AND THAT IS THE WHOLE POINT OF OPTION D. It stays the row key, so the 50
--    stored links in recipe_ingredients keep resolving, and the 30 `[[key]]`s sitting inside recipe
--    prose (`[[bread_flour|flour]]`, `[[potato|potatoes]]`) stay human-authorable. A surrogate integer
--    key would have broken both. Decision B (approval promotes a personal row in place by flipping
--    owner to NULL) also depends on this: the id and the concept both survive the flip, so nothing has
--    to be re-pointed.
--
-- ⚠️ `concept` IS "NOT NULL DEFAULT ''" FOR A SQLite REASON, NOT A DESIGN ONE. The design says a plain
--    `concept TEXT NOT NULL`. SQLite refuses to ADD a NOT NULL column to a populated table without a
--    default ("Cannot add a NOT NULL column with default value NULL"), and the usual escape, the
--    table-rebuild pattern of 019, is NOT available here: 019 says in as many words that it was safe
--    "because nothing FKs INTO ratings", whereas recipe_ingredients (3,555 rows), ingredient_seasons
--    (65) and ingredient_regions (102) all FK into ingredients, and a DROP with foreign_keys ON fails
--    outright. So the '' is a transient artifact that the UPDATE below immediately overwrites, and the
--    no-empty-concept test guards that nothing ever writes it again. Same shape as recipes.source and
--    ingredients.source, both of which were added by ALTER with a NOT NULL default.
--
-- ⚠️ TWO INDEXES, AND ONE ALONE IS NOT ENOUGH. Measured: `UNIQUE(owner, concept)` by itself permits TWO
--    shared rows with the same concept, because SQLite treats NULLs as distinct in a unique index, so
--    (NULL,'garlic') and (NULL,'garlic') do not collide. The partial index on concept WHERE owner IS
--    NULL is what makes one-shared-per-concept true. Together they give the four behaviors the model
--    needs: one shared row per concept, one personal row per concept per user, a shared and a personal
--    row for the same concept coexisting, and two users each holding their own.
--
-- BACKFILL: every existing row is shared and its id is already a name slug, so concept = id and
-- owner = NULL is correct for all 36. No id changes, no row moves.
--
-- INERT. Nothing reads concept or owner yet. The effective-library read is stage 2 and the create path
-- is stage 3. This migration adds the shape and nothing else.
-- The Alembic revision mirrors this for Postgres.

ALTER TABLE ingredients ADD COLUMN concept TEXT NOT NULL DEFAULT '';   -- '' is transient, see above
ALTER TABLE ingredients ADD COLUMN owner   INTEGER REFERENCES users(id);   -- NULL = shared

UPDATE ingredients SET concept = id WHERE concept = '';

CREATE UNIQUE INDEX idx_ingredients_owner_concept  ON ingredients(owner, concept);
CREATE UNIQUE INDEX idx_ingredients_shared_concept ON ingredients(concept) WHERE owner IS NULL;
