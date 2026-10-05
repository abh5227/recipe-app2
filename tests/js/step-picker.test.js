"use strict";
// The "link a step" picker's rules: what the list holds, what a typed filter keeps, and where the
// arrow keys land. Pure, so every case here is the case the browser runs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pickerRows, filterRows, matchesStep, stepRowsOf, startCursor, moveCursor,
         PICKER_ROWS, PICKER_WORDS } from "../../static/step-picker.js";

// The bagel's shape: four sections over fifteen steps, which is the case that broke the old menu.
const STEPS = [
  { id: 100, text: "Make the dough:", is_heading: true },
  { id: 1, text: "Mix the flour, water, salt and yeast until no dry flour remains", is_heading: false },
  { id: 2, text: "Knead for 10 to 12 minutes until smooth", is_heading: false },
  { id: 200, text: "Shape:", is_heading: true },
  { id: 3, text: "Divide into eight pieces and roll each into a ball", is_heading: false },
  { id: 4, text: "Poke a hole through the center with your thumb", is_heading: false },
];
const rows = () => pickerRows(STEPS);
const ids = (rs) => stepRowsOf(rs).map((r) => r.id);

test("the rows are the method in its own order, sections printed and steps numbered", () => {
  const r = rows();
  assert.deepEqual(r.map((x) => x.t), ["sect", "step", "step", "sect", "step", "step"]);
  assert.deepEqual(stepRowsOf(r).map((x) => x.no), [1, 2, 3, 4],
    "the numbers skip the headings, as the page does");
  assert.deepEqual(r.filter((x) => x.t === "sect").map((x) => x.text),
    ["Make the dough:", "Shape:"]);
});

test("a row shows the first few words and says when there are more", () => {
  const r = stepRowsOf(rows())[0];
  assert.equal(r.words.split(/\s+/).length, PICKER_WORDS);
  assert.equal(r.words, "Mix the flour, water, salt and yeast");
  assert.equal(r.more, true);
  assert.equal(stepRowsOf(pickerRows([{ id: 9, text: "Rest", is_heading: false }]))[0].more, false);
});

test("an empty heading is not printed as an empty section", () => {
  const r = pickerRows([{ id: 1, text: "   ", is_heading: true },
                        { id: 2, text: "Chop", is_heading: false }]);
  assert.deepEqual(r.map((x) => x.t), ["step"]);
});

test("the cleaner is injected, so a row reads as the page reads it", () => {
  // The app hands in stepHeadingTitle for a heading and showLinksAsWords for a step, which is how
  // "[[garlic|the garlic]]" and a trailing colon stop reaching the list.
  const clean = (t, isHeading) => (isHeading ? String(t).replace(/:$/, "") : String(t).toUpperCase());
  const r = pickerRows([{ id: 1, text: "To cook:", is_heading: true },
                        { id: 2, text: "chop", is_heading: false }], clean);
  assert.equal(r[0].text, "To cook");
  assert.equal(r[1].words, "CHOP");
});

// --- the filter -----------------------------------------------------------------------------------

test("digits mean a NUMBER and never a word, which is the bug this rule was written for", () => {
  // ⚠️ "12" used to match step 2 as well, because step 2's words read "10 to 12 minutes". A cook
  //    typing a number means a step number.
  assert.deepEqual(ids(filterRows(rows(), "12")), [], "no step 12 here, and step 2 is not one");
  assert.deepEqual(ids(filterRows(rows(), "2")), [2], "step 2, by its number");
  assert.deepEqual(ids(filterRows(rows(), "minutes")), [2], "the same words, asked for as words");
});

test("a number matches by prefix, so one keystroke is worth making", () => {
  const many = pickerRows(Array.from({ length: 14 }, (_, i) =>
    ({ id: i + 1, text: `step ${i + 1} words`, is_heading: false })));
  assert.deepEqual(stepRowsOf(filterRows(many, "1")).map((r) => r.no), [1, 10, 11, 12, 13, 14]);
});

test("a word matches anywhere in the step, not only in the words the row shows", () => {
  assert.deepEqual(ids(filterRows(rows(), "thumb")), [4],
    "'thumb' is the ninth word and the row shows seven");
});

test("the filter ignores case and surrounding space", () => {
  assert.deepEqual(ids(filterRows(rows(), "  KNEAD ")), [2]);
});

test("an empty filter keeps everything, headings included", () => {
  assert.deepEqual(filterRows(rows(), "").length, rows().length);
  assert.deepEqual(filterRows(rows(), "   ").length, rows().length);
});

test("a heading survives only while a step under it does", () => {
  const r = filterRows(rows(), "thumb");
  assert.deepEqual(r.map((x) => x.t), ["sect", "step"]);
  assert.equal(r[0].text, "Shape:", "and it is the right one, not the first one");
});

