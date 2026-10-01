-- 045_sourced_content_resolved_basis.sql - a fourth match_basis, 'resolved', for an article a
-- person chose.
--
-- ⚠️ WHY A FOURTH VALUE RATHER THAN REUSING 'title'. 168 rows landed on a Wikipedia
--    disambiguation page and were refused rather than guessed. Settling one means reading the
--    page's options and picking the food sense, which is a judgement and not a match. Recording
--    it as 'title' would file a human decision as an automatic name hit, and the first question
--    asked of a wrong attachment is how it was reached.
--
-- ⚠️ AND IT IS THE BASIS A WRONG ATTACHMENT IS MOST LIKELY TO CARRY. Three failure modes put a
--    wrong article on a row. A P279 walk, which nothing here does. A disambiguation page, which
--    is refused. And the row's own Q-id naming a sense a cook does not mean, which is how 'mint'
--    arrived at Mint (candy) and 'squash' at Squash (drink), both by sitelink, the basis
--    described as authoritative. A sitelink is authoritative about which item links to which
--    article and says nothing about whether the item is the sense a cook means.
--
-- SQLite cannot alter a CHECK, so the table is rebuilt. Every column and every row is carried
-- across unchanged, and the index is recreated.
-- ⚠️ THIS FILE IS A TABLE REBUILD AND IT HAS TO BE ONE TRANSACTION, AND ITS PRAGMAS HAVE TO STAY
-- OUTSIDE THAT TRANSACTION. migrate.py runs each file through sqlite3's executescript, which opens
-- no transaction, so without the BEGIN below every statement auto-commits on its own. A PRAGMA
-- foreign_keys is a NO-OP inside a transaction, measured, so moving the pragma in would silently
-- run this rebuild with foreign keys ON and change what the file does. Hence the order: pragma off,
-- BEGIN, rebuild, COMMIT, pragma on. 056_wait_alongside.sql writes out the reasoning at length.
--
-- Measured by replaying this file truncated one statement after the DROP and closing the
-- connection, which is what a Ctrl-C, a laptop sleep or a crash does:
--
--   no transaction : library_sourced_content is GONE and lsc_rebuild_045 is left behind holding
--                    every row. ⚠️ AND THE RETRY IS WORSE HERE THAN ANYWHERE ELSE, because this
--                    file says CREATE TABLE IF NOT EXISTS. The retry does not fail on the leftover
--                    scratch table the way 041 and 056 do. It silently REUSES it, copies from a
--                    library_sourced_content that no longer exists or has been rebuilt, and lands a
--                    schema that looks right. A failure that errors is recoverable. This one is not
--                    announced at all.
--   this BEGIN     : the rebuild, the rename and the index land together or not at all, the
--                    scratch table never outlives the statement that made it, and re-running
--                    migrate.py applies the file cleanly.
PRAGMA foreign_keys=off;

BEGIN;

CREATE TABLE IF NOT EXISTS lsc_rebuild_045 (
    library_id          TEXT PRIMARY KEY,   -- library_names.library_id. NOT an FK, per 030.
    source              TEXT NOT NULL,      -- 'wikipedia'
    source_title        TEXT,               -- the article title as fetched
    source_url          TEXT,               -- the article URL
    source_revision     INTEGER,            -- revid, so a later refresh can see what moved
    match_basis         TEXT NOT NULL,      -- sitelink | title | redirect | resolved
    sourced_description TEXT,               -- the lead section, plain text, verbatim
    scientific_name     TEXT,               -- the binomial, when the lead states one
    license             TEXT,               -- 'CC-BY-SA-4.0'
    attribution         TEXT,
    sourced_image       TEXT,               -- the Commons filename from Wikidata P18
    image_url           TEXT,               -- a thumb URL, only filled when the license is usable
    image_license       TEXT,               -- ⚠️ NULL means DO NOT RENDER
    image_attribution   TEXT,
    fetched_at          TEXT NOT NULL,
    CHECK (match_basis IN ('sitelink','title','redirect','resolved'))
);

INSERT INTO lsc_rebuild_045
    SELECT library_id, source, source_title, source_url, source_revision, match_basis,
           sourced_description, scientific_name, license, attribution, sourced_image,
           image_url, image_license, image_attribution, fetched_at
    FROM library_sourced_content;

DROP TABLE library_sourced_content;
ALTER TABLE lsc_rebuild_045 RENAME TO library_sourced_content;
CREATE INDEX IF NOT EXISTS idx_lsc_basis ON library_sourced_content(match_basis);

COMMIT;

PRAGMA foreign_keys=on;
