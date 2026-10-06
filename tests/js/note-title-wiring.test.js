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

/** The body of the named top-level function, by brace matching.
 * ⚠️ THE OPENING BRACE IS THE ONE AFTER THE PARAMETER LIST, not the first one found. flashSaved
 * takes a DESTRUCTURED options object, so "the first { after the name" returned
 * "{ created = false }" and every assertion about the function's body failed against it. */
function body(name) {
  const at = APP.indexOf(`function ${name}(`);
  assert.ok(at > 0, `${name} is not in app.js`);
  let depth = 0, close = -1;
  for (let i = APP.indexOf("(", at); i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")" && --depth === 0) { close = i; break; }
  }
  assert.ok(close > 0, `${name}'s parameter list never closes`);
  const open = APP.indexOf("{", close);
  depth = 0;
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

// ---- "+ note" opens the whole panel (Andy's call, 2026-10-06) -----------------------------------
// ⚠️ THE NEW-NOTE BOX WAS THE ONE PLACE THAT DID NOT SHARE THE EDITOR, and it had its own state
// (newText), its own attribute (data-new-note-input), its own save call on the Enter handler, its
// own branch in restoreNoteFocus and its own branch in click-away. Five copies of "a note is being
// typed". The panel is the editor now, so what is checked here is that those five are GONE rather
// than that a sixth has been added beside them.

// ⚠️ A "THIS IS GONE" ASSERTION HAS TO READ THE CODE, NOT THE COMMENTS, and the first draft of
// this test did not: the comment explaining that [data-new-note-input] had been removed was itself
// a match for it, so the test failed on the explanation of its own subject.
const CODE = APP.replace(/\/\/[^\n]*/g, "");

test("the new-note box carries no state, no attribute and no handler of its own", () => {
  assert.doesNotMatch(CODE, /newText/, "noteState.newText survived the fold");
  assert.doesNotMatch(CODE, /data-new-note-input/,
    "a selector for the bare box's own attribute survived");
  assert.doesNotMatch(CODE, /data-new-note=/, "the bare box's wrapper attribute survived");
});

test("+ note opens an editor, so every shared handler finds it", () => {
  const b = body("handleNoteAction");
  // the add branch sets the editor's own state rather than a parallel set
  assert.match(b, /noteState\.newRow = newNoteRow\(where, NOTE_KINDS\.kinds\)/);
  assert.match(b, /noteState\.editingId = NEW_NOTE_ID/);
  assert.match(b, /noteState\.editingPlace = `new:\$\{where\}`/);
  assert.match(b, /noteState\.drafts\.set\(NEW_NOTE_ID, ""\)/);
  assert.match(b, /noteState\.titleDrafts\.set\(NEW_NOTE_ID, ""\)/);
});

test("saveOpenNote is the one entry point, and it decides create against patch", () => {
  const b = body("saveOpenNote");
  assert.match(b, /String\(id\) === String\(NEW_NOTE_ID\)\) return saveNewNote\(\)/,
    "a new note has to reach saveNewNote through the shared save, not past it");
});

test("the create carries the title, the type and the step the panel was holding", () => {
  const b = body("saveNewNote");
  assert.match(b, /noteDraft\(NEW_NOTE_ID\)/, "the text comes from the shared draft map");
  assert.match(b, /noteTitleDraft\(NEW_NOTE_ID\)/, "the title comes from the shared draft map");
  assert.match(b, /if \(title\) body\.title = title/);
  assert.match(b, /if \(row\.kind\) body\.kind = row\.kind/);
  assert.match(b, /if \(stepId != null\) body\.step_id = stepId/);
  // an empty new note is still dropped, which is what "+ note" has always done
  assert.match(b, /if \(!text\) \{ closeNoteEditors\(\); repaintNotes\(\); return Promise\.resolve\(\); \}/);
});

test("closing throws the unsaved row away with the drafts", () => {
  // ⚠️ WITHOUT IT the next "+ note" opens holding the last one's type and step link.
  assert.match(body("closeNoteEditors"), /noteState\.newRow = null/);
});

test("the type and the link on a new note are local, never a write", () => {
  // ⚠️ CREATING THE ROW SO THE TYPE COULD BE STORED would make "+ note" write the moment it was
  //    opened, which is the one thing an empty new note must not do.
  for (const fn of ["setNoteKind", "setNoteStep"]) {
    const b = body(fn);
    assert.match(b, /String\(id\) === String\(NEW_NOTE_ID\) && noteState\.newRow/, fn);
    assert.match(b, /return Promise\.resolve\(\)/, fn);
  }
});

test("one lookup answers 'which note is this' for a row the server has never seen", () => {
  const b = body("noteRowFor");
  assert.match(b, /noteState\.newRow/);
  assert.match(b, /resolveNoteSteps/, "step_no is resolved, never stored");
  // and the write paths ask it rather than doing their own find
  for (const fn of ["setNoteKind", "setNoteStep"]) {
    assert.match(body(fn), /noteRowFor\(id\)/, fn);
  }
});

test("the panel's menus read the same state a stored note's do", () => {
  const b = body("noteNewBoxHTML");
  assert.match(b, /kindMenu: noteState\.kindMenuFor === NEW_NOTE_ID/);
  assert.match(b, /stepMenu: noteState\.stepMenuFor === NEW_NOTE_ID/);
  assert.match(b, /resolveNoteSteps\(\[noteState\.newRow\], currentSteps\(\)\)/);
});

test("the Undo after a create is a DELETE, because there is no earlier version", () => {
  // ⚠️ IT USED TO DO NOTHING. saveNewNote drew "Saved · Undo" and undoNote returned early on a null
  //    `before`, so the one control on that toast was dead. Found while folding "+ note" into the
  //    editor, which is where "same save rules as editing" has to mean something.
  assert.match(body("saveNewNote"), /flashSaved\(data\.note\.id, null, \{ created: true \}\)/);
  const b = body("undoNote");
  assert.match(b, /const created = noteState\.savedNew/);
  assert.match(b, /if \(created\) \{ repaintNotes\(\); return deleteNote\(id\); \}/);
  // and the flag is cleared everywhere savedId is, or the next save's Undo would delete
  assert.match(body("flashSaved"), /noteState\.savedNew = !!created/);
  assert.match(body("flashSaved"), /noteState\.savedNew = false/);
  assert.match(body("enterEditMode"), /noteState\.savedNew = false/);
});
