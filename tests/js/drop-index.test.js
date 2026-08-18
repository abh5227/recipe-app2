// drop-index.js — the pure drop-target calculation for row drag-reorder (C0). Nothing is wired yet
// (C1 does ingredients, C2 steps), so this file IS the specification: the geometry contract, the
// tie-break, the direction-independence that kills the classic off-by-one, and above all the recorded
// HEIGHT-AGNOSTIC constraint, which is pinned by a variable-height list whose correct answer differs
// from the answer uniform row-height arithmetic would give.
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyRowDrop, dropBeforeIndex } from "../../static/drop-index.js";
import { reorderBefore } from "../../static/reorder.js";

// Four uniform 44px rows starting at y=100. Midpoints: 122, 166, 210, 254; the list ends at 276.
// Plain objects, not DOMRects — the module needs only {top, height}, which is what makes it testable.
const EVEN = [
  { top: 100, height: 44 },
  { top: 144, height: 44 },
  { top: 188, height: 44 },
  { top: 232, height: 44 },
];
const ROWS = ["A", "B", "C", "D"];

// ---- the ends -------------------------------------------------------------------------------------

test("above the first row's midpoint -> index 0", () => {
  assert.equal(dropBeforeIndex(EVEN, 0, 2), 0);        // far above the list
  assert.equal(dropBeforeIndex(EVEN, 121, 2), 0);      // one pixel above row 0's midpoint
});

test("below the last row's midpoint -> null (the end)", () => {
  assert.equal(dropBeforeIndex(EVEN, 255, 0), null);   // one pixel past row 3's midpoint
  assert.equal(dropBeforeIndex(EVEN, 9999, 0), null);  // far below the list
  // and null is what reorderBefore already spells "the end"
  assert.deepEqual(applyRowDrop(ROWS, 0, null), ["B", "C", "D", "A"]);
});

// ---- the boundary ---------------------------------------------------------------------------------

test("exactly ON a midpoint lands AFTER that row (the `<` is strict)", () => {
  // 210 is row 2's midpoint exactly. Not before row 2 -> the scan continues to row 3.
  assert.equal(dropBeforeIndex(EVEN, 210, 0), 3);
  assert.equal(dropBeforeIndex(EVEN, 209, 0), 2);      // one pixel earlier IS before row 2
  // the last row's midpoint exactly -> past every midpoint -> the end
  assert.equal(dropBeforeIndex(EVEN, 254, 0), null);
});

// ---- ⚠️ the classic off-by-one --------------------------------------------------------------------

test("downward and upward past the same row give the same drop, and the array the user SEES", () => {
  // One drop point, in the gap between B and C (above row 2's midpoint of 210, below row 1's is not
  // required — 200 is past 166 and short of 210).
  const y = 200;

  const down = dropBeforeIndex(EVEN, y, 0);            // dragging A downward
  const up = dropBeforeIndex(EVEN, y, 3);              // dragging D upward to the same gap
  assert.equal(down, 2);
  assert.equal(up, 2);
  assert.equal(down, up, "the drop target must not depend on the drag's direction");

  const afterDown = applyRowDrop(ROWS, 0, down);
  const afterUp = applyRowDrop(ROWS, 3, up);
  assert.deepEqual(afterDown, ["B", "A", "C", "D"]);   // A now sits between B and C
  assert.deepEqual(afterUp, ["A", "B", "D", "C"]);     // D now sits between B and C

  // THE POINT: the visible outcome is "between B and C" both times, and the before-reference is 2
  // both times — but the dragged row's RESULTING INDEX differs by direction. An API returning that
  // landing index would need a direction-dependent adjustment; this one does not.
  assert.equal(afterDown.indexOf("A"), 1);
  assert.equal(afterUp.indexOf("D"), 2);
});

// ---- never itself ----------------------------------------------------------------------------------

test("the dragged row is never returned as its own target, at any pointer position", () => {
  for (let dragged = 0; dragged < EVEN.length; dragged++) {
    for (let y = 90; y <= 290; y += 1) {
      assert.notEqual(dropBeforeIndex(EVEN, y, dragged), dragged,
        `row ${dragged} targeted itself at y=${y}`);
    }
  }
});

test("hovering over your own row is a no-op drop, not a move", () => {
  // Pointer inside row 1's own box: row 1 is skipped, so the scan answers row 2 -> "insert before the
  // row directly after me", which is where row 1 already is.
  assert.equal(dropBeforeIndex(EVEN, 150, 1), 2);
  assert.deepEqual(applyRowDrop(ROWS, 1, 2), ROWS);
});

// ---- ⚠️ the recorded constraint: HEIGHT-AGNOSTIC ---------------------------------------------------

// row 0: 0–44 (mid 22) | row 1: 44–184, a 140px tall row (mid 114) | row 2: 184–228 (mid 206)
const MIXED = [
  { top: 0, height: 44 },
  { top: 44, height: 140 },
  { top: 184, height: 44 },
];

test("VARIABLE HEIGHTS: the target follows midpoints, never uniform row-height arithmetic", () => {
  // If anyone reintroduces `Math.floor(y / rowHeight)`, these are the assertions that fail.
  const uniform = (y) => Math.floor(y / 44);           // what height arithmetic would answer

  assert.equal(dropBeforeIndex(MIXED, 100, 2), 1);     // y=100 is above the tall row's midpoint (114)
  assert.equal(uniform(100), 2, "sanity: uniform arithmetic really does disagree here");

  assert.equal(dropBeforeIndex(MIXED, 170, 0), 2);     // y=170 is still inside the tall row, past its midpoint
  assert.equal(uniform(170), 3, "sanity: uniform arithmetic would run off the end here");

  assert.equal(dropBeforeIndex(MIXED, 200, 0), 2);     // y=200 is above row 2's midpoint (206)
  assert.equal(uniform(200), 4, "sanity: uniform arithmetic would be two rows out here");
});

