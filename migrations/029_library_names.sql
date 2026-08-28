-- 029_library_names.sql
-- Add-on-save ingredient linking, stage 1: the library_names lookup table. It maps an ingredient
-- library row's id to that row's canonical name, and it exists so a later stage's save path can create
-- an `ingredients` row from a library link WITHOUT opening the two databases the library is derived
-- from (join.db at 894 MB and sources.db at 5.18 GB, both gitignored and neither ever present on a
-- server). app.py has no access to either today, and this table is what keeps that true.
--
-- TWO COLUMNS, AND THE MISSING THIRD IS A DECISION. An earlier draft carried a `slug` column plus an
-- index on it, to serve the reverse slug -> library_id lookup that promoting a step's [[key]] link
-- would need. Step-link promotion is DROPPED, so nothing needs the reverse direction and the column
-- goes with it. Measured on the current 10,527-row library: two columns is 624 KB, the slug-plus-index
-- version is 1,044 KB, against a recipes.db of 3,476 KB.
-- ⚠️ IF STEP-LINK PROMOTION EVER COMES BACK it needs the slug column and its index, and the reverse
--    lookup is NOT a function: 63 slugs map to 129 library rows (bacon is 3 of them, ice cream another
--    3), so it would have to refuse on ambiguity rather than pick one.
--
-- INERT. Nothing reads this table. The loader is stage 3 and it reads a gitignored server-side file, so
-- a fresh clone and CI both get an EMPTY table. That emptiness is the point rather than a gap: the save
-- gate's create branch (stage 5) can only match a row that is present, so with no rows it never fires
-- and the gate keeps behaving exactly as it does now. Postgres lands in the same state, where the
-- Alembic revision creates the table and nothing populates it.
--
-- library_id is the library row's own id and it is NOT always a Q-id. Measured over the 10,527 kept
-- rows: 61.1% are Wikidata Q-ids, 38.4% are Open Food Facts ids shaped 'en:egg-pasta', 0.5% are
-- authored slugs, and 4 rows are wiktextract keys. One TEXT PK covers all four shapes. The ids are
-- globally unique and collide with none of the 36 ingredients slugs.
-- The Alembic revision mirrors this for Postgres.

CREATE TABLE library_names (
    library_id TEXT PRIMARY KEY,   -- the library row's id ('Q1063736', 'en:egg-pasta', 'salt')
    canonical  TEXT NOT NULL       -- its chosen display name, the later source of ingredients.name
);
