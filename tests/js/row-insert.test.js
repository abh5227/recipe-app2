"use strict";
// Pins B's insert arithmetic: "above row i" lands at i, "below row i" lands at i + 1, and anything
// that isn't a real row of a list that long refuses rather than guessing. Pure transform in
// static/row-insert.js, so this runs under bare `node --test`.
//
// What these tests CANNOT cover, and is therefore click-through-only: app.js is not node-importable
// (it touches document/window at module scope), so the TipTap re-mount rebinding after a mid-list
// step insert, where the caret lands, and the menu's own open/close behaviour are all verified in the
// browser, not here. Counting them as unit tests would be padding.
import { test } from "node:test";
import assert from "node:assert/strict";
import { insertIndexFor } from "../../static/row-insert.js";

test("above lands AT the row, below lands after it", () => {
  assert.equal(insertIndexFor("above", 3, 8), 3);
  assert.equal(insertIndexFor("below", 3, 8), 4);
});

test("boundary: above the FIRST row inserts at the very top", () => {
  assert.equal(insertIndexFor("above", 0, 5), 0);
});

test("boundary: below the LAST row inserts at the array end", () => {
  // splice(len, 0, row) appends — the same landing spot the end-of-list adder uses.
  assert.equal(insertIndexFor("below", 4, 5), 5);
  assert.equal(insertIndexFor("above", 4, 5), 4);
});

test("boundary: a single-row list accepts both directions", () => {
  assert.equal(insertIndexFor("above", 0, 1), 0);
  assert.equal(insertIndexFor("below", 0, 1), 1);
});

test("mid-list is the ordinary case and shifts everything at or after it", () => {
  const rows = ["a", "b", "c", "d"];
  const at = insertIndexFor("below", 1, rows.length);
  rows.splice(at, 0, "NEW");
  assert.deepEqual(rows, ["a", "b", "NEW", "c", "d"]);

  const rows2 = ["a", "b", "c", "d"];
  rows2.splice(insertIndexFor("above", 2, rows2.length), 0, "NEW");
  assert.deepEqual(rows2, ["a", "b", "NEW", "c", "d"]);
});

test("headings are NOT a special case: the index is positional, so 'below' joins the section", () => {
  // Sections are implicit in position — a heading owns the rows after it until the next heading.
  const rows = [
    { is_heading: 1, text: "FOR THE DASHI" },   // 0
    { is_heading: 0, text: "kombu" },           // 1
    { is_heading: 1, text: "FOR THE TOFU" },    // 2
    { is_heading: 0, text: "tofu" },            // 3
  ];
  // below the SECOND heading -> the first row inside that section
  const below = [...rows];
  below.splice(insertIndexFor("below", 2, below.length), 0, { is_heading: 0, text: "NEW" });
  assert.deepEqual(below.map((r) => r.text), ["FOR THE DASHI", "kombu", "FOR THE TOFU", "NEW", "tofu"]);

  // above the SECOND heading -> OUTSIDE it: the last row of the PRECEDING section
  const above = [...rows];
  above.splice(insertIndexFor("above", 2, above.length), 0, { is_heading: 0, text: "NEW" });
  assert.deepEqual(above.map((r) => r.text), ["FOR THE DASHI", "kombu", "NEW", "FOR THE TOFU", "tofu"]);

  // above the FIRST heading -> the new first row of the list, before any section starts
  const top = [...rows];
  top.splice(insertIndexFor("above", 0, top.length), 0, { is_heading: 0, text: "NEW" });
  assert.deepEqual(top.map((r) => r.text), ["NEW", "FOR THE DASHI", "kombu", "FOR THE TOFU", "tofu"]);
});

test("an EMPTY list refuses — unreachable from the UI, since no rows means no ⋯ menu", () => {
  assert.equal(insertIndexFor("above", 0, 0), null);
  assert.equal(insertIndexFor("below", 0, 0), null);
});

test("refuses any index that is not a real row, rather than clamping to a wrong one", () => {
  // Each of these has a silently-wrong splice() clamp, which is why null is returned instead:
  assert.equal(insertIndexFor("above", -1, 5), null);    // splice(-1) inserts before the LAST row
  assert.equal(insertIndexFor("below", -1, 5), null);
  assert.equal(insertIndexFor("above", 5, 5), null);     // one past the end; splice would append
  assert.equal(insertIndexFor("above", 99, 5), null);
  assert.equal(insertIndexFor("above", NaN, 5), null);   // splice(NaN) inserts at 0
  assert.equal(insertIndexFor("above", 1.5, 5), null);
  assert.equal(insertIndexFor("above", undefined, 5), null);
  assert.equal(insertIndexFor("above", "2", 5), null);   // a raw dataset value, never coerced for us
});

test("refuses a nonsensical length", () => {
  assert.equal(insertIndexFor("above", 0, -1), null);
  assert.equal(insertIndexFor("above", 0, NaN), null);
  assert.equal(insertIndexFor("above", 0, undefined), null);
});

test("any pos that is not 'below' means above — the caller passes one of two literals", () => {
  assert.equal(insertIndexFor("above", 2, 5), 2);
  assert.equal(insertIndexFor("BELOW", 2, 5), 2);   // case-sensitive by design; only "below" shifts
});
