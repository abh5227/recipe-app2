"use strict";
// ⚠️ TWO LINES OF static/app.js WERE UNTESTED, AND A FRESH REVIEW PROVED IT by deleting each one and
// finding the JS suite still green:
//
//   noteState.titleDrafts.clear()       in closeNoteEditors
//   if (titleMoved) body.title = ...    in saveOpenNote
//
// app.js is not importable in the zero-dep suite (it touches document at module scope), so what is
// checked here is the SOURCE: the wiring exists, and the two decisions it encodes are stated as
// executable rules against the extracted modules beside it. A source read is a weaker test than
// running the function and it is a great deal stronger than nothing, which is what was there.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { noteTitleChanged, notePatchBody } from "../../static/note-ui.js";
import { draftSetTitle, draftSetText } from "../../static/note-draft.js";

const APP = fs.readFileSync(path.join(import.meta.dirname, "../../static/app.js"), "utf8");

/** The body of the named top-level function, by brace matching. */
function body(name) {
  const at = APP.indexOf(`function ${name}(`);
  assert.ok(at > 0, `${name} is not in app.js`);
  const open = APP.indexOf("{", at);
  let depth = 0;
  for (let i = open; i < APP.length; i++) {
    if (APP[i] === "{") depth++;
    else if (APP[i] === "}" && --depth === 0) return APP.slice(open, i + 1);
  }
  throw new Error(`${name} never closes`);
}

test("closeNoteEditors clears BOTH draft maps, or a title leaks to the next note", () => {
  // ⚠️ WITHOUT IT the title typed into note A is the title offered for note B, and saveOpenNote
  //    would read it as a change and write it. Every path into an editor goes through here:
  //    the edit branch, enterEditMode, Escape and click-away.
  const b = body("closeNoteEditors");
  assert.match(b, /noteState\.drafts\.clear\(\)/);
  assert.match(b, /noteState\.titleDrafts\.clear\(\)/,
    "the title drafts are not cleared, so they survive into the next note");
  assert.match(b, /noteState\.focusField = "text"/);
});

test("saveOpenNote sends the title only when it moved, and the text only when IT moved", () => {
  const b = body("saveOpenNote");
  assert.match(b, /const textMoved = .*noteTextChanged\(/s);
  assert.match(b, /const titleMoved = .*noteTitleChanged\(/s);
  assert.match(b, /if \(textMoved\) body\.text = /,
    "the text is sent unconditionally, so a title-only edit rewrites the words too");
  assert.match(b, /if \(titleMoved\) body\.title = /,
    "the title is never sent, so every title change on the recipe page is a no-op");
  // the held branch has to carry both the same way
  assert.match(b, /if \(textMoved\) next = draftSetText\(/);
  assert.match(b, /if \(titleMoved\) next = draftSetTitle\(/);
  // and the row is checked before either question is asked, because both read it
  assert.ok(b.indexOf("if (!note)") < b.indexOf("const textMoved"),
    "noteTextChanged runs the display rule over note.text and throws on a missing row");
});

test("the undo body carries the title, or a save puts the row back half way", () => {
  const b = body("saveOpenNote");
  assert.match(b, /const before = \{ text: note\.text, title: /,
    "the Undo offer records only the words, so it would restore them and leave a cleared title");
});

test("the editor is seeded from the row's title and the caret starts in the words", () => {
  const b = body("handleNoteAction");
  assert.match(b, /noteState\.titleDrafts\.set\(id, note && note\.title/,
    "the Title box opens empty on a titled note");
  assert.match(b, /noteState\.focusField = "text"/);
});

test("a repaint restores whichever field had the caret", () => {
  const b = body("restoreNoteFocus");
  assert.match(b, /noteState\.focusField === "title" \? "\[data-note-title\]"/,
    "a repaint while the Title box has focus sends the next keystrokes into the note's TEXT");
  assert.match(b, /\|\| row\.querySelector\("\[data-note-input\]"\)/,
    "and it falls back to the textarea, so a missing box never leaves the caret nowhere");
});

test("the input handler records which field is being typed in", () => {
  const at = APP.indexOf('e.target.closest("[data-note-title]")');
  assert.ok(at > 0, "the Title box has no input handler at all");
  const near = APP.slice(at, at + 260);
  assert.match(near, /noteState\.focusField = "title"/);
  assert.match(near, /noteState\.titleDrafts\.set\(/);
});

test("Enter and Escape reach the editor from the Title box too", () => {
  // Enter in a one-line field otherwise submits nothing, and Escape would close the popover the
  // panel sits in and lose the typed title with no way back.
  assert.match(APP, /closest\("\[data-note-input\], \[data-note-title\]"\)/);
});

// --- and the decisions those lines encode, as executable rules ------------------------------------

test("a title draft from another note would be written as a change, which is what clearing stops", () => {
  const noteA = { id: 1, title: "Flour", text: "x" };
  const noteB = { id: 2, title: null, text: "y" };
  assert.equal(noteTitleChanged(noteB, "Flour"), true,
    "A's leaked draft reads as a change on B, so the map has to be cleared between them");
  assert.equal(noteTitleChanged(noteA, "Flour"), false);
});

test("a title-only edit sends no text, and a text-only edit sends no title", () => {
  assert.deepEqual(notePatchBody({ title: "Flour" }), { title: "Flour" });
  assert.deepEqual(notePatchBody({ text: "x" }), { text: "x" });
  // ⚠️ AND THE SERVER READS ABSENT AS KEEP, which is what makes the conditional safe rather than
  //    lossy: a PATCH naming only the title leaves the words exactly as they were.
  assert.ok(!("text" in notePatchBody({ title: "Flour" })));
  assert.ok(!("title" in notePatchBody({ text: "x" })));
});

test("the held branch changes the title without touching the references", () => {
  const notes = [{ id: 1, title: null, text: "proceed with step 9", kind: "notes",
                   refs: [{ ref_index: 0, match_text: "step 9", step_id: 42 }] }];
  // ⚠️ draftSetText RE-RUNS carryRefs, so it is the one that may reshape a reference. The claim
  //    here is about draftSetTitle, so the title is set on its own.
  const only = draftSetTitle(notes, 1, "Shaping");
  assert.equal(only[0].title, "Shaping");
  assert.equal(only[0].refs, notes[0].refs, "the same array object, untouched");
  const both = draftSetTitle(draftSetText(notes, 1, "proceed with step 9"), 1, "Shaping");
  assert.equal(both[0].title, "Shaping");
  assert.equal(both[0].text, "proceed with step 9");
  assert.deepEqual(both[0].refs.map((r) => [r.ref_index, r.match_text, r.step_id]),
                   [[0, "step 9", 42]], "the reference still names the same step");
});
