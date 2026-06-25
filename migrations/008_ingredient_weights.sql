-- 008_ingredient_weights.sql
-- A read-only reference table for Phase 1c (volume -> weight). It maps an ingredient
-- name to how many grams one millilitre of it weighs (its density), so the converter
-- can turn a volume measure ("1 cup flour") into grams. Nothing app-owned points at it;
-- it's rebuilt wholesale from the source CSV on every build (see build_db.seed_weights).
--
-- The rows come from the King Arthur Baking Ingredient Weight Chart, via
-- king-arthur-staples-v2.csv. grams_per_ml is computed at SEED time (grams / reference
-- volume in mL), not here — the migration only defines the shape.
CREATE TABLE ingredient_weights (
    lookup_key   TEXT NOT NULL,   -- normalized ingredient name (see weights.normalize)
    display_name TEXT NOT NULL,   -- original name from the chart, for display
    grams_per_ml REAL NOT NULL    -- density: grams that one mL of this ingredient weighs
);

CREATE INDEX idx_iw_lookup ON ingredient_weights(lookup_key);