test("VARIABLE HEIGHTS: the tall row's midpoint is the only thing that switches the answer", () => {
  // Dragging row 0, so both the tall row and the one after it are eligible targets.
  assert.equal(dropBeforeIndex(MIXED, 113, 0), 1);     // one pixel above the tall row's midpoint
  assert.equal(dropBeforeIndex(MIXED, 114, 0), 2);     // exactly on it -> after it (the strict `<`)
  assert.equal(dropBeforeIndex(MIXED, 115, 0), 2);     // one pixel below
  // A drop deep inside a tall row still resolves by that row's midpoint, not by how tall it is:
  // every y from its midpoint to its bottom gives the same answer.
  for (let y = 114; y < 184; y++) assert.equal(dropBeforeIndex(MIXED, y, 0), 2);
});

// ---- degenerate lists -------------------------------------------------------------------------------

test("single-row list, dragging the only row -> nowhere to go", () => {
  const one = [{ top: 0, height: 44 }];
  assert.equal(dropBeforeIndex(one, 0, 0), null);      // its only row is the dragged one
  assert.equal(dropBeforeIndex(one, 1000, 0), null);
  assert.deepEqual(applyRowDrop(["A"], 0, null), ["A"]);   // and the drop is a no-op
});

test("single-row list, nothing being dragged -> the row is eligible", () => {
  const one = [{ top: 0, height: 44 }];
  assert.equal(dropBeforeIndex(one, 10, null), 0);
  assert.equal(dropBeforeIndex(one, 40, null), null);
});

test("empty list -> the end, and no drop can be applied", () => {
  assert.equal(dropBeforeIndex([], 100, 0), null);
  assert.equal(dropBeforeIndex([], 100, null), null);
  assert.equal(applyRowDrop([], 0, null), null, "no row 0 to drag -> refuse");
});

// ---- defensive inputs --------------------------------------------------------------------------------

test("unusable geometry is refused rather than guessed at", () => {
  assert.equal(dropBeforeIndex(EVEN, NaN, 0), null);            // a non-finite pointer
  assert.equal(dropBeforeIndex(null, 100, 0), null);            // no rects at all
  const holey = [{ top: 100, height: 44 }, null, { top: 188, height: 44 }];
  assert.equal(dropBeforeIndex(holey, 180, 0), 2);              // the unmeasurable row is skipped, not targeted
});

test("dropBeforeIndex does not mutate its input", () => {
  const src = EVEN.map((r) => ({ ...r }));
  dropBeforeIndex(src, 200, 1);
  assert.deepEqual(src, EVEN);
});

// ---- composition with reorderBefore -------------------------------------------------------------------

test("round-trip: a drop above the first row moves the row to the front", () => {
  assert.deepEqual(applyRowDrop(ROWS, 2, dropBeforeIndex(EVEN, 0, 2)), ["C", "A", "B", "D"]);
});

test("round-trip: a drop below the last row moves the row to the end", () => {
  assert.deepEqual(applyRowDrop(ROWS, 1, dropBeforeIndex(EVEN, 9999, 1)), ["A", "C", "D", "B"]);
});

test("round-trip: rows are carried by identity, so any row shape works", () => {
  // The editor lists hold row OBJECTS (and heading rows), not ids — applyRowDrop must move whatever
  // it is given, untouched and un-cloned.
  const heading = { heading: "FOR THE BASE" };
  const eggs = { qty: "2", text: "eggs" };
  const flour = { qty: "1 cup", text: "flour" };
  const out = applyRowDrop([heading, eggs, flour], 2, 0);       // flour to the front
  assert.deepEqual(out, [flour, heading, eggs]);
  assert.equal(out[0], flour, "the row object itself must be carried, not a copy");
});

test("applyRowDrop delegates to reorderBefore — the move has ONE definition", () => {
  // Same permutation, computed both ways: if the composition here ever drifts from the array op in
  // reorder.js, this fails.
  const order = ROWS.map((_, i) => i);
  assert.deepEqual(applyRowDrop(ROWS, 3, 1), reorderBefore(order, 3, 1).map((i) => ROWS[i]));
  assert.deepEqual(applyRowDrop(ROWS, 0, null), reorderBefore(order, 0, null).map((i) => ROWS[i]));
});

test("applyRowDrop REFUSES a bad index rather than clamping it", () => {
  // reorderBefore is defensive about an unknown id and APPENDS it, so a stale index would silently
  // grow the list by a phantom row. Refusing is the only safe direction. (cf. insertIndexFor)
  assert.equal(applyRowDrop(ROWS, 4, 1), null);        // dragged index past the end
  assert.equal(applyRowDrop(ROWS, -1, 1), null);
  assert.equal(applyRowDrop(ROWS, 1.5, 1), null);
  assert.equal(applyRowDrop(ROWS, null, 1), null);
  assert.equal(applyRowDrop(ROWS, 0, 9), null);        // before-index past the end
  assert.equal(applyRowDrop(ROWS, 0, -1), null);
  assert.equal(applyRowDrop(null, 0, 1), null);
});

test("applyRowDrop does not mutate its input", () => {
  const src = [...ROWS];
  applyRowDrop(src, 3, 0);
  assert.deepEqual(src, ROWS);
});
