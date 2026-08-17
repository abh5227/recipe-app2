"use strict";
// Pins where a struck REMOVED annotation row lands. The bug this guards: a null `section` used to mean
// "list bottom" unconditionally, so an item removed from the UNNAMED PREAMBLE sailed past every section
// to the end of the list (observed on french-fries-copy: a step removed before the "FRY #1" heading
// rendered under the last step of "FRY #2"). Pure module, so this runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { removedInsertIndex } from "../../static/annotation-place.js";

const H = (t) => ({ isHeading: true, headingText: t });
const R = () => ({ isHeading: false, headingText: null });

// row / HEAD-A / row / row / HEAD-B / row   -> the shape both lists actually render
const sectioned = [R(), H("FRY #1"), R(), R(), H("FRY #2"), R()];

test("preamble (null section) inserts BEFORE the first heading, not at list bottom", () => {
  assert.equal(removedInsertIndex(sectioned, null), 1);
  assert.equal(removedInsertIndex(sectioned, undefined), 1);
  assert.equal(removedInsertIndex(sectioned, ""), 1);        // "" is the same conflation in miniature
});

test("null section with NO headings anywhere still means list bottom", () => {
  const flat = [R(), R(), R()];
  assert.equal(removedInsertIndex(flat, null), 3);
  assert.equal(removedInsertIndex([], null), 0);
});

test("a named section lands at that section's bottom — the next heading, or the list end", () => {
  assert.equal(removedInsertIndex(sectioned, "FRY #1"), 4);   // just before HEAD-B
  assert.equal(removedInsertIndex(sectioned, "FRY #2"), 6);   // last section -> list end
});

test("a renamed / since-deleted section falls to LIST BOTTOM, never into the preamble", () => {
  assert.equal(removedInsertIndex(sectioned, "FRY #3"), 6);
  assert.equal(removedInsertIndex(sectioned, "fry #1"), 6);   // exact match only — case matters
});

test("several preamble removals keep their old_pos order (each lands after the previous)", () => {
  const items = sectioned.slice();
  const at1 = removedInsertIndex(items, null);
  items.splice(at1, 0, { isHeading: false, headingText: null, tag: "first" });
  const at2 = removedInsertIndex(items, null);
  items.splice(at2, 0, { isHeading: false, headingText: null, tag: "second" });
  assert.equal(at1, 1);
  assert.equal(at2, 2);                                       // AFTER the first, not before it
  assert.deepEqual(items.filter((x) => x.tag).map((x) => x.tag), ["first", "second"]);
  assert.equal(items[3].headingText, "FRY #1");               // both still above the first heading
});

test("several in-section removals keep their order too (the pre-existing property)", () => {
  const items = sectioned.slice();
  const a = removedInsertIndex(items, "FRY #1");
  items.splice(a, 0, { isHeading: false, headingText: null, tag: "first" });
  const b = removedInsertIndex(items, "FRY #1");
  items.splice(b, 0, { isHeading: false, headingText: null, tag: "second" });
  assert.equal(a, 4);
  assert.equal(b, 5);
  assert.deepEqual(items.filter((x) => x.tag).map((x) => x.tag), ["first", "second"]);
});
