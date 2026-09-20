-- 044_sourced_content.sql - Wikipedia lead text, scientific name and Commons image, as a
-- SEPARATE layer beside the handwritten description.
--
-- ⚠️ THE HANDWRITTEN TEXT IS NEVER WRITTEN HERE AND NEVER READ FROM HERE. ingredients.descr is
--    the handwritten layer and this table does not touch it. Precedence at render time is
--    handwritten, then sourced, then blank.
--
-- ⚠️ image_license IS THE GATE, NOT A NOTE. A NULL means the file's rights have not been read or
--    were read and are not usable, and a row with a NULL image_license MUST NOT render its image.
--    Commons licences vary file by file and a filename alone grants nothing.
--
-- ⚠️ THE TEXT IS A PRIVATE DEVELOPMENT STARTER. It is CC-BY-SA and is replaced by handwritten copy
--    before anything is published, so ShareAlike never triggers on distribution. The attribution is
--    stored anyway, because it is correct while the text is present and costs one column.
--
-- ⚠️ match_basis RECORDS HOW THE ARTICLE WAS REACHED and exists so a wrong attachment is findable.
--    'sitelink' is authoritative. 'title' matched the row's own name. 'redirect' arrived through a
--    redirect and is the weakest. NOTHING is reached by walking P279: following subclass edges puts
--    the Vegetable article on onion and the Fruit article on tomato, which looks like a success and
--    is not one.
CREATE TABLE IF NOT EXISTS library_sourced_content (
    library_id          TEXT PRIMARY KEY,   -- library_names.library_id. NOT an FK, per 030.
    source              TEXT NOT NULL,      -- 'wikipedia'
    source_title        TEXT,               -- the article title as fetched
    source_url          TEXT,               -- the article URL
    source_revision     INTEGER,            -- revid, so a later refresh can see what moved
    match_basis         TEXT NOT NULL,      -- sitelink | title | redirect
    sourced_description TEXT,               -- the lead section, plain text, verbatim
    scientific_name     TEXT,               -- the binomial, when the lead states one
    license             TEXT,               -- 'CC-BY-SA-4.0'
    attribution         TEXT,
    sourced_image       TEXT,               -- the Commons filename from Wikidata P18
    image_url           TEXT,               -- a thumb URL, only filled when the licence is usable
    image_license       TEXT,               -- ⚠️ NULL means DO NOT RENDER
    image_attribution   TEXT,
    fetched_at          TEXT NOT NULL,
    CHECK (match_basis IN ('sitelink','title','redirect'))
);
CREATE INDEX IF NOT EXISTS idx_lsc_basis ON library_sourced_content(match_basis);
