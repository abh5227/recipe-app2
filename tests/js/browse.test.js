"use strict";
// Pins the browse list's search and sort (static/browse.js). Two things here are
// silent-regression-prone and asserted explicitly: the "Made" tag must never be searchable (it is
// hidden on the card, so matching it would filter on something the user cannot see), and missing
// values must sort LAST rather than floating to the top of a descending list. Pure — runs under
// bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cardTags, searchText, matchesQuery, monthYear, sortRecipes, browseList, SORT_MODES,
} from "../../static/browse.js";

const R = (o) => ({ name: "", author: "", category: "", rating: 0, cook_count: 0, last_cooked: null, ...o });
const names = (list) => list.map((r) => r.name);

/* ---------- tags ---------- */

test("cardTags: splits on the middot, trims, drops empties", () => {
  assert.deepEqual(cardTags(R({ category: "Thai · Chicken" })), ["Thai", "Chicken"]);
  assert.deepEqual(cardTags(R({ category: "  Bread  ·· Sides " })), ["Bread", "Sides"]);
  assert.deepEqual(cardTags(R({ category: "" })), []);
  assert.deepEqual(cardTags(R({ category: null })), []);
  assert.deepEqual(cardTags(null), [], "defensive: no row at all");
});

test('cardTags: "Made" is dropped, in any casing', () => {
  assert.deepEqual(cardTags(R({ category: "Made · Thai" })), ["Thai"]);
  assert.deepEqual(cardTags(R({ category: "made · Thai" })), ["Thai"]);
  assert.deepEqual(cardTags(R({ category: "MADE" })), []);
  assert.deepEqual(cardTags(R({ category: "Homemade" })), ["Homemade"], "substring is NOT a match");
});

/* ---------- search ---------- */

test("matchesQuery: name, author and tags all match, case-insensitively", () => {
  const r = R({ name: "Gai Yang", author: "Leela Punyaratabandhu", category: "Thai · Chicken" });
  assert.equal(matchesQuery(r, "gai"), true, "name");
  assert.equal(matchesQuery(r, "GAI"), true, "name, upper");
  assert.equal(matchesQuery(r, "leela"), true, "author");
  assert.equal(matchesQuery(r, "thai"), true, "tag");
  assert.equal(matchesQuery(r, "chick"), true, "substring of a tag");
  assert.equal(matchesQuery(r, "yan"), true, "substring mid-name");
  assert.equal(matchesQuery(r, "pizza"), false, "no match");
});

test("matchesQuery: an empty query matches everything", () => {
  const r = R({ name: "Anything" });
  for (const q of ["", "   ", null, undefined]) {
    assert.equal(matchesQuery(r, q), true, `empty query ${JSON.stringify(q)} -> match`);
  }
});

test('matchesQuery: "Made" is NOT searchable — the card never shows it', () => {
  const r = R({ name: "Aloo Gobhi", author: "Madhur Jaffrey", category: "Made · Indian" });
  assert.equal(matchesQuery(r, "made"), false, "the hidden tag must not match");
  assert.equal(matchesQuery(r, "indian"), true, "its visible sibling still matches");
  // "Madhur" contains "mad" — the author is still searchable, so this is an exclusion of the TAG,
  // not a blanket ban on the letters.
  assert.equal(matchesQuery(r, "madhur"), true, "author still matches");
});

test("searchText: is exactly name + author + visible tags", () => {
  const r = R({ name: "Bulgogi", author: "Maangchi", category: "Made · Korean · Beef" });
  assert.equal(searchText(r), "bulgogi maangchi korean beef");
});

/* ---------- monthYear ---------- */

test("monthYear: YYYY-MM-DD -> 'Mon YYYY', and nothing for junk", () => {
  assert.equal(monthYear("2026-07-25"), "Jul 2026");
  assert.equal(monthYear("2026-01-01"), "Jan 2026");
  assert.equal(monthYear("2026-12-31"), "Dec 2026");
  for (const bad of [null, undefined, "", "nope", "2026", "2026-13-01"]) {
    assert.equal(monthYear(bad), "", `junk ${JSON.stringify(bad)} -> empty`);
  }
});

/* ---------- sort ---------- */

const LIST = [
  R({ name: "Cherry",  rating: 3, cook_count: 1, last_cooked: "2026-01-05" }),
  R({ name: "Apple",   rating: 5, cook_count: 9, last_cooked: "2026-08-04" }),
  R({ name: "Banana",  rating: 0, cook_count: 0, last_cooked: null }),
  R({ name: "date",    rating: 3, cook_count: 1, last_cooked: "2026-03-11" }),
];

test("sort name: A to Z, and it is the DEFAULT", () => {
  assert.deepEqual(names(sortRecipes(LIST, "name")), ["Apple", "Banana", "Cherry", "date"]);
  assert.deepEqual(names(sortRecipes(LIST, undefined)), ["Apple", "Banana", "Cherry", "date"], "no mode -> name");
  assert.deepEqual(names(sortRecipes(LIST, "nonsense")), ["Apple", "Banana", "Cherry", "date"], "bad mode -> name");
  assert.equal(SORT_MODES[0], "name", "name is first in the control's order");
});

test("sort rating: descending, unrated LAST, ties by name", () => {
  assert.deepEqual(names(sortRecipes(LIST, "rating")), ["Apple", "Cherry", "date", "Banana"]);
});

test("sort cooks: descending, never-cooked LAST, ties by name", () => {
  assert.deepEqual(names(sortRecipes(LIST, "cooks")), ["Apple", "Cherry", "date", "Banana"]);
});

test("sort last: most recent first, NO date sorts LAST", () => {
  assert.deepEqual(names(sortRecipes(LIST, "last")), ["Apple", "date", "Cherry", "Banana"]);
});

test("sort: returns a new array and never reorders the caller's", () => {
  const before = names(LIST);
  const out = sortRecipes(LIST, "rating");
  assert.notEqual(out, LIST, "a new array");
  assert.deepEqual(names(LIST), before, "the input is untouched");
});

test("sort: missing fields entirely are treated as zero, not NaN", () => {
  const odd = [R({ name: "Zed" }), { name: "Nil" }, R({ name: "Ace", rating: 4 })];
  assert.deepEqual(names(sortRecipes(odd, "rating")), ["Ace", "Nil", "Zed"], "NaN must not poison the order");
});

/* ---------- compose ---------- */

test("browseList: search and sort compose", () => {
  const list = [
    R({ name: "Thai Curry",   rating: 2, category: "Thai" }),
    R({ name: "Thai Basil",   rating: 5, category: "Thai" }),
    R({ name: "Roman Pasta",  rating: 4, category: "Italian" }),
  ];
  assert.deepEqual(names(browseList(list, "thai", "rating")), ["Thai Basil", "Thai Curry"]);
  assert.deepEqual(names(browseList(list, "thai", "name")), ["Thai Basil", "Thai Curry"]);
  assert.deepEqual(names(browseList(list, "", "rating")), ["Thai Basil", "Roman Pasta", "Thai Curry"]);
  assert.deepEqual(names(browseList(list, "nothing here", "name")), [], "no matches -> empty");
});

test("browseList: a tag query filters, and Made never does", () => {
  const list = [
    R({ name: "One", category: "Made · Thai" }),
    R({ name: "Two", category: "Italian" }),
  ];
  assert.deepEqual(names(browseList(list, "thai", "name")), ["One"]);
  assert.deepEqual(names(browseList(list, "made", "name")), [], "Made matches nothing");
});
