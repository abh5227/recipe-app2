"use strict";
// Notes held in the Edit-mode draft. Every function here changes a LIST, which is the whole reason
// Cancel can throw the session away: nothing has been written.
import { test } from "node:test";
import assert from "node:assert/strict";
import { noteStepNumbers, resolveNoteSteps, scanMentions, carryRefs, nextDraftId,
         draftSetText, draftSetKind, draftSetStep, draftAdd, draftDelete, draftRestore,
         notesPayload, noteGroupKey, draftReorder, draftAddBeside,
         noteDragMates } from "../../static/note-draft.js";
import { noteSections } from "../../static/note-blocks.js";
import { readFileSync } from "node:fs";

const TABLE = JSON.parse(readFileSync(
  new URL("../../static/note-kinds.json", import.meta.url), "utf8")).kinds;

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


// --- the group a drag may move a note inside ------------------------------------------------------
// ⚠️ EVERY ONE OF THESE READS resolveNoteSteps FIRST, because a group key is a question about the
//    NUMBER a note reads under and the raw draft row carries only the id.

const linked = (id, stepId, kind = "notes") =>
  note({ id, step_id: stepId, kind, text: `note ${id}` });

test("a linked note's group is its step, and an unlinked note's is its type", () => {
  const rows = resolveNoteSteps([linked(1, 30), note({ id: 2, kind: "storage", text: "s" })], STEPS);
  assert.equal(noteGroupKey(rows[0], TABLE), "step:2");
  assert.equal(noteGroupKey(rows[1], TABLE), "kind:storage");
});

test("a kind the table does not list takes the first kind's group, as the display does", () => {
  // noteBlocks maps an unknown kind onto table[0], so two notes that READ as one group must key
  // as one group too, or a drop the page offers would be refused.
  const rows = resolveNoteSteps([note({ id: 1, kind: "wat", text: "a" }),
                                 note({ id: 2, kind: "notes", text: "b" })], STEPS);
  assert.equal(noteGroupKey(rows[0], TABLE), noteGroupKey(rows[1], TABLE));
  assert.equal(noteGroupKey(rows[0], TABLE), `kind:${TABLE[0].kind}`);
});

test("a note whose step has gone is grouped by its type, not by a step it cannot print", () => {
  const rows = resolveNoteSteps([linked(1, 30)], [STEPS[0]]);
  assert.equal(noteGroupKey(rows[0], TABLE), "kind:notes");
});

// --- reorder within a group ----------------------------------------------------------------------

test("two notes on one step swap, and nothing else moves", () => {
  const rows = resolveNoteSteps(
    [linked(1, 30), linked(2, 30), note({ id: 3, kind: "storage", text: "s" })], STEPS);
  const out = draftReorder(rows, TABLE, 2, 1);
  assert.deepEqual(out.map((n) => n.id), [2, 1, 3]);
  assert.deepEqual(out.map((n) => n.position), [0, 1, 2]);
});

test("a drop into ANOTHER group is refused and changes nothing", () => {
  const rows = resolveNoteSteps(
    [linked(1, 30), note({ id: 2, kind: "storage", text: "s" })], STEPS);
  assert.equal(draftReorder(rows, TABLE, 1, 2), null);
  assert.equal(draftReorder(rows, TABLE, 2, 1), null);
});

test("a drop onto a note on a DIFFERENT step is refused, though both read under STEP NOTES", () => {
  // ⚠️ THE GROUP ON SCREEN IS ONE BLOCK AND THE RULE IS FINER THAN THAT. STEP NOTES is ordered by
  //    step number, so a note moved across steps would be sorted straight back.
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 40)], STEPS);
  assert.equal(draftReorder(rows, TABLE, 1, 2), null);
});

test("a drop onto itself is refused, so an idle drag writes nothing", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.equal(draftReorder(rows, TABLE, 1, 1), null);
});

test("a stale id is refused rather than appended", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.equal(draftReorder(rows, TABLE, 99, 1), null);
  assert.equal(draftReorder(rows, TABLE, 1, 99), null);
});

test("beforeId null moves a note to the end of ITS OWN run, not to the end of the list", () => {
  // The storage note sits after the two step notes in the flat list. Dropping note 1 past the last
  // step note must land it between note 2 and the storage note.
  const rows = resolveNoteSteps(
    [linked(1, 30), linked(2, 30), note({ id: 3, kind: "storage", text: "s" })], STEPS);
  const out = draftReorder(rows, TABLE, 1, null);
  assert.deepEqual(out.map((n) => n.id), [2, 1, 3]);
});

test("a note already last in its run is refused when dropped past the end", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.equal(draftReorder(rows, TABLE, 2, null), null);
});

test("a reorder keeps every row's id, text, kind and link", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const out = draftReorder(rows, TABLE, 2, 1);
  for (const id of [1, 2]) {
    const was = rows.find((n) => n.id === id), now = out.find((n) => n.id === id);
    assert.equal(now.text, was.text);
    assert.equal(now.kind, was.kind);
    assert.equal(now.step_id, was.step_id);
  }
});

