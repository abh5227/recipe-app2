"use strict";
// The Notes grouping, display-only. The stored text keeps the author's labels; this decides what
// the page shows. The kind table is static/note-kinds.json, the SAME file app.js imports and
// import_cleanup reads, so a label means one thing across the whole app.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { noteBlocks, noteParagraphs, classifyNote } from "../../static/note-blocks.js";

const TABLE = JSON.parse(fs.readFileSync(
  path.join(import.meta.dirname, "../../static/note-kinds.json"), "utf8")).kinds;

const shape = (t) => noteBlocks(t, TABLE).map((b) => [b.header, b.paras]);

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
  for (const v of ["", "   ", "\n\n", null, undefined]) assert.deepEqual(noteBlocks(v, TABLE), []);
});

test("paragraphs split on a blank line and a line break inside one survives", () => {
  // white-space: pre-wrap on .notes-para is what renders it, so the break has to reach the text.
  assert.deepEqual(noteParagraphs("a\nstill a\n\nb"), ["a\nstill a", "b"]);
});

test("a curly apostrophe in a label matches the straight one in the table", () => {
  assert.equal(classifyNote("Cook’s note: taste it.", TABLE).kind, "notes");
});
