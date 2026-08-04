// The SHARED hero caption (Stage 4 hero-caption slot). The hero Polaroid points at recipes.image; when that
// path is a promoted cook photo, the recipe payload's photos array flags it is_hero WITH its caption. So the
// hero shows "the caption of the is_hero photo" — NO schema, NO new field: promoting a captioned photo carries
// its caption for free, and editing that photo's caption (via the 3c ⋮ menu) updates the hero on renderRecipe
// (it's the same field, re-read). Returns the caption string, or null when there's no captioned cook-photo hero
// — an uncaptioned hero, or a legacy/backfilled hero with no matching cook_photo row — so the hero renders
// image-only, as before. Pure, so it's unit-tested directly (tests/js/hero-caption.test.js).
export function heroCaption(photos) {
  const hero = (photos || []).find((p) => p && p.is_hero);
  return hero && hero.caption ? hero.caption : null;
}
