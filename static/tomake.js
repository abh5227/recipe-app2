// Derived "to make" status — client-only, NO schema and NO stored flag. A recipe is "to make"
// iff it's in the current user's box AND has never been cooked by them:
//   owner == me   (is_mine, from the /api/recipes payload)
//   && cook_count == 0
// Pure, so it's unit-tested directly (tests/js/tomake.test.js). Deliberately NOT routed through
// the category-tag system (TAG_CATEGORY/tagsHTML): a tag-based "to make" is a known footgun
// (free-type re-entry), which is exactly why this is a derived mark, not a tag.
export function isToMake(r) {
  return r != null && r.is_mine === true && (r.cook_count | 0) === 0;
}
