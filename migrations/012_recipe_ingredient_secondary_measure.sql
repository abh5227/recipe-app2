-- 012_recipe_ingredient_secondary_measure.sql
-- A dual-measure ingredient line carries BOTH a volume and a weight (e.g.
-- "1 cup (250 g) flour" or "100 g (1 cup) sugar"). Migration 011 gave us recipe_ingredients.grams
-- for the WEIGHT; this column holds the OTHER measure — the VOLUME — so a line's two measures are
-- both captured, regardless of which one the source wrote first.
--
-- CAPTURE ONLY for now: written at import, not yet displayed. A later step wires a toggle to show
-- the volume (Imperial) vs. the grams (Metric). Nullable: most lines have only one measure.
ALTER TABLE recipe_ingredients ADD COLUMN secondary_measure TEXT;
