-- 007_addition_sections.sql
-- An added ingredient can now belong to a SECTION of a recipe — the run of lines under
-- a given heading (e.g. "Marinade", "Dipping sauce"). That lets a new ingredient land at
-- the bottom of its own section instead of the very bottom of the whole list.
--
-- We store the section by its heading TEXT rather than a line number, so it stays put
-- when quantities or line positions change (additions still never "drift" the way a
-- position-keyed edit can). NULL means "no section": the area before the first heading,
-- or simply a recipe that has no headings at all.
ALTER TABLE recipe_additions ADD COLUMN section TEXT;
