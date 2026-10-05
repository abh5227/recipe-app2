"use strict";
// The Notes grouping, display-only. The stored text keeps the author's labels; this decides what
// the page shows. The kind table is static/note-kinds.json, the SAME file app.js imports and
// import_cleanup reads, so a label means one thing across the whole app.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { noteBlocks, noteBlocksFromText, noteParagraphs, classifyNote, displayText,
         noteSections, linkedStepNo, STEP_NOTES_HEADER } from "../../static/note-blocks.js";

const TABLE = JSON.parse(fs.readFileSync(
  path.join(import.meta.dirname, "../../static/note-kinds.json"), "utf8")).kinds;

// ⚠️ THE MODULE TAKES ROWS SINCE MIGRATION 060. noteBlocksFromText is the old string shape, kept
// for a payload from a previous deploy, and it is what lets these cases stay stated as prose — the
// grouping decisions they pin are the same whichever door the notes come in by.
const shape = (t) => noteBlocksFromText(t, TABLE).map((b) => [b.header, b.notes.map((n) => n.display)]);
const rowShape = (rows) => noteBlocks(rows, TABLE).map((b) => [b.header, b.notes.map((n) => n.display)]);
const row = (o) => ({ id: 1, kind: "notes", text: "", step_id: null, step_no: null, refs: [], ...o });

test("the kind table is the one file both sides read", () => {
  assert.ok(TABLE.length >= 4, "the kind list lost entries");
  assert.equal(TABLE[0].kind, "notes", "the first kind is the fallback and must be Notes");
  for (const k of TABLE) {
    assert.ok(k.kind && k.header && Array.isArray(k.labels) && k.labels.length);
  }
});

test("beans: two Note paragraphs and a Tip become two blocks, labels stripped", () => {
  assert.deepEqual(shape(
    "Note: Some legumes need no soak.\n\nNote: Save the bean liquid.\n\nTip: Add herbs."), [
    ["Notes", ["Some legumes need no soak.", "Save the bean liquid."]],
    ["Tips", ["Add herbs."]],
  ]);
});

test("an unlisted label keeps its text WHOLE and stays under Notes", () => {
  // ⚠️ THE COMMON CASE, NOT THE EDGE ONE. 17 of the corpus's labelled paragraphs are one-off topic
  // labels, and stripping one deletes the only thing naming what the note is about.
  assert.deepEqual(shape("Blind Bake: Place a coffee filter into the shell."),
    [["Notes", ["Blind Bake: Place a coffee filter into the shell."]]]);
});

test("a paragraph with no label at all is untouched", () => {
  assert.deepEqual(shape("Consider using vital wheat gluten."),
    [["Notes", ["Consider using vital wheat gluten."]]]);
});

test("the period form is a label too", () => {
  // brioche-bread writes "Storing. Brioche can be stored..." with a full stop, not a colon.
  assert.deepEqual(shape("Storing. Brioche keeps three days."),
    [["Storage", ["Brioche keeps three days."]]]);
});

test("a kind is ONE block even when its paragraphs are not adjacent", () => {
  assert.deepEqual(shape("Note: first.\n\nTip: a tip.\n\nNote: second."), [
    ["Notes", ["first.", "second."]],
    ["Tips", ["a tip."]],
  ]);
});

test("a sentence that merely looks short is not a label", () => {
  // "Made with Vedant and Sophia." has nothing after it, so there is no label and no content split.
  assert.deepEqual(shape("Made with Vedant and Sophia."),
    [["Notes", ["Made with Vedant and Sophia."]]]);
});

test("empty and null notes produce no blocks at all", () => {
  for (const v of ["", "   ", "\n\n", null, undefined]) assert.deepEqual(noteBlocksFromText(v, TABLE), []);
  for (const v of [[], null, undefined]) assert.deepEqual(noteBlocks(v, TABLE), []);
});

test("paragraphs split on a blank line and a line break inside one survives", () => {
  // white-space: pre-wrap on .notes-para is what renders it, so the break has to reach the text.
  assert.deepEqual(noteParagraphs("a\nstill a\n\nb"), ["a\nstill a", "b"]);
});

test("a curly apostrophe in a label matches the straight one in the table", () => {
  assert.equal(classifyNote("Cook’s note: taste it.", TABLE).kind, "notes");
});


test("a ROW is grouped by its kind column, not by its label", () => {
  // ⚠️ THE COLUMN IS AUTHORITATIVE. A cook who moves a note into Storage has changed the kind, and
  // the words stay exactly as they were typed.
  assert.deepEqual(rowShape([row({ id: 1, kind: "storage", text: "Keeps three days." })]),
    [["Storage", ["Keeps three days."]]]);
});

test("a label is stripped only when it AGREES with the row's kind", () => {
  // Agreeing: the word is redundant with the header above it, so it goes.
  assert.equal(displayText(row({ kind: "tips", text: "Tip: Add herbs." }), TABLE), "Add herbs.");
  // Disagreeing: the cook moved it, and hiding the word would quietly edit the note to match a
  // decision they can still undo.
  assert.equal(displayText(row({ kind: "storage", text: "Tip: Add herbs." }), TABLE),
    "Tip: Add herbs.");
});

test("an unknown kind on a row falls back to Notes rather than vanishing", () => {
  assert.deepEqual(rowShape([row({ kind: "nonsense", text: "Something." })]),
    [["Notes", ["Something."]]]);
});

