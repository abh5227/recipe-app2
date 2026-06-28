-- 013: per-ingredient "convert to grams in Metric?" flag.
--
-- TRUE (the default) for weigh-it staples: flours & starches, sugars & syrups, butter,
-- soft dairy / pastes, nuts & seeds, grated cheese, pourable liquids, chocolate, oats,
-- dried fruit. FALSE for raw produce / aromatics and pure cooking oils & solid fats, where
-- a volume reads far more naturally in the kitchen than a gram weight (you scoop a clove or
-- pour a glug; you don't weigh it). build_db.seed_weights sets the per-row value from the
-- King Arthur CSV; this migration only adds the column with a safe TRUE default so existing
-- rows keep converting until a rebuild repopulates them.
ALTER TABLE ingredient_weights ADD COLUMN convert_to_grams INTEGER NOT NULL DEFAULT 1;
