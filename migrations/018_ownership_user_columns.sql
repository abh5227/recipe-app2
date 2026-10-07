-- 018_ownership_user_columns.sql
-- Rescoping R1 (docs/product-vision.md — the recipe-box model): add the ownership / per-user columns.
-- PURELY ADDITIVE and NULLABLE — nothing reads them yet. A fresh build has no user to own seed recipes,
-- and the routes are gated so new writes always have a current_user; R2 backfills existing rows to me,
-- create/copy set owner=current_user, and the cook/rating writers set user_id=current_user (R4). The
-- ratings PK stays (recipe_id) here — the composite (recipe_id, user_id) PK rebuild is R3; adding a
-- nullable column to ratings is a plain in-place ADD COLUMN (no table rebuild). All three are reference
-- FKs to users(id) with NO cascade, matching auth-1's created_by/used_by. This is the SQLite half of
-- the dual schema source; an Alembic revision mirrors it for Postgres.
--
-- ⚠️ ONE TRANSACTION, BECAUSE executescript OPENS NONE. migrate.py applies each file with
-- sqlite3's executescript, which auto-commits every statement on its own, so an interrupted run
-- left some of the statements below applied with the filename UNRECORDED, and the retry then died
-- forever on "duplicate column name". Wrapped 2026-10-07. Every database past this file is
-- unaffected (migrate.py tracks by filename and never by checksum), so this protects a FRESH
-- INSTALL, which is the only thing that still runs it. See tests/test_migration_atomicity.py.
BEGIN;

ALTER TABLE recipes  ADD COLUMN owner   INTEGER REFERENCES users(id);
ALTER TABLE cook_log ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE ratings  ADD COLUMN user_id INTEGER REFERENCES users(id);

COMMIT;
