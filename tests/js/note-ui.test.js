"use strict";
// The note component's pure half. One component renders in three places (the Notes section, a step
// popover, Edit mode's block), so the questions here are about what each place gets: who may edit,
// which instance becomes an editor, what the type tag says, and when a "step N" is a link.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { tagLabel, kindOf, kindTagHTML, kindMenuHTML, noteBodyHTML, noteRowHTML, noteInputHTML,
         newNoteBoxHTML, addNoteButtonHTML, refChipsHTML, notePatchBody, noteTextChanged,
         undoToastHTML } from "../../static/note-ui.js";

const TABLE = JSON.parse(fs.readFileSync(
  path.join(import.meta.dirname, "../../static/note-kinds.json"), "utf8")).kinds;

// The app's own escaper, copied in the shape the other pure modules take it: injected, not imported.
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const note = (o) => ({ id: 7, kind: "notes", text: "", step_id: null, step_no: null, refs: [], ...o });

// --- the type tag ---------------------------------------------------------------------------------

test("the five type labels come out of the kind table, not a second list", () => {
  // ⚠️ THE BRIEF NAMES THESE FIVE. The headers are plural ("Notes") and the tag wants the singular
  //    the cook picks ("Note"), so the tag is derived from each kind's own canonical label. If this
  //    fails, note-kinds.json moved and the tag is the thing that noticed.
  assert.deepEqual(TABLE.map(tagLabel), ["Note", "Tip", "Storage", "Variation", "Serving"]);
});

test("an unknown kind falls back to the first one rather than rendering blank", () => {
  assert.equal(kindOf(TABLE, "nonsense").kind, "notes");
  assert.equal(kindOf(TABLE, undefined).kind, "notes");
});

test("an owner's tag is a button and a stranger's is not", () => {
  const mine = kindTagHTML(note({ kind: "tips" }), TABLE, esc, { editable: true });
  const theirs = kindTagHTML(note({ kind: "tips" }), TABLE, esc, { editable: false });
  assert.match(mine, /<button/, "the owner must be able to open the menu");
  assert.match(mine, /data-note-kind="7"/);
  assert.match(mine, /aria-haspopup="true"/);
  assert.doesNotMatch(theirs, /<button/, "a stranger's tag is a label, not a control");
  assert.match(theirs, /note-tag-flat/);
  for (const html of [mine, theirs]) assert.match(html, />Tip/);
});

test("the type menu marks the current kind and offers all five", () => {
  const html = kindMenuHTML(note({ kind: "storage" }), TABLE, esc);
  assert.equal((html.match(/role="menuitemradio"/g) || []).length, 5);
  assert.match(html, /aria-checked="true"[^>]*data-note-set-kind="7" data-kind="storage"/);
  assert.equal((html.match(/aria-checked="true"/g) || []).length, 1);
});

// --- the self-reference rule ----------------------------------------------------------------------

test("a step reference is a link everywhere except the popover it points at", () => {
  const n = note({
    text: "This matters at step 3 and again at step 5",
    refs: [{ ref_index: 0, match_text: "step 3", step_id: 30, step_no: 3 },
           { ref_index: 1, match_text: "step 5", step_id: 50, step_no: 5 }],
  });
  const section = noteBodyHTML(n, TABLE, esc, {});
  assert.equal((section.match(/note-stepref/g) || []).length, 2, "both link in the Notes section");

  const onStep3 = noteBodyHTML(n, TABLE, esc, { selfStepId: 30 });
  assert.equal((onStep3.match(/note-stepref/g) || []).length, 1);
  assert.match(onStep3, /step 5<\/a>/, "the OTHER step stays a link");
  assert.match(onStep3, /step 3/, "and the self-reference keeps its words");
  assert.doesNotMatch(onStep3, /data-note-step="3"/, "step 3 must not be a link in step 3's popover");

  const onStep5 = noteBodyHTML(n, TABLE, esc, { selfStepId: 50 });
  assert.match(onStep5, /step 3<\/a>/);
  assert.doesNotMatch(onStep5, /data-note-step="5"/);
});

test("a note attached to a step but naming no step is unaffected by the rule", () => {
  const n = note({ text: "Use warm water", step_id: 30, refs: [] });
  assert.equal(noteBodyHTML(n, TABLE, esc, { selfStepId: 30 }),
               noteBodyHTML(n, TABLE, esc, {}));
});

test("a reference the server could not resolve stays plain text, as it always did", () => {
  const n = note({ text: "see step 40",
                   refs: [{ ref_index: 0, match_text: "step 40", step_id: null, step_no: null }] });
  const html = noteBodyHTML(n, TABLE, esc, {});
  assert.doesNotMatch(html, /note-stepref/);
  assert.match(html, /see step 40/);
});

// --- which instance becomes an editor -------------------------------------------------------------

test("only the instance that was clicked becomes an editor", () => {
  // ⚠️ MEASURED ON THE BAGEL BEFORE THIS WAS SCOPED: one click opened three textareas, in the Notes
  //    section and in two popovers, and whichever blurred last decided what was saved.
  const n = note({ text: "hello", step_id: 30 });
  const section = noteRowHTML(n, TABLE, esc, { editable: true, place: "section",
                                               editing: true, draft: "hello" });
  const pop = noteRowHTML(n, TABLE, esc, { editable: true, place: "pop:30",
                                           editing: false, selfStepId: 30 });
  assert.match(section, /note-editing/);
  assert.match(section, /data-note-place="section"/);
  assert.match(section, /data-note-input="7"/);
  assert.doesNotMatch(pop, /note-editing/, "the popover copy stays reading");
  assert.doesNotMatch(pop, /data-note-input/);
  assert.match(pop, /data-note-place="pop:30"/);
});