test("nothing matching leaves no rows at all, not a list of bare headings", () => {
  assert.deepEqual(filterRows(rows(), "parsnip"), []);
});

test("matchesStep is the one rule, asked directly", () => {
  const r = stepRowsOf(rows())[1];
  assert.equal(matchesStep(r, ""), true);
  assert.equal(matchesStep(r, "2"), true);
  assert.equal(matchesStep(r, "3"), false);
  assert.equal(matchesStep(r, "smooth"), true);
  assert.equal(matchesStep(r, null), true);
});

// --- the keyboard ---------------------------------------------------------------------------------

test("the cursor starts on the step the note is already linked to", () => {
  assert.equal(startCursor(rows(), 3), 3);
  assert.equal(startCursor(rows(), null), 1, "else the first row");
  assert.equal(startCursor(rows(), 999), 1, "a link to a step that is not here is not a cursor");
});

test("a filter that hides the current link does not leave the cursor on it", () => {
  const r = filterRows(rows(), "thumb");
  assert.equal(startCursor(r, 1), 4, "step 1 is filtered out, so the cursor takes what is there");
});

test("down and up move one selectable row and skip the headings", () => {
  const r = rows();
  assert.equal(moveCursor(r, 1, 1), 2);
  assert.equal(moveCursor(r, 2, 1), 3, "straight past the Shape: heading");
  assert.equal(moveCursor(r, 3, -1), 2);
});

test("the arrows CLAMP at both ends rather than wrapping", () => {
  // Jumping from the last row to the first hides the fact that the cook has reached the end, which
  // is the thing they are looking for.
  const r = rows();
  assert.equal(moveCursor(r, 4, 1), 4);
  assert.equal(moveCursor(r, 1, -1), 1);
});

test("an arrow with the cursor nowhere lands at the near end", () => {
  assert.equal(moveCursor(rows(), null, 1), 1);
  assert.equal(moveCursor(rows(), null, -1), 4);
});

test("an empty list answers null rather than throwing", () => {
  assert.equal(startCursor([], 1), null);
  assert.equal(moveCursor([], 1, 1), null);
  assert.deepEqual(pickerRows(null), []);
  assert.deepEqual(filterRows(null, "x"), []);
});

// --- Escape changes nothing --------------------------------------------------------------------

test("nothing the picker does to its rows reaches the note", () => {
  // ⚠️ ESCAPE HAS TO LEAVE THE ROW BYTE-IDENTICAL, and the structural half of that is here: every
  //    function in this module is a read. The rows handed in come back unmutated, and a step id
  //    leaves the module only as data on a button that has to be clicked.
  const before = JSON.stringify(rows());
  const r = rows();
  filterRows(r, "knead");
  startCursor(r, 3);
  moveCursor(r, 3, 1);
  matchesStep(stepRowsOf(r)[0], "mix");
  assert.equal(JSON.stringify(r), before);
});

test("seven rows is a stated number, not a hope", () => {
  assert.equal(PICKER_ROWS, 7);
  assert.ok(PICKER_ROWS >= 6 && PICKER_ROWS <= 8, "the brief asks for about 6 to 8");
});

// --- a step the database has never seen -----------------------------------------------------------
// ⚠️ THE DRAFT HOLDS `id: null` ROWS AND THE FIXTURES NEVER DID. addStep inserts one, currentSteps
//    hands view.draft.steps straight to pickerRows, and a link is a row id, so picking an unsaved
//    step sent +"null" -> NaN and quietly wrote no link. These pin the real draft shape.

test("an unsaved step is counted but never offered", () => {
  const rows = pickerRows([{ id: 10, text: "first" }, { id: null, text: "just added" },
                           { id: 20, text: "third" }], (t) => t);
  assert.deepEqual(rows.map((r) => r.id), [10, 20], "no null id reaches the list");
  assert.deepEqual(rows.map((r) => r.no), [1, 3], "and the numbers still match the page");
});

test("the cursor cannot land on an unsaved step", () => {
  // String(null) === String(null) made startCursor pick the unsaved row for an UNLINKED note.
  const rows = pickerRows([{ id: null, text: "just added" }, { id: 20, text: "second" }], (t) => t);
  assert.equal(startCursor(rows, null), 20, "an unlinked note starts on a real step");
  assert.equal(startCursor(rows, undefined), 20);
});

test("a heading and an unsaved step are both printed-or-skipped, never selectable", () => {
  const rows = pickerRows([{ id: 5, is_heading: true, text: "For the sauce" },
                           { id: null, text: "just added" }, { id: 20, text: "stir" }], (t) => t);
  assert.deepEqual(rows.map((r) => r.t), ["sect", "step"]);
  assert.deepEqual(stepRowsOf(rows).map((r) => r.id), [20]);
});