test("the input list is never mutated", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const before = JSON.stringify(rows);
  draftReorder(rows, TABLE, 2, 1);
  assert.equal(JSON.stringify(rows), before);
});

test("what the reading view shows after a save is the order the reorder wrote", () => {
  // ⚠️ THE RULE THE WHOLE FEATURE RESTS ON. noteSections reads the list order within a group, and
  //    write_notes assigns position from the order it is given, so the two cannot disagree.
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const out = draftReorder(rows, TABLE, 2, 1);
  const { steps } = noteSections(out, TABLE);
  assert.deepEqual(steps.map((n) => n.id), [2, 1]);
});

// --- add above / add below -----------------------------------------------------------------------

test("a note added below copies its neighbour's type and step link", () => {
  const rows = resolveNoteSteps([linked(1, 30, "storage")], STEPS);
  const out = draftAddBeside(rows, TABLE, 1, "below");
  assert.equal(out.length, 2);
  assert.equal(out[1].kind, "storage");
  assert.equal(out[1].step_id, 30);
  assert.equal(out[1].text, "");
});

test("a note added above takes the neighbour's place in the list", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const out = draftAddBeside(rows, TABLE, 2, "above");
  assert.deepEqual(out.map((n) => n.id), [1, nextDraftId(rows), 2]);
});

test("the added note lands in its neighbour's group, which is what 'stays in place' means", () => {
  const rows = resolveNoteSteps(
    [linked(1, 30), note({ id: 2, kind: "storage", text: "s" })], STEPS);
  const out = draftAddBeside(rows, TABLE, 1, "below");
  const added = out.find((n) => n.id < 0);
  assert.equal(noteGroupKey(resolveNoteSteps([added], STEPS)[0], TABLE),
               noteGroupKey(rows[0], TABLE));
});

test("a neighbour linked only by its WORDS still hands over the step, as an id", () => {
  // ⚠️ THE CASE THAT NEEDED linkedStepId. The neighbour reaches step 2 through "see step 2" in its
  //    text; the new note has no text, so the only way to put it there is its own link.
  const rows = resolveNoteSteps(
    [note({ id: 1, text: "see step 2", refs: [{ ref_index: 0, match_text: "step 2", step_id: 30 }] })],
    STEPS);
  assert.equal(rows[0].step_no, null, "the note itself carries no own link");
  const out = draftAddBeside(rows, TABLE, 1, "below");
  assert.equal(out[1].step_id, 30);
});

test("a new note's id is negative, so the save gives it a new row", () => {
  const rows = resolveNoteSteps([linked(1, 30)], STEPS);
  const out = draftAddBeside(rows, TABLE, 1, "below");
  assert.ok(out[1].id < 0);
  assert.deepEqual(notesPayload(out).map((n) => n.id), [1], "a blank new note is not sent at all");
});

test("a stale id adds nothing", () => {
  const rows = resolveNoteSteps([linked(1, 30)], STEPS);
  assert.equal(draftAddBeside(rows, TABLE, 99, "below"), null);
});

test("every position is renumbered 0..n-1 after an add", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const out = draftAddBeside(rows, TABLE, 1, "below");
  assert.deepEqual(out.map((n) => n.position), [0, 1, 2]);
});

test("the ids may arrive as STRINGS, which is how the DOM hands them over", () => {
  // ⚠️ THE DEFECT THIS PINS. app.js reads both ids off data-note-row, so they are strings, and
  //    reorderBefore's indexOf is an identity test against a list of numbers. A note dropped at
  //    the TOP of its group landed at the bottom of it, with no error anywhere.
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30), linked(3, 30)], STEPS);
  assert.deepEqual(draftReorder(rows, TABLE, "2", "1").map((n) => n.id), [2, 1, 3]);
  assert.deepEqual(draftReorder(rows, TABLE, "1", null).map((n) => n.id), [2, 3, 1]);
  assert.equal(draftReorder(rows, TABLE, "3", "3"), null);
});

test("a string id is refused across groups just the same", () => {
  const rows = resolveNoteSteps(
    [linked(1, 30), note({ id: 2, kind: "storage", text: "s" })], STEPS);
  assert.equal(draftReorder(rows, TABLE, "1", "2"), null);
});

test("draftAddBeside takes a string id too", () => {
  const rows = resolveNoteSteps([linked(1, 30, "storage")], STEPS);
  const out = draftAddBeside(rows, TABLE, "1", "below");
  assert.equal(out.length, 2);
  assert.equal(out[1].step_id, 30);
});

// --- which notes get a grip ----------------------------------------------------------------------
// ⚠️ THE QUESTION IS ABOUT THE OTHER NOTES, NOT ABOUT THIS ONE. A note alone in its drag group has
//    no legal drop target, so a handle on it offers a move that can only snap back.

