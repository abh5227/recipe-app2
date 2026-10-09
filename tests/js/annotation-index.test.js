"use strict";
// annotation-index.js — which annotations attach to which rendered row.
//
// ⚠️ THIS FILE EXISTS BECAUSE THE FUNCTION USED TO BE UNTESTABLE. It lived inside app.js keyed on
// new_pos, so the only way to be wrong about it was in the browser, on real data, silently: a mark
// rendered against the row NEXT to the one it belonged to. Keying on the row id removed the second
// counter that made that possible, and extracting it made the rule checkable.
import { test } from "node:test";
import assert from "node:assert/strict";
import { annotationIndex } from "../../static/annotation-index.js";

const mod = (kind, field, row_id, extra = {}) =>
  ({ kind, type: "modified", field, row_id, new_pos: 0, old_pos: 0, ...extra });

test("a mark attaches to the row whose id it names", () => {
  const { ing } = annotationIndex([mod("ingredient", "amount", 42)]);
  assert.equal(ing.get(42).amount.field, "amount");
  assert.equal(ing.get(0), undefined, "nothing is keyed by position any more");
});

test("an amount and a name edit on one row share one slot", () => {
  const { ing } = annotationIndex([mod("ingredient", "amount", 7), mod("ingredient", "name", 7)]);
  assert.equal(ing.size, 1);
  assert.ok(ing.get(7).amount && ing.get(7).name);
});

test("ingredients and steps are separate id spaces", () => {
  // ⚠️ THE REASON THIS MATTERS: an ingredient row and a step row can hold the SAME id, since they
  // come from different tables with their own sequences. Under the old position keying that was also
  // true, so this is a property to keep rather than a new risk.
  const { ing, step } = annotationIndex([mod("ingredient", "amount", 5), mod("step", null, 5)]);
  assert.ok(ing.get(5).amount, "the ingredient mark stayed with the ingredients");
  assert.ok(step.get(5).mod, "the step mark stayed with the steps");
});

test("a removed entry is kept apart and ordered by old_pos", () => {
  const rm = (kind, old_pos) =>
    ({ kind, type: "removed", text: "x", old_pos, new_pos: null, row_id: null, section: null });
  const { ing, removedIng, removedStep } = annotationIndex(
    [rm("ingredient", 3), rm("ingredient", 1), rm("step", 2)]);
  assert.equal(ing.size, 0, "a removed row has no current row to attach to");
  assert.deepEqual(removedIng.map((e) => e.old_pos), [1, 3]);
  assert.equal(removedStep.length, 1);
});

test("an entry with no row_id is ignored rather than keyed on null", () => {
  // A recipe-header field change carries row_id null, and so does anything the diff could not place.
  const { ing, step } = annotationIndex([
    { kind: "field", type: "modified", field: "servings", from: "4", to: "6", row_id: null },
    mod("ingredient", "amount", null),
  ]);
  assert.equal(ing.size, 0);
  assert.equal(step.size, 0);
});

test("an added row is keyed by its id like any other", () => {
  const { ing } = annotationIndex(
    [{ kind: "ingredient", type: "added", text: "1 tsp salt", row_id: 99, new_pos: 2 }]);
  assert.ok(ing.get(99).added);
});

test("a heading entry is ignored", () => {
  const { ing, step } = annotationIndex(
    [{ kind: "heading", type: "modified", from: "A", to: "B", row_id: 11, new_pos: 0, old_pos: 0 }]);
  assert.equal(ing.size, 0);
  assert.equal(step.size, 0);
});

test("no annotations gives four empty collections", () => {
  for (const anns of [[], null, undefined]) {
    const r = annotationIndex(anns);
    assert.equal(r.ing.size + r.step.size + r.removedIng.length + r.removedStep.length, 0);
  }
});

// ---- Round B revision 4, A1: the second amount gets a slot ------------------------------------- //
test("a second-amount edit gets its own slot on its row", () => {
  // It used to be dropped here, so the server recorded the change and the page drew nothing.
  const { ing } = annotationIndex([mod("ingredient", "second_amount", 9, { from: "14 oz", to: "400 g" })]);
  assert.equal(ing.get(9).second_amount.to, "400 g");
  assert.equal(ing.get(9).amount, undefined, "the first amount is not marked by it");
});

test("amount, name and second amount on one row share one slot", () => {
  const { ing } = annotationIndex([mod("ingredient", "amount", 3), mod("ingredient", "name", 3),
                                   mod("ingredient", "second_amount", 3)]);
  assert.equal(ing.size, 1);
  assert.ok(ing.get(3).amount && ing.get(3).name && ing.get(3).second_amount);
});

test("a note edit is still not slotted", () => {
  // A note takes no part in "your changes" on the page. Only the second amount was added.
  const { ing } = annotationIndex([mod("ingredient", "note", 4)]);
  assert.deepEqual(ing.get(4), {});
});
