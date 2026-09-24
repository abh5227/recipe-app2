-- 048_ratings_cluster.sql - a rating is a cooking's verdict, not a verdict on the recipe.
--
-- ⚠️ THE MODEL. Each logged cook carries its own rating. The recipe's headline number is the AVERAGE
--    of its rated cooks. INPUT is per-cook (the log-cook box, and stars on each cook-log row); DISPLAY
--    is the average, read-only, everywhere. Under the old shape ratings was keyed (recipe_id, user_id),
--    so one rating existed per recipe and rating a fourth cook overwrote the verdict on the first three.
--
-- ⚠️ WHY A COLUMN ON cook_log AND NOT A RE-KEYED ratings TABLE. A cook row already carries the date,
--    the source, its photos (cook_photos.cook_log_id) and a recipe-state snapshot, so the verdict and
--    the caption belong on the row the evidence already hangs off. Re-keying ratings to include
--    cook_log_id would need the full create-copy-drop-rename rebuild migration 019 did, on a live user
--    table, and would leave a parallel table duplicating one foreign key. A nullable ADD COLUMN with a
--    CHECK is accepted in place by SQLite (tested on 3.45.3), so nothing is rebuilt here.
--
-- ⚠️ THE ratings TABLE IS LEFT FROZEN, NOT DROPPED. All 120 rows stay exactly as they are. Nothing
--    reads or writes it after this migration, so it cannot drift, and it is the rollback for the
--    backfill without reaching for a backup file. A LATER migration drops it once the new path has
--    been used. Do not add reads or writes to it.
--
-- ⚠️ THE HALF-STEP CHECK IS AN EXPLICIT IN-LIST, deliberately. The arithmetic form
--    (rating * 2 = CAST(rating * 2 AS INT)) relies on rounding behavior that differs between SQLite
--    and Postgres. Every half value is exactly representable in binary floating point, so equality
--    against a literal list is safe and says what it means. Existing whole values need no data
--    migration: 4 and 4.0 are the same number.
--
-- ⚠️ rated_at IS SEPARATE FROM cooked_on ON PURPOSE. The verdict's timestamp is not the cook's date.
--    Collapsing them would lose the fact that 108 of the existing ratings were stamped in one bulk
--    import on 2026-07-01, long after the cooks they describe.
--
-- The existing recipes.db is migrated by scripts/backfill_percook_ratings.py (data-coupled: it moves
-- the ratings rows onto their cooks by a 5-clause rule), which stamps THIS migration as applied there
-- so build_db does not run it twice. On a fresh build cook_log is empty and the columns start NULL.
-- An Alembic revision mirrors this for Postgres.

ALTER TABLE cook_log ADD COLUMN rating REAL
    CHECK (rating IS NULL OR rating IN (0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5));
ALTER TABLE cook_log ADD COLUMN rated_at TEXT;
ALTER TABLE cook_log ADD COLUMN caption TEXT
    CHECK (caption IS NULL OR LENGTH(caption) <= 60);

-- The headline average is AVG(rating) over a recipe's rated cooks, per user, at two call sites
-- (app.py's list_recipes subquery and recipe_stats). Both filter rating IS NOT NULL, so this partial
-- index backs exactly the rows they read. idx_cook_log_recipe already covers the unfiltered scans.
CREATE INDEX IF NOT EXISTS idx_cook_log_rating ON cook_log(recipe_id, user_id) WHERE rating IS NOT NULL;


-- A dated observation of what ONE WEB PAGE displayed, captured on import. ⚠️ THIS IS NOT ANDY'S
-- RATING AND NEVER AVERAGES WITH IT. url_jsonld.py keeps "rating": 0 and that comment stands. See
-- ROADMAP.md "Source rating snapshot" (2026-09-16): the timestamp is part of the claim rather than
-- metadata beside it, so a snapshot with its date stripped off is a different and false claim.
--
-- ⚠️ A TABLE, NOT COLUMNS ON recipes, so a re-import in a year records a SECOND observation instead
--    of destroying the first. Several rows per recipe is the point, hence a surrogate id PK.
--
-- ⚠️ scale_assumed RECORDS THAT THE 5-POINT SCALE WAS A GUESS. bestRating is absent from all 7
--    fixtures that carry a rating, so the flag is 1 in every real case today. A 9.2 from a 10-point
--    source stored as 9.2 out of 5 is a false claim, and this flag is how a display knows not to
--    make it. int-boolean (0/1), the is_heading/is_admin idiom.
CREATE TABLE recipe_source_ratings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id     TEXT    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    value         REAL    NOT NULL,                      -- the published average, coerced from JSON-LD
    rating_count  INTEGER,                               -- reviews behind it (ratingCount or reviewCount)
    scale         REAL    NOT NULL DEFAULT 5,            -- bestRating when the page states one
    scale_assumed INTEGER NOT NULL DEFAULT 1,            -- int-boolean: 1 = the page did not state bestRating
    source_url    TEXT,                                  -- the page this describes
    source_name   TEXT,                                  -- its host, for display
    captured_at   TEXT    NOT NULL                       -- now_utc(): when the page said it
);

CREATE INDEX idx_recipe_source_ratings_recipe ON recipe_source_ratings(recipe_id);
