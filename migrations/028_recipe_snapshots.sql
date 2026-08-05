-- 028_recipe_snapshots.sql
-- Change-tracking stage 1: recipe_snapshots — a versioned JSON-blob snapshot of a recipe's editable
-- CONTENT, captured when a cook is logged (reason='cook'; a manual "save a version" is stage 2). The
-- Cooking Journal's foundation (HYBRID model): snapshots are the STORED TRUTH; the "specific changes" are
-- DERIVED by diffing consecutive snapshots later (stage 3), and materialized for note-linkage later
-- (stage 4). Stage 1 only WRITES snapshots — nothing reads them yet.
--
-- Purely ADDITIVE: a plain CREATE TABLE — no existing-table change, and NO data backfill. Retroactive
-- snapshots are IMPOSSIBLE (past recipe-states weren't retained by the destructive edit path
-- write_recipe_rows, so there's nothing to reconstruct), so tracking starts FRESH at the first cook after
-- this ships; existing cooks simply have no snapshot.
--
-- cook_log_id ON DELETE CASCADE: undoing a cook (undo_cook deletes the cook_log row) removes ITS snapshot
-- — the snapshot was "the version I cooked for THIS cook," so it goes with the cook (no explicit handling
-- in undo_cook; the FK cascade does it, same as cook_photos). NULLABLE for the stage-2 manual snapshot (no
-- cook). recipe_id ON DELETE CASCADE keeps it consistent when a recipe is deleted. user_id is a reference
-- FK (no cascade), the interim multi-user-shaped rule (like cook_log.user_id / cook_photos.user_id).
-- The Alembic revision mirrors this for Postgres.

CREATE TABLE recipe_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   TEXT    NOT NULL REFERENCES recipes(id)  ON DELETE CASCADE,   -- TEXT = recipes.id
    cook_log_id INTEGER          REFERENCES cook_log(id) ON DELETE CASCADE,   -- the cook it belongs to (NULL for manual, stage 2)
    user_id     INTEGER NOT NULL REFERENCES users(id),                        -- who triggered it (reference FK, no cascade)
    reason      TEXT    NOT NULL,                                             -- 'cook' | 'manual'
    content     TEXT    NOT NULL,                                             -- the JSON-blob recipe content (serialize_recipe_content)
    created_at  TEXT    NOT NULL                                              -- now_utc(): a real UTC timestamp (cook_log has only a date)
);

CREATE INDEX idx_recipe_snapshots_recipe   ON recipe_snapshots(recipe_id, created_at);   -- per-recipe history (stage-3 consecutive-snapshot diff)
CREATE INDEX idx_recipe_snapshots_cook_log ON recipe_snapshots(cook_log_id);             -- the cook <-> snapshot link
