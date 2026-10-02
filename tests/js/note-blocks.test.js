"use strict";
// The Notes grouping, display-only. The stored text keeps the author's labels; this decides what
// the page shows. The kind table is static/note-kinds.json, the SAME file app.js imports and
// import_cleanup reads, so a label means one thing across the whole app.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { noteBlocks, noteBlocksFromText, noteParagraphs, classifyNote, displayText }
  from "../../static/note-blocks.js";

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
