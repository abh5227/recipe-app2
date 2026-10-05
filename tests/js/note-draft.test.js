"use strict";
// Notes held in the Edit-mode draft. Every function here changes a LIST, which is the whole reason
// Cancel can throw the session away: nothing has been written.
import { test } from "node:test";
import assert from "node:assert/strict";
import { noteStepNumbers, resolveNoteSteps, scanMentions, carryRefs, nextDraftId,
         draftSetText, draftSetKind, draftSetStep, draftAdd, draftDelete, draftRestore,
         notesPayload } from "../../static/note-draft.js";

const note = (o) => ({ id: 1, kind: "notes", text: "", step_id: null, step_no: null,
                       ingredient_row_id: null, position: 0, refs: [], ...o });
const STEPS = [{ id: 10, is_heading: false }, { id: 20, is_heading: true },
               { id: 30, is_heading: false }, { id: 40, is_heading: false }];

// --- resolving against the DRAFT's steps ----------------------------------------------------------

test("the numbers skip headings, exactly as notes.py::step_numbers does", () => {
  const by = noteStepNumbers(STEPS);
  assert.deepEqual([...by.entries()], [[10, 1], [20, null], [30, 2], [40, 3]]);
});

test("a note's step_no is resolved from the steps it is handed", () => {
  const [n] = resolveNoteSteps([note({ step_id: 30 })], STEPS);
  assert.equal(n.step_no, 2);
  assert.equal(n.step_ok, true);
});

test("a link to a step the draft no longer holds resolves to nothing, and keeps its id", () => {
  // ⚠️ THIS IS WHAT MAKES "delete the step, the note survives unlinked" VISIBLE BEFORE THE SAVE.
  //    The stored step_id stays, so nothing is decided here that the save cannot decide again.
  const [n] = resolveNoteSteps([note({ step_id: 30 })], [STEPS[0], STEPS[1]]);
  assert.equal(n.step_no, null);
  assert.equal(n.step_ok, false);
  assert.equal(n.step_id, 30, "the link is not thrown away by the display");
});

test("a link to a step that has become a heading resolves to nothing too", () => {
  const [n] = resolveNoteSteps([note({ step_id: 30 })],
    STEPS.map((s) => (s.id === 30 ? { ...s, is_heading: true } : s)));
  assert.equal(n.step_no, null);
});

test("every reference is resolved too, and a note with none is untouched", () => {
  const [n] = resolveNoteSteps(
    [note({ refs: [{ ref_index: 0, match_text: "step 9", step_id: 40 }] })], STEPS);
  assert.equal(n.refs[0].step_no, 3);
  assert.equal(resolveNoteSteps([note({})], STEPS)[0].step_no, null);
});

test("resolving returns copies and never reaches the row it was given", () => {
  const rows = [note({ step_id: 30, refs: [{ ref_index: 0, match_text: "step 1", step_id: 10 }] })];
  const before = JSON.stringify(rows);
  resolveNoteSteps(rows, STEPS);
  assert.equal(JSON.stringify(rows), before, "view.draft is a clone and must stay one");
});

// --- the step mentions a save will re-scan ---------------------------------------------------------

test("the mentions are counted the way the server counts them", () => {
  assert.deepEqual(scanMentions("see step 3, then steps 4 and 5"),
    [{ ref_index: 0, match_text: "step 3" }, { ref_index: 1, match_text: "steps 4" }]);
  assert.deepEqual(scanMentions(""), []);
  assert.deepEqual(scanMentions(null), []);
});

test("a reference survives a word inserted before it", () => {
  // ⚠️ KEYED ON (ref_index, match_text), which is write_notes' own carry rule.
  const refs = [{ ref_index: 0, match_text: "step 9", step_id: 77, step_no: 8 }];
  const out = carryRefs(refs, "Rest it, then proceed with step 9.");
  assert.deepEqual(out, [{ ref_index: 0, match_text: "step 9", step_id: 77, step_no: 8 }]);
});

test("rewording the mention DROPS the link rather than printing the old step's number", () => {
  const refs = [{ ref_index: 0, match_text: "step 9", step_id: 77, step_no: 8 }];
  const out = carryRefs(refs, "proceed with step 3.");
  assert.deepEqual(out, [{ ref_index: 0, match_text: "step 3", step_id: null, step_no: null }]);
});

test("deleting the words deletes the reference", () => {
  assert.deepEqual(carryRefs([{ ref_index: 0, match_text: "step 9", step_id: 77 }], "no steps named"),
    []);
});

// --- the operations -------------------------------------------------------------------------------

test("a new note's id is negative, so it cannot be mistaken for a row", () => {
  assert.equal(nextDraftId([]), -1);
  assert.equal(nextDraftId([note({ id: 5 }), note({ id: 9 })]), -1);
  assert.equal(nextDraftId([note({ id: 5 }), note({ id: -1 }), note({ id: -2 })]), -3);
});

test("setting the text re-scans the mentions as the save will", () => {
  const rows = [note({ id: 1, text: "see step 9",
                       refs: [{ ref_index: 0, match_text: "step 9", step_id: 77, step_no: 8 }] })];
  const out = draftSetText(rows, 1, "see step 2 instead");
  assert.equal(out[0].text, "see step 2 instead");
  assert.deepEqual(out[0].refs, [{ ref_index: 0, match_text: "step 2", step_id: null, step_no: null }]);
});