test("a note alone in its group has no mate, and two together both do", () => {
  const rows = resolveNoteSteps([linked(1, 30), note({ id: 2, kind: "storage", text: "s" })], STEPS);
  assert.deepEqual([...noteDragMates(rows, TABLE)], []);
  const pair = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.deepEqual([...noteDragMates(pair, TABLE)].sort(), ["1", "2"]);
});

test("two notes under STEP NOTES on DIFFERENT steps are each alone", () => {
  // They share one heading on screen and neither can move, which is the case the bagel shows.
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 40)], STEPS);
  assert.deepEqual([...noteDragMates(rows, TABLE)], []);
});

test("a group of three gives all three a mate, and a lone fourth none", () => {
  const rows = resolveNoteSteps(
    [note({ id: 1, kind: "notes", text: "a" }), note({ id: 2, kind: "notes", text: "b" }),
     note({ id: 3, kind: "notes", text: "c" }), note({ id: 4, kind: "storage", text: "d" })], STEPS);
  assert.deepEqual([...noteDragMates(rows, TABLE)].sort(), ["1", "2", "3"]);
});

test("the ids come back as STRINGS, which is what the renderer looks them up with", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  const mates = noteDragMates(rows, TABLE);
  assert.ok(mates.has("1"), "a String id is found");
  assert.ok(!mates.has(1), "and a number is deliberately not, so a caller cannot mix the two");
});

test("adding a note beside a lone one gives BOTH a grip", () => {
  // ⚠️ THE LIVE HALF OF THE RULE. The renderer asks this again on every repaint, so an add, a
  //    delete, a relink or a type change gives or takes the handle away as it happens.
  const rows = resolveNoteSteps([linked(1, 30)], STEPS);
  assert.deepEqual([...noteDragMates(rows, TABLE)], [], "alone to begin with");
  const after = resolveNoteSteps(draftAddBeside(rows, TABLE, 1, "below"), STEPS);
  assert.equal(after.length, 2);
  assert.equal(noteDragMates(after, TABLE).size, 2, "the new note is in the same group");
});

test("deleting one of a pair takes the other's grip away", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.equal(noteDragMates(rows, TABLE).size, 2);
  assert.deepEqual([...noteDragMates(draftDelete(rows, 2), TABLE)], []);
});

test("re-typing a note out of its group takes the grip from both", () => {
  const rows = resolveNoteSteps(
    [note({ id: 1, kind: "notes", text: "a" }), note({ id: 2, kind: "notes", text: "b" })], STEPS);
  assert.equal(noteDragMates(rows, TABLE).size, 2);
  const moved = resolveNoteSteps(draftSetKind(rows, 2, "storage"), STEPS);
  assert.deepEqual([...noteDragMates(moved, TABLE)], []);
});

test("re-linking a note to another step takes the grip from both", () => {
  const rows = resolveNoteSteps([linked(1, 30), linked(2, 30)], STEPS);
  assert.equal(noteDragMates(rows, TABLE).size, 2);
  const moved = resolveNoteSteps(draftSetStep(rows, 2, 40), STEPS);
  assert.deepEqual([...noteDragMates(moved, TABLE)], []);
});

test("a note whose step has gone joins the type group, and can gain a mate there", () => {
  const rows = resolveNoteSteps(
    [linked(1, 30), note({ id: 2, kind: "notes", text: "b" })], STEPS);
  assert.deepEqual([...noteDragMates(rows, TABLE)], [], "one is on a step, one is not");
  const gone = resolveNoteSteps([linked(1, 30), note({ id: 2, kind: "notes", text: "b" })],
                                [STEPS[0]]);
  assert.deepEqual([...noteDragMates(gone, TABLE)].sort(), ["1", "2"],
    "the link resolves to nothing, so both read under Notes");
});

test("an empty list answers with an empty set rather than throwing", () => {
  assert.equal(noteDragMates([], TABLE).size, 0);
  assert.equal(noteDragMates(null, TABLE).size, 0);
});

test("every note with a mate can actually be moved, which is the rule's whole point", () => {
  // ⚠️ THE TWO HALVES ARE STATED TOGETHER ON PURPOSE. A grip is a promise that draftReorder will
  //    accept a drop, so the set and the operation are checked against each other rather than
  //    separately.
  const rows = resolveNoteSteps(
    [linked(1, 30), linked(2, 30), note({ id: 3, kind: "storage", text: "s" })], STEPS);
  const mates = noteDragMates(rows, TABLE);
  for (const r of rows) {
    const others = rows.filter((x) => x.id !== r.id);
    const legal = others.some((o) => draftReorder(rows, TABLE, r.id, o.id) !== null)
      || draftReorder(rows, TABLE, r.id, null) !== null;
    assert.equal(mates.has(String(r.id)), legal,
      `note ${r.id}: grip ${mates.has(String(r.id))} but a legal drop is ${legal}`);
  }
});
