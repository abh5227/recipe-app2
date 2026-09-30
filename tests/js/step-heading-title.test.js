// The step heading's display transform: a trailing colon comes off on the way to the screen and the
// stored text keeps it.
//
// ⚠️ 90 OF THE 116 STORED HEADINGS END IN A COLON, and that is not an accident of authorship. A
// colon is how import_cleanup.is_section RECOGNIZES a heading, so the mark that identified the row
// is the mark left over once it has a rule under it instead of a sentence beside it.
import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

const APP = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const src = APP.slice(APP.indexOf("function stepHeadingTitle"));
const body = src.slice(0, src.indexOf("\n}") + 2);
const stepHeadingTitle = new Function(`${body}; return stepHeadingTitle;`)();

test("a trailing colon comes off", () => {
  assert.equal(stepHeadingTitle("Make your roux:"), "Make your roux");
  assert.equal(stepHeadingTitle("CHICKEN:"), "CHICKEN");
  assert.equal(stepHeadingTitle("To serve :"), "To serve");
});

test("a colon inside the heading stays", () => {
  assert.equal(stepHeadingTitle("Step 1: the dough"), "Step 1: the dough");
});

test("a heading with no colon is unchanged", () => {
  assert.equal(stepHeadingTitle("Shaping options"), "Shaping options");
  assert.equal(stepHeadingTitle("FRY #1"), "FRY #1");
});

test("other terminal punctuation is the author's and stays", () => {
  assert.equal(stepHeadingTitle("Make crispy cheesy birria tacos!"), "Make crispy cheesy birria tacos!");
});

test("empty and null are safe", () => {
  assert.equal(stepHeadingTitle(""), "");
  assert.equal(stepHeadingTitle(null), "");
  assert.equal(stepHeadingTitle(undefined), "");
});

test("the render calls it and the editor does not", () => {
  // ⚠️ THE CLASS IS NO LONGER A LITERAL, which is why this matches the call and not the whole tag.
  // A heading now carries its level (migration 059), so the tag is built from stepHeadingClass(row).
  assert.match(APP, /\$\{esc\(stepHeadingTitle\(row\.text\)\)\}/,
    "reading mode strips the colon");
  assert.match(APP, /stepHeadingClass\(row\)\}">\$\{esc\(stepHeadingTitle/,
    "and it does so inside the levelled heading tag, not somewhere else");
  assert.match(APP, /editStepHeadingField\(i, row\.text\)/,
    "the editor shows the STORED text, colon and all");
});

test("the heading level reaches both views through one helper", () => {
  // Reading and edit mode must agree about what a heading looks like, and they agree by calling the
  // same function rather than by two tags being kept in step by hand.
  assert.match(APP, /function stepHeadingClass\(row\) \{\s*return `group h\$\{stepLevel\(row\)\}`/);
  // The interpolation, so the function's own declaration is not counted as a call site.
  const uses = APP.match(/\$\{stepHeadingClass\(row\)\}/g) || [];
  assert.equal(uses.length, 2, "the reading row and the edit row, and nothing else");
});
