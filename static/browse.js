// Pure browse-list logic — what a search query matches, and how the four sorts order.
// No DOM and no fetch, so it is unit-tested directly (tests/js/browse.test.js), the same pattern
// static/tomake.js follows. renderHome imports these and re-runs them over the already-loaded
// /api/recipes array: all 298 recipes arrive in one payload, so filtering and sorting are in-memory
// and instant. There is no search or sort endpoint and none is needed.

// The card's tag list, and the SAME list the search reads. "Made" is excluded on purpose: 150 of
// 298 recipes carry it, cooked state is read from cook_count instead, and a tag the user cannot
// see should not silently match their query.
export function cardTags(r) {
  return String((r && r.category) || "")
    .split("·")
    .map((t) => t.trim())
    .filter((t) => t && t.toLowerCase() !== "made");
}

// Everything a query is matched against: the name, who it came from, and the visible tags.
export function searchText(r) {
  if (r == null) return "";
  return [r.name, r.author, ...cardTags(r)].filter(Boolean).join(" ").toLowerCase();
}

// Case-insensitive substring. An empty or whitespace-only query matches everything.
export function matchesQuery(r, q) {
  const needle = String(q == null ? "" : q).trim().toLowerCase();
  if (!needle) return true;
  return searchText(r).includes(needle);
}

// "2026-07-25" -> "Jul 2026". Deliberately string-sliced rather than routed through Date, so it
// cannot drift by a day across time zones the way a parsed date can.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function monthYear(iso) {
  const m = /^(\d{4})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  const mi = Number(m[2]) - 1;
  return mi >= 0 && mi < 12 ? `${MONTHS[mi]} ${m[1]}` : "";
}

// The four sorts. Name is the DEFAULT and is also every other sort's tie-breaker, so the order is
// total and a re-render never reshuffles equal rows. Missing values sort LAST in the three
// descending modes: an unrated recipe reads as 0, a never-cooked one as 0, and a recipe with no
// last-cooked date as the empty string, which is smaller than any real 'YYYY-MM-DD'.
const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""));
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

export const SORT_MODES = ["name", "rating", "cooks", "last"];

const COMPARATORS = {
  name: byName,
  rating: (a, b) => num(b.rating) - num(a.rating) || byName(a, b),
  cooks: (a, b) => num(b.cook_count) - num(a.cook_count) || byName(a, b),
  last: (a, b) => String(b.last_cooked || "").localeCompare(String(a.last_cooked || "")) || byName(a, b),
};

// Returns a NEW array; the caller's list is never reordered in place.
export function sortRecipes(list, mode) {
  const cmp = COMPARATORS[mode] || COMPARATORS.name;
  return [...(list || [])].sort(cmp);
}

// Search then sort. The one entry point renderHome calls, so the two can never be applied in the
// wrong order or with different rules than the tests pin.
export function browseList(list, query, mode) {
  return sortRecipes((list || []).filter((r) => matchesQuery(r, query)), mode);
}