test("every operation returns a new array and leaves the old one alone", () => {
  const rows = [note({ id: 1, text: "a" }), note({ id: 2, text: "b" })];
  const frozen = JSON.stringify(rows);
  for (const out of [draftSetText(rows, 1, "x"), draftSetKind(rows, 1, "tips"),
                     draftSetStep(rows, 1, 30), draftAdd(rows, { text: "c" }),
                     draftDelete(rows, 1), draftRestore(rows, note({ id: 9 }), 0)]) {
    assert.notEqual(out, rows);
  }
  assert.equal(JSON.stringify(rows), frozen);
});

test("the kind changes and the words do not", () => {
  const out = draftSetKind([note({ id: 1, text: "Tip: rest it." })], 1, "storage");
  assert.equal(out[0].kind, "storage");
  assert.equal(out[0].text, "Tip: rest it.", "moving a note between types is not an edit to it");
});

test("the step link takes a number or a null, and a string id still finds the row", () => {
  assert.equal(draftSetStep([note({ id: 1 })], "1", "30")[0].step_id, 30);
  assert.equal(draftSetStep([note({ id: 1, step_id: 30 })], 1, null)[0].step_id, null);
});

test("a new note goes at the end, where the adder is and where the save will put it", () => {
  const out = draftAdd([note({ id: 1, text: "a" })], { text: "b", stepId: 30 });
  assert.equal(out.length, 2);
  assert.equal(out[1].text, "b");
  assert.equal(out[1].step_id, 30);
  assert.equal(out[1].position, 1);
  assert.ok(out[1].id < 0);
});

test("deleting renumbers the positions it left behind", () => {
  const out = draftDelete([note({ id: 1, position: 0 }), note({ id: 2, position: 1 }),
                           note({ id: 3, position: 2 })], 2);
  assert.deepEqual(out.map((n) => [n.id, n.position]), [[1, 0], [3, 1]]);
});

test("undo puts a deleted note back where it was", () => {
  const rows = [note({ id: 1, text: "a" }), note({ id: 3, text: "c" })];
  const out = draftRestore(rows, note({ id: 2, text: "b" }), 1);
  assert.deepEqual(out.map((n) => n.text), ["a", "b", "c"]);
  assert.deepEqual(out.map((n) => n.position), [0, 1, 2]);
});

test("undo past the end lands at the end rather than throwing", () => {
  assert.equal(draftRestore([note({ id: 1 })], note({ id: 2 }), 99).length, 2);
  assert.equal(draftRestore([note({ id: 1 })], note({ id: 2 }), null)[1].id, 2);
});

// --- what the save carries --------------------------------------------------------------------

test("the payload is the shape write_notes reads, and carries no client-only field", () => {
  const out = notesPayload([note({ id: -3, text: " keep me ", kind: "tips", step_id: 30,
                                   step_no: 2, display: "keep me", displayStripped: true,
                                   refs: [{ ref_index: 0, match_text: "step 1", step_id: 10,
                                            step_no: 1 }] })]);
  assert.deepEqual(out, [{
    text: "keep me", kind: "tips", step_id: 30, ingredient_row_id: null,
    refs: [{ ref_index: 0, match_text: "step 1", step_id: 10 }],
  }]);
  assert.ok(!("id" in out[0]), "a draft id never leaves the client");
  assert.ok(!("step_no" in out[0]), "the number is derived and the server derives it");
});

test("a note left blank is not sent, exactly like a blank ingredient row", () => {
  assert.deepEqual(notesPayload([note({ id: 1, text: "   " }), note({ id: 2, text: "real" })])
    .map((n) => n.text), ["real"]);
});

test("an empty list is sent as an empty list, because that is how the editor clears them", () => {
  assert.deepEqual(notesPayload([]), []);
  assert.deepEqual(notesPayload(null), []);
});

// --- the id names the row the note came from ------------------------------------------------

test("the payload names the row each note came from", () => {
  // ⚠️ WITHOUT IT THE SERVER PAIRS BY WORDING AND THEN BY ORDER, which reads "delete A, add B" and
  //    "reword A" as the same list of the same length.
  const out = notesPayload([note({ id: 12, text: "kept" })]);
  assert.equal(out[0].id, 12);
});

test("a note written this session has no id, so the server gives it a new row", () => {
  const out = notesPayload(draftAdd([note({ id: 12, text: "kept" })], { text: "brand new" }));
  assert.equal(out[0].id, 12);
  assert.ok(!("id" in out[1]), "a negative draft id never leaves the client");
});

test("only a real row id is sent", () => {
  for (const bad of [null, undefined, 0, -1, "", "abc", NaN, false]) {
    const out = notesPayload([{ ...note({ text: "x" }), id: bad }]);
    assert.ok(!("id" in out[0]), `id ${JSON.stringify(bad)} should not be sent`);
  }
  assert.equal(notesPayload([{ ...note({ text: "x" }), id: "12" }])[0].id, 12,
    "a numeric string is still a row id");
});
