-- 055_import_flags_archive.sql - somewhere for a confirmed import flag to go that is not /dev/null.
--
-- ⚠️ ADDITIVE. One new table. Nothing is moved into it by this migration, which is
--    scripts/archive_import_flags.py's job, so applying it changes no row of any existing table.
--
-- ⚠️ WHY A TABLE AND NOT A DELETE. The 562 positioned flags are a finished review queue: the
--    importer recorded what it declined to guess, and the decisions have been made. Nothing reads
--    them. That is a reason to get them out of the working table, not a reason to destroy them,
--    because they are the only record of what the importer was unsure about and why. Recovery is one
--    INSERT ... SELECT back.
--
-- ⚠️ position IS DELIBERATELY NOT A POINTER ANY MORE. It records the ingredient-line slot as it stood
--    at IMPORT, and rows have been inserted, deleted and reordered since, so it names a line only by
--    accident now. Archiving is partly an admission of that: keeping the column in the live table
--    invites someone to join on it. Note the shape is preserved verbatim, including position, so the
--    archive is a faithful copy rather than an interpretation of one.
--
-- ⚠️ NO FOREIGN KEY ON recipe_id, AND THAT IS THE POINT OF AN ARCHIVE. import_flags cascades from
--    recipes, so deleting a recipe takes its flags with it. An archive that did the same would lose
--    exactly the history it exists to hold. archived_at records when the row was moved.
--
-- ⚠️ THE 2 imported_via ROWS DO NOT MOVE. app.update_recipe reads them to decide whether a recipe's
--    reason='original' baseline is captured on its first save (the U5 rule), and url_cascade writes a
--    new one on every URL import. They are live, not history. The 31 other unpositioned rows
--    (no_directions 26, no_ingredients 3, photo_only 2) stay too: they name a RECIPE rather than a
--    line, so they have not gone stale the way a position has.

CREATE TABLE import_flags_archive (
    id          INTEGER PRIMARY KEY,   -- the original import_flags.id, kept so recovery is exact
    recipe_id   TEXT    NOT NULL,
    position    INTEGER,
    flag        TEXT    NOT NULL,
    reason      TEXT,
    created_at  TEXT    NOT NULL,
    archived_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_import_flags_archive_recipe ON import_flags_archive(recipe_id);