test("a stranger gets no editing affordances at all", () => {
  const n = note({ text: "hello" });
  const theirs = noteRowHTML(n, TABLE, esc, { editable: false, place: "section" });
  for (const probe of [/data-note-edit/, /data-note-del/, /<button[^>]*note-tag"/]) {
    assert.doesNotMatch(theirs, probe);
  }
  assert.match(theirs, /hello/, "but the words are still there to read");
  assert.doesNotMatch(theirs, /note-mine/);
});

test("an owner's row carries Edit and Delete with real labels", () => {
  const html = noteRowHTML(note({ text: "hello" }), TABLE, esc,
                           { editable: true, place: "section" });
  assert.match(html, /data-note-edit="7"[^>]*aria-label="Edit this note"/);
  assert.match(html, /data-note-del="7"[^>]*aria-label="Delete this note"/);
  assert.match(html, /note-mine/);
});

// --- the editing box ------------------------------------------------------------------------------

test("the editor is a textarea, because Shift and Enter has to make a line", () => {
  const html = noteInputHTML(7, "a note", esc);
  assert.match(html, /<textarea/);
  assert.match(html, /Enter saves/);
  assert.match(html, /aria-label="[^"]*Escape cancels"/);
});

test("the editing box shows the draft, not the stored text", () => {
  const html = noteRowHTML(note({ text: "stored" }), TABLE, esc,
                           { editable: true, place: "section", editing: true, draft: "typed" });
  assert.match(html, />typed</);
  assert.doesNotMatch(html, />stored</);
});

test("the new-note box is keyed on its step, so it cannot collide with an open editor", () => {
  const html = newNoteBoxHTML(30, esc);
  assert.match(html, /data-new-note="30"/);
  assert.match(html, /data-new-note-input="30"/);
  assert.match(html, /note-tag-flat">Note</, "a new note is a Note until it is told otherwise");
});

test("the step adder names the step it belongs to and says what it does", () => {
  const html = addNoteButtonHTML(42, esc);
  assert.match(html, /data-add-note="42"/);
  assert.match(html, /aria-label="Add a note to this step"/);
});

// --- the link chips -------------------------------------------------------------------------------

test("a chip shows the arrow only where the number has MOVED", () => {
  const same = refChipsHTML(note({
    refs: [{ ref_index: 0, match_text: "step 1", step_id: 10, step_no: 1 }] }), esc);
  assert.match(same, /step 1<span/, "step 1 reaching step 1 says it once");
  assert.doesNotMatch(same, /&rarr;/);

  const moved = refChipsHTML(note({
    refs: [{ ref_index: 0, match_text: "step 9", step_id: 88, step_no: 8 }] }), esc);
  assert.match(moved, /step 9 &rarr; step 8/, "the bagel's case, and the reason an id is stored");
});

test("an unresolved reference gets no chip, because there is no link to remove", () => {
  assert.equal(refChipsHTML(note({
    refs: [{ ref_index: 0, match_text: "step 40", step_id: null, step_no: null }] }), esc), "");
});

test("a chip carries the note and the mention it would unlink", () => {
  const html = refChipsHTML(note({
    refs: [{ ref_index: 2, match_text: "step 4", step_id: 40, step_no: 4 }] }), esc);
  assert.match(html, /data-note-unlink="7"/);
  assert.match(html, /data-ref-index="2"/);
});

// --- what a save sends ----------------------------------------------------------------------------

test("the patch body carries only what was named", () => {
  assert.deepEqual(notePatchBody({ text: "x" }), { text: "x" });
  assert.deepEqual(notePatchBody({ kind: "tips" }), { kind: "tips" });
  assert.deepEqual(notePatchBody({ position: 2 }), { position: 2 });
  assert.deepEqual(notePatchBody({ step_id: null }), { step_id: null },
                   "unlinking has to be sendable, so an explicit null survives");
  assert.deepEqual(notePatchBody({ step_id: "30" }), { step_id: 30 });
  assert.deepEqual(notePatchBody({}), {});
});

test("an unchanged save sends nothing, because click-away fires on every blur", () => {
  const n = note({ text: "  hello  " });
  assert.equal(noteTextChanged(n, "hello"), false, "trimming is not a change");
  assert.equal(noteTextChanged(n, "hello there"), true);
  assert.equal(noteTextChanged(n, ""), true, "emptying it IS a change the caller must decide about");
});

// --- the toasts -----------------------------------------------------------------------------------

test("the undo offer is announced without stealing focus, and carries its token", () => {
  const html = undoToastHTML("Deleted", "d7", esc);
  assert.match(html, /role="status"/);
  assert.match(html, /data-note-toast="d7"/);
  assert.match(html, /data-note-undo="d7"/);
  assert.match(html, /Deleted/);
});

// --- escaping -------------------------------------------------------------------------------------

test("a note full of markup is escaped everywhere it is drawn", () => {
  const n = note({ text: '<script>alert(1)</script> & "quotes"' });
  for (const html of [noteRowHTML(n, TABLE, esc, { editable: true, place: "section" }),
                      noteRowHTML(n, TABLE, esc, { editable: true, place: "section",
                                                   editing: true, draft: n.text }),
                      noteBodyHTML(n, TABLE, esc, {})]) {
    assert.doesNotMatch(html, /<script>/, "a note's words are never markup");
    assert.match(html, /&lt;script&gt;/);
  }
});

test("a place name full of quotes cannot break out of the attribute", () => {
  const html = noteRowHTML(note({ text: "x" }), TABLE, esc,
                           { editable: true, place: 'a" onclick="evil()' });
  assert.doesNotMatch(html, /onclick="evil/);
  assert.match(html, /&quot;/);
});
