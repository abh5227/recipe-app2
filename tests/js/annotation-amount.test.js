"use strict";
// The amounts an ANNOTATED ledger row shows. The bug these pin: the annotation render hardcoded a
// factor of 1, so an edited row sat at its printed amount while every unedited row beside it
// doubled. Every assertion here compares 1x against 2x rather than a literal, because the literal
// is what the abbreviation already covers in scaler.test.js.
import { test } from "node:test";
import assert from "node:assert/strict";
import { editedAmountParts, removedAmountText, stepSpanTexts } from "../../static/annotation-amount.js";
import { amountText } from "../../static/scaler.js";

// --------------------------------------------------------------------------------------------- //
// An edited amount: BOTH halves move with the factor
// --------------------------------------------------------------------------------------------- //
test("both halves of an edited amount double at 2x", () => {
  const one = editedAmountParts("3 tablespoons", "2 tbsp", null, 1);
  const two = editedAmountParts("3 tablespoons", "2 tbsp", null, 2);
  assert.equal(one.was, "3 tbsp");
  assert.equal(one.fix, "2 tbsp");
  assert.equal(two.was, "6 tbsp");
  assert.equal(two.fix, "4 tbsp");
});

test("baked-tofu's real edit abbreviates AND scales together", () => {
  // ½ teaspoon -> 1 tsp is a live annotation. The unit word abbreviates at every factor, which is
  // what the hardcoded 1 was reaching for, and the number still has to move.
  const one = editedAmountParts("½ teaspoon", "1 tsp", null, 1);
  const two = editedAmountParts("½ teaspoon", "1 tsp", null, 2);
  const half = editedAmountParts("½ teaspoon", "1 tsp", null, 0.5);
  assert.equal(one.was, "½ tsp");
  assert.equal(one.fix, "1 tsp");
  assert.equal(two.was, "1 tsp");
  assert.equal(two.fix, "2 tsp");
  assert.equal(half.was, "¼ tsp");
  assert.equal(half.fix, "½ tsp");
});

test("the struck original scales by the SAME factor as the ink correction", () => {
  for (const f of [0.5, 1, 2, 3.5]) {
    const p = editedAmountParts("2 cups", "3 cups", null, f);
    assert.equal(p.was, amountText("2 cups", f));
    assert.equal(p.fix, amountText("3 cups", f));
  }
});

test("a countable amount still scales as a count", () => {
  assert.equal(editedAmountParts("4", "4 cloves", null, 2).fix, "8 cloves");
  assert.equal(editedAmountParts("4", "4 cloves", null, 2).was, "8");
});

// --------------------------------------------------------------------------------------------- //
// The gram sub-line an edited row used to lose
// --------------------------------------------------------------------------------------------- //
test("an edited row keeps a gram estimate, and it is the CURRENT amount's", () => {
  const WATER = 227 / 236.588;
  // 1 cup clears the 2-tbsp spoon threshold; the weight must follow `to`, not `from`.
  const p = editedAmountParts("2 cups", "1 cup", WATER, 1);
  assert.ok(p.weight, "expected a weight sub-line");
  assert.equal(p.weight, editedAmountParts("x", "1 cup", WATER, 1).weight);
  assert.notEqual(p.weight, editedAmountParts("x", "2 cups", WATER, 1).weight);
});

test("the gram estimate scales with the factor too", () => {
  const WATER = 227 / 236.588;
  const one = editedAmountParts("2 cups", "1 cup", WATER, 1).weight;
  const two = editedAmountParts("2 cups", "1 cup", WATER, 2).weight;
  const g = (s) => parseInt(String(s).replace(/[^0-9]/g, ""), 10);
  assert.ok(g(two) > g(one) * 1.9 && g(two) < g(one) * 2.1, `${one} -> ${two}`);
});

test("a weightless row emits no sub-line, so the column stays unreserved", () => {
  assert.equal(editedAmountParts("1 tsp", "2 tsp", null, 1).weight, "");
});

// --------------------------------------------------------------------------------------------- //
// A struck REMOVED row
// --------------------------------------------------------------------------------------------- //
test("a removed row's struck amount scales", () => {
  // the entry carries the combined line and the name; the amount is what precedes the name
  const args = ["2 tablespoons olive oil, plus more for dough", "olive oil, plus more for dough"];
  assert.equal(removedAmountText(...args, 1), "2 tbsp");
  assert.equal(removedAmountText(...args, 2), "4 tbsp");
  assert.equal(removedAmountText(...args, 0.5), "1 tbsp");
});

test("a removed row whose line is all name reserves no figure", () => {
  assert.equal(removedAmountText("Fresh basil", "Fresh basil", 2), "");
});

test("a removed row with a bare count scales as a count", () => {
  assert.equal(removedAmountText("4 garlic cloves", "garlic cloves", 2), "8");
});

// --------------------------------------------------------------------------------------------- //
// An edited STEP
// --------------------------------------------------------------------------------------------- //
test("a step's scale-tagged span scales and its plain prose does not", () => {
  const spans = [
    { t: "plain", text: "Cook the beef: add " },
    { t: "scale", text: "1 tbsp", unit: "tbsp", value: 1 },
    { t: "plain", text: " oil and simmer for 4-6 minutes." },
  ];
  const two = stepSpanTexts(spans, 2);
  assert.equal(two[0].text, "Cook the beef: add ");
  assert.equal(two[1].text, "2 tbsp");
  assert.equal(two[2].text, " oil and simmer for 4-6 minutes.", "a time must not double");
});

test("⚠️ the tagger is what protects a time, not the scaler", () => {
  // The corpus's one reworded step. Running the scaler over the whole prose turns "4-6 minutes"
  // into "8-12 minutes", which is why stepSpanTexts takes SPANS and never a raw string.
  const spans = [{ t: "plain", text: "simmer for 4-6 minutes, until reduced to 1-2 tablespoons" }];
  assert.equal(stepSpanTexts(spans, 2)[0].text,
               "simmer for 4-6 minutes, until reduced to 1-2 tablespoons");
});

test("no spans is an empty render, not a throw", () => {
  assert.deepEqual(stepSpanTexts(undefined, 2), []);
  assert.deepEqual(stepSpanTexts([], 2), []);
});
