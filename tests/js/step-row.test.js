"use strict";
// Pins the blank-step rule (editor parity stage 1): clearing a step's text is how you DELETE it, so
// draftPayload prunes blank steps at save time exactly as nonEmptyRows prunes blank ingredient rows.
// Pure transforms in static/step-row.js, so this runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepIsBlank, nonEmptySteps, focusIndexAfterRemove } from "../../static/step-row.js";

test("stepIsBlank: empty and whitespace-only text is blank; real text is not", () => {
  assert.equal(stepIsBlank({ is_heading: 0, text: "" }), true);
  assert.equal(stepIsBlank({ is_heading: 0, text: "   " }), true);
  assert.equal(stepIsBlank({ is_heading: 0, text: "\n\t " }), true);
  assert.equal(stepIsBlank({ is_heading: 0, text: "Preheat the oven." }), false);
  assert.equal(stepIsBlank({ is_heading: 0, text: "  padded but real  " }), false);
});

test("stepIsBlank: a heading keeps its label in `text` — textless headings are blank, real ones are not", () => {
  assert.equal(stepIsBlank({ is_heading: 1, text: "" }), true);       // renders as nothing; server demotes {heading:""}
  assert.equal(stepIsBlank({ is_heading: 1, text: "   " }), true);
  assert.equal(stepIsBlank({ is_heading: 1, text: "TO SERVE:" }), false);
});

test("stepIsBlank: missing/undefined text and a missing row are blank (never throws)", () => {
  assert.equal(stepIsBlank({ is_heading: 0 }), true);
  assert.equal(stepIsBlank({}), true);
  assert.equal(stepIsBlank(null), true);
  assert.equal(stepIsBlank(undefined), true);
});

test("nonEmptySteps drops only the blanks, preserving order and the surviving objects", () => {
  const a = { is_heading: 0, text: "Mix" };
  const h = { is_heading: 1, text: "TO SERVE:" };
  const b = { is_heading: 0, text: "Bake" };
  const steps = [a, { is_heading: 0, text: "" }, h, { is_heading: 0, text: "  " }, b];
  const kept = nonEmptySteps(steps);
  assert.deepEqual(kept, [a, h, b]);
  assert.equal(kept[0], a);                      // same objects, not copies
  assert.equal(steps.length, 5);                 // input untouched
});

test("nonEmptySteps: all-blank -> empty, none-blank -> unchanged", () => {
  assert.deepEqual(nonEmptySteps([{ text: "" }, { text: " " }]), []);
  const real = [{ is_heading: 0, text: "One" }, { is_heading: 0, text: "Two" }];
  assert.deepEqual(nonEmptySteps(real), real);
});

// Editor parity stage 2: after removeStep splices, the caret goes to whatever took the deleted step's
// place. lenAfter is the length AFTER the splice, so a middle delete lands on the SAME index.
test("focusIndexAfterRemove: a middle delete focuses the step that slid into that index", () => {
  assert.equal(focusIndexAfterRemove(0, 4), 0);   // deleted the first of 5 -> the new first
  assert.equal(focusIndexAfterRemove(2, 4), 2);   // deleted the middle    -> the one that took its slot
});

test("focusIndexAfterRemove: deleting the last step falls back to the new last; empty -> no focus", () => {
  assert.equal(focusIndexAfterRemove(4, 4), 3);   // was last of 5 -> clamp to the new last
  assert.equal(focusIndexAfterRemove(0, 0), null);
  assert.equal(focusIndexAfterRemove(3, 0), null);
});
