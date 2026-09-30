"use strict";
// Pins the blank-step rule (editor parity stage 1): clearing a step's text is how you DELETE it, so
// draftPayload prunes blank steps at save time exactly as nonEmptyRows prunes blank ingredient rows.
// Pure transforms in static/step-row.js, so this runs under bare `node --test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { stepIsBlank, nonEmptySteps, focusIndexAfterRemove, writeStepField,
         stepLevel, toggleStepType, setStepLevel } from "../../static/step-row.js";

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

// Editor parity: step headings are editable inline. writeStepField is the draft write-back the
// [data-inline-edit-step] input listener and its Esc-revert both go through.
test("writeStepField: the 'heading' key writes the label into .text (where a heading keeps it)", () => {
  const row = { is_heading: 1, text: "TO SERVE:" };
  assert.equal(writeStepField(row, "heading", "TO FINISH:"), row);   // returns the row, like writeIngField
  assert.deepEqual(row, { is_heading: 1, text: "TO FINISH:" });      // is_heading untouched
});

test("writeStepField: 'text' writes the same field, so a non-heading step round-trips too", () => {
  const row = { is_heading: 0, text: "Mix" };
  writeStepField(row, "text", "Mix well");
  assert.deepEqual(row, { is_heading: 0, text: "Mix well" });
});

test("writeStepField: an empty string is written through, NOT ignored", () => {
  // Clearing a heading must reach the draft — nonEmptySteps then drops it at save, which is the
  // documented delete-by-clearing contract. Swallowing "" would make the field un-clearable.
  const row = { is_heading: 1, text: "TO SERVE:" };
  writeStepField(row, "heading", "");
  assert.equal(row.text, "");
  assert.equal(stepIsBlank(row), true);
});

test("writeStepField: an unknown key changes nothing, and a missing row never throws", () => {
  const row = { is_heading: 1, text: "TO SERVE:" };
  writeStepField(row, "qty", "2");
  assert.deepEqual(row, { is_heading: 1, text: "TO SERVE:" });       // no stray property
  // The delegated listeners can fire on a stale data-i between a splice and its re-render.
  assert.equal(writeStepField(null, "heading", "x"), null);
  assert.equal(writeStepField(undefined, "heading", "x"), undefined);
});

// --------------------------------------------------------------------------------------------- //
// Convert to heading / Convert to step, and the two levels (migration 059)
// --------------------------------------------------------------------------------------------- //

test("stepLevel: a subheading is 2 and everything else reads as 1", () => {
  assert.equal(stepLevel({ is_heading: 1, heading_level: 2 }), 2);
  assert.equal(stepLevel({ is_heading: 1, heading_level: 1 }), 1);
  // The column ships without a CHECK (migration 059), so both ends narrow instead.
  assert.equal(stepLevel({ is_heading: 1 }), 1, "a row written before 059 is a section");
  assert.equal(stepLevel({ is_heading: 1, heading_level: null }), 1);
  assert.equal(stepLevel({ is_heading: 1, heading_level: "2" }), 1, "a string is not a level");
  assert.equal(stepLevel({ is_heading: 1, heading_level: 7 }), 1);
  assert.equal(stepLevel(null), 1);
  assert.equal(stepLevel(undefined), 1);
});

test("toggleStepType keeps the row id, which is what the conversion has to keep", () => {
  // ⚠️ THE WHOLE REASON THE MENU ITEM IS A TOGGLE. Delete plus Add step was the only undo path
  // before, and it mints a NEW id — taking the wait link, the annotation anchor and any margin mark
  // with it. 67 steps became headings, so the undo had to be lossless.
  const row = { id: 4555, is_heading: 0, text: "Rise" };
  assert.equal(toggleStepType(row), row, "mutates in place, like toggleRowType");
  assert.deepEqual(row, { id: 4555, is_heading: 1, text: "Rise", heading_level: 1 });
  toggleStepType(row);
  assert.deepEqual(row, { id: 4555, is_heading: 0, text: "Rise", heading_level: 1 });
});

test("a new heading is a section, not a subheading", () => {
  // A subheading is a label lifted off one step, which is the importer's job. A person reaching for
  // "Convert to heading" is marking a boundary.
  assert.equal(stepLevel(toggleStepType({ id: 1, is_heading: 0, text: "Make the sauce" })), 1);
});

test("both kinds keep their words in text, so nothing is lost either way", () => {
  // The step twin is much shorter than toggleRowType for this reason: there is no second field to
  // seed from and nothing to leave dormant.
  const row = { id: 9, is_heading: 0, text: "Deseed - trim and discard the stems." };
  const words = row.text;
  toggleStepType(row);
  assert.equal(row.text, words);
  toggleStepType(row);
  assert.equal(row.text, words);
  assert.equal(stepIsBlank(row), false);
});

test("a demoted subheading comes back as a subheading inside one session", () => {
  const row = { id: 1806, is_heading: 1, text: "Deseed", heading_level: 2 };
  toggleStepType(row);                                  // -> an ordinary step, level left dormant
  assert.equal(row.is_heading, 0);
  toggleStepType(row);                                  // -> back
  assert.equal(stepLevel(row), 2, "the level was not thrown away mid-session");
});

test("setStepLevel refuses to mark an ordinary step as a subheading", () => {
  // A level the reading view would never read is a value with no meaning, and app.py stores 1 on
  // every non-heading row regardless.
  assert.equal(stepLevel(setStepLevel({ id: 1, is_heading: 0, text: "Mix." }, 2)), 1);
  assert.equal(setStepLevel({ id: 1, is_heading: 0, text: "Mix." }, 2).heading_level, undefined);
});

test("setStepLevel moves a heading both ways and narrows anything else to a section", () => {
  const h = { id: 2, is_heading: 1, text: "Deseed", heading_level: 1 };
  assert.equal(stepLevel(setStepLevel(h, 2)), 2);
  assert.equal(stepLevel(setStepLevel(h, 1)), 1);
  assert.equal(stepLevel(setStepLevel(h, 3)), 1);
  assert.equal(stepLevel(setStepLevel(h, "2")), 1);
});