test("rows keep their id, their step link and their references through the grouping", () => {
  const [block] = noteBlocks([row({ id: 7, step_id: 42, step_no: 3,
                                    refs: [{ ref_index: 0, match_text: "step 3", step_no: 3 }],
                                    text: "Proceed with step 3." })], TABLE);
  assert.equal(block.notes[0].id, 7);
  assert.equal(block.notes[0].step_no, 3);
  assert.equal(block.notes[0].refs[0].match_text, "step 3");
});

// ---------------------------------------------------------------------------------------------
// noteSections: the Notes section's arrangement, which is ONE rule read by the recipe page and by
// Edit mode. The "linked" question is linkedStepNo and nothing else asks it a second way.
// ---------------------------------------------------------------------------------------------
const sect = (rows) => noteSections(rows, TABLE);
const sectShape = (rows) => {
  const { steps, blocks } = sect(rows);
  return [steps.map((n) => [n.stepLinkNo, n.display]),
          blocks.map((b) => [b.header, b.notes.map((n) => n.display)])];
};

test("linked means an own step link OR a step named in the words", () => {
  assert.equal(linkedStepNo(row({ step_id: 7, step_no: 3 })), 3, "its own link");
  assert.equal(linkedStepNo(row({ refs: [{ ref_index: 0, step_id: 7, step_no: 5 }] })), 5,
    "a step named in its words");
  assert.equal(linkedStepNo(row({})), null, "neither");
});

test("a link whose step became a heading is NOT linked, because there is no number to order by", () => {
  // The server resolves step_no to null for a heading, which is the same rule a wait follows: a
  // wrong number is worse than no link. The note keeps its stored step_id and reads in its type
  // group rather than under a STEP NOTES heading that cannot say which step.
  assert.equal(linkedStepNo(row({ step_id: 7, step_no: null })), null);
  const [steps, blocks] = sectShape([row({ id: 1, text: "Tip: watch it.", kind: "tips",
                                           step_id: 7, step_no: null })]);
  assert.deepEqual(steps, []);
  assert.deepEqual(blocks, [["Tips", ["watch it."]]]);
});

test("an own link is asked first and alone, so a mention does not overrule it", () => {
  // A note carrying step_id is where its author put it. Its own link resolving to nothing does not
  // quietly re-file it under a step it merely mentions.
  assert.equal(linkedStepNo(row({ step_id: 7, step_no: null,
                                  refs: [{ ref_index: 0, step_id: 9, step_no: 4 }] })), null);
  assert.equal(linkedStepNo(row({ step_id: 7, step_no: 2,
                                  refs: [{ ref_index: 0, step_id: 9, step_no: 4 }] })), 2);
});

test("a linked note leaves its type group entirely and appears once", () => {
  const [steps, blocks] = sectShape([
    row({ id: 1, kind: "tips", text: "Tip: rest it.", step_id: 4, step_no: 2 }),
    row({ id: 2, kind: "tips", text: "Tip: salt early." }),
  ]);
  assert.deepEqual(steps, [[2, "rest it."]]);
  assert.deepEqual(blocks, [["Tips", ["salt early."]]], "the linked one is not here as well");
});

test("step notes are ordered by step number, then by the order they were given in", () => {
  const [steps] = sectShape([
    row({ id: 1, text: "c", step_id: 30, step_no: 3 }),
    row({ id: 2, text: "a", step_id: 10, step_no: 1 }),
    row({ id: 3, text: "b", step_id: 10, step_no: 1 }),
  ]);
  assert.deepEqual(steps, [[1, "a"], [1, "b"], [3, "c"]],
    "two notes on one step keep the order the cook put them in");
});

test("a note linked ONLY by its words sorts on the step it names", () => {
  const [steps, blocks] = sectShape([
    row({ id: 1, text: "Mix, then see step 6 for the rest.",
          refs: [{ ref_index: 0, match_text: "step 6", step_id: 60, step_no: 6 }] }),
    row({ id: 2, text: "Early one.", step_id: 10, step_no: 2 }),
  ]);
  assert.deepEqual(steps.map((x) => x[0]), [2, 6]);
  assert.deepEqual(blocks, []);
});

test("with nothing linked there is no step group at all", () => {
  const [steps, blocks] = sectShape([row({ id: 1, text: "Just a note." })]);
  assert.deepEqual(steps, [], "no empty STEP NOTES heading on the 294 recipes without one");
  assert.deepEqual(blocks, [["Notes", ["Just a note."]]]);
});

test("the step group carries the SAME display text the type group would have", () => {
  // One decorator, so a note does not read one way under STEP NOTES and another under its type.
  const linked = sect([row({ id: 1, kind: "variations", text: "Variation: add cheese.",
                             step_id: 4, step_no: 2 })]).steps[0];
  const plain = sect([row({ id: 1, kind: "variations", text: "Variation: add cheese." })])
    .blocks[0].notes[0];
  assert.equal(linked.display, "add cheese.");
  assert.equal(linked.display, plain.display);
  assert.equal(linked.displayStripped, plain.displayStripped);
});

test("an unknown kind is settled the same way in both halves", () => {
  const linked = sect([row({ id: 1, kind: "nonsense", text: "x", step_id: 4, step_no: 1 })]).steps[0];
  assert.equal(linked.kind, "notes", "the fallback kind, as noteBlocks would have given it");
});

test("the step-notes header is a plain string, uppercased by the shared heading rule", () => {
  assert.equal(STEP_NOTES_HEADER, "Step notes");
  assert.equal(STEP_NOTES_HEADER, STEP_NOTES_HEADER.trim());
});
