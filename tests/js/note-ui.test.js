"use strict";
// The note component's pure half. One component renders in three places (the Notes section, a step
// popover, Edit mode's block), so the questions here are about what each place gets: who may edit,
// which instance becomes an editor, what the type tag says, and when a "step N" is a link.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { tagLabel, kindOf, kindMenuHTML, noteBodyHTML, noteRowHTML, noteEditHTML, noteInputHTML,
         stepMenuHTML, newNoteBoxHTML, addNoteButtonHTML, notePatchBody, noteTextChanged,
         savedToastHTML, undoToastHTML } from "../../static/note-ui.js";

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

test("reading, a note carries NO type control — the group heading says what it is", () => {
  // ⚠️ THE ROUND 1 DESIGN PUT A "Tip ▾" ON EVERY NOTE AT REST AND ANDY TURNED IT DOWN. The Notes
  //    section already prints a heading per kind, so a tag on each note says the same thing twice
  //    and turns a read into a form. The type is a control only while the note is being edited.
  const mine = noteRowHTML(note({ kind: "tips", text: "hello" }), TABLE, esc,
                           { editable: true, place: "section", where: "section" });
  for (const probe of [/data-note-kind/, /note-tag/, /aria-haspopup/, /data-note-del/]) {
    assert.doesNotMatch(mine, probe, "no control on a note at rest but the pencil");
  }
  assert.match(mine, /<p class="notes-para"/, "live's own paragraph, unchanged");
});

test("a note in a POPOVER carries its type, because a popover has no heading to carry it", () => {
  const html = noteRowHTML(note({ kind: "tips", text: "hello" }), TABLE, esc,
                           { editable: true, place: "pop:30", where: "pop", selfStepId: 30 });
  assert.match(html, /<span class="note-type">Tip<\/span>/);
  assert.match(html, /step-note-line/);
});

test("the step link is live's \"(step N)\", and never inside the step's own popover", () => {
  const n = note({ text: "hello", step_id: 30, step_no: 3 });
  const section = noteRowHTML(n, TABLE, esc, { place: "section", where: "section" });
  const pop = noteRowHTML(n, TABLE, esc, { place: "pop:30", where: "pop", selfStepId: 30 });
  assert.match(section, /<a class="meta-step note-step" href="#" data-note-step="3">\(step 3\)<\/a>/);
  // ⚠️ THE POPOVER IS ALREADY ON THAT STEP. A link to where the reader is standing is noise, which
  //    is the same reasoning the self-reference rule above rests on.
  assert.doesNotMatch(pop, /\(step 3\)/);
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
  assert.match(section, /note-edit/);
  assert.match(section, /data-note-place="section"/);
  assert.match(section, /data-note-input="7"/);
  assert.doesNotMatch(pop, /data-note-place="section"/, "the popover copy stays reading");
  assert.doesNotMatch(pop, /data-note-input/);
  assert.match(pop, /data-note-place="pop:30"/);
});

test("a stranger gets no editing affordances at all", () => {
  const n = note({ text: "hello" });
  const theirs = noteRowHTML(n, TABLE, esc, { editable: false, place: "section" });
  for (const probe of [/data-note-edit/, /data-note-del/, /note-pencil/]) {
    assert.doesNotMatch(theirs, probe);
  }
  assert.match(theirs, /hello/, "but the words are still there to read");
});

test("an owner's only mark at rest is a labelled pencil", () => {
  const html = noteRowHTML(note({ text: "hello" }), TABLE, esc,
                           { editable: true, place: "section", where: "section" });
  assert.match(html, /class="note-pencil" data-note-edit="7" aria-label="Edit this note"/);
  // the words themselves are the mouse target; the pencil is the keyboard one
  assert.match(html, /<span class="note-words" data-note-edit="7">/);
});

// --- the editing box ------------------------------------------------------------------------------

test("the editor is a textarea, because Shift and Enter has to make a line", () => {
  const html = noteInputHTML(7, "a note", esc);
  assert.match(html, /<textarea/);
  assert.match(html, /aria-label="[^"]*Escape cancels"/);
  // the key hint lives in the footer now, beside the controls it belongs with
  assert.match(noteEditHTML(note({ text: "a note" }), TABLE, esc, {}), /Enter saves &middot; Esc cancels/);
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
  assert.doesNotMatch(html, /note-tag/, "a new note has no type control either — Note until told otherwise");
});

test("the step adder names the step it belongs to and says what it does", () => {
  const html = addNoteButtonHTML(42, esc);
  assert.match(html, /data-add-note="42"/);
  assert.match(html, /aria-label="Add a note to this step"/);
});

// --- the editor's footer -------------------------------------------------------------------------

test("the footer carries the type, the step link and the delete, and nothing else", () => {
  const html = noteEditHTML(note({ kind: "tips", text: "x", step_id: 30, step_no: 3 }), TABLE, esc,
                            { place: "section" });
  assert.match(html, /data-note-kind="7"[^>]*>Tip/);
  assert.match(html, /data-note-unlink-step="7"/);
  assert.match(html, /&middot; step 3/, "the link control names the step it would remove");
  assert.match(html, /data-note-del="7"[^>]*aria-label="Delete this note"/);
  assert.equal((html.match(/class="note-tool/g) || []).length, 3, "three controls, no more");
});

test("a note linked to nothing offers the picker instead of an unlink", () => {
  const html = noteEditHTML(note({ text: "x" }), TABLE, esc, { place: "section" });
  assert.match(html, /data-note-link-menu="7"/);
  assert.match(html, />link a step/);
  assert.doesNotMatch(html, /data-note-unlink-step/);
});

test("the two menus are drawn WITH the editor, so closing it closes them", () => {
  // ⚠️ THE ROUND 1 MENU WAS INSERTED NEXT TO ITS BUTTON BY JS, which a repaint could leave behind.
  const shut = noteEditHTML(note({ text: "x" }), TABLE, esc, { place: "section" });
  assert.doesNotMatch(shut, /note-kind-menu/);
  const open = noteEditHTML(note({ text: "x" }), TABLE, esc, { place: "section", kindMenu: true });
  assert.match(open, /note-kind-menu/);
  assert.match(open, /aria-expanded="true"/);
});

test("the step picker offers steps and never a heading", () => {
  // ⚠️ A NOTE ON A HEADING RESOLVES NO NUMBER, so the page would print it without a link. Offering
  //    one would be offering a pointer the reader can never see.
  const steps = [{ id: 1, text: "chop", is_heading: false },
                 { id: 2, text: "To cook:", is_heading: true },
                 { id: 3, text: "fry", is_heading: false }];
  const html = stepMenuHTML(note({}), steps, esc);
  assert.equal((html.match(/role="menuitem"/g) || []).length, 2);
  assert.match(html, /data-step-id="1"[^>]*>step 1/);
  assert.match(html, /data-step-id="3"[^>]*>step 2/, "the numbers skip the heading, as the page does");
});

test("a save offers an undo too, not just a delete", () => {
  // ⚠️ A SAVE THAT SILENTLY REPLACED THE WORDS with no way back is the one edit a playground should
  //    not have. The token tells the handler which kind of undo it is.
  const html = savedToastHTML(7);
  assert.match(html, /Saved &middot; /);
  assert.match(html, /data-note-undo="s7"/);
  assert.match(html, /role="status"/);
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
