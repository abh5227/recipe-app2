"use strict";
// The note component's pure half. One component renders in three places (the Notes section, a step
// popover, Edit mode's block), so the questions here are about what each place gets: who may edit,
// which instance becomes an editor, what the type tag says, and when a "step N" is a link.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { displayParts } from "../../static/note-blocks.js";
import { tagLabel, kindOf, kindMenuHTML, noteBodyHTML, noteRowHTML, noteEditHTML, noteInputHTML,
         noteTitleInputHTML, noteTitleChanged,
         stepMenuHTML, newNoteBoxHTML, addNoteButtonHTML, notePatchBody, noteTextChanged,
         noteEditText, savedToastHTML, undoToastHTML, pickBarHTML,
         noteStepChanged } from "../../static/note-ui.js";
import { pickerRows } from "../../static/step-picker.js";
import { noteTextPlain, noteTextParts } from "../../static/note-text.js";

const TABLE = JSON.parse(fs.readFileSync(
  path.join(import.meta.dirname, "../../static/note-kinds.json"), "utf8")).kinds;

// The app's own escaper, copied in the shape the other pure modules take it: injected, not imported.
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// ⚠️ THE REAL CALLER PASSES A DECORATED ROW. app.js::noteOne feeds rows from noteSections, which
//    runs note-blocks.js::decorate and sets `display` and `displayStripped`; noteBodyHTML branches
//    on `display != null`, so a fixture without them took the OTHER branch and every test here
//    exercised a shape the browser never produces. `decorated()` below is the browser's shape, and
//    the bare `note()` stays for the handful of cases that are about the undecorated path.
const note = (o) => ({ id: 7, kind: "notes", text: "", step_id: null, step_no: null, refs: [], ...o });
const decorated = (o) => {
  const row = note(o);
  const d = displayParts(row, TABLE);
  return { ...row, display: d.text, displayStripped: d.stripped };
};

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
  // ⚠️ THREE CONTROLS UNLINKED, FOUR LINKED, and the fourth is the × that takes the link off. The
  //    step itself reopens the picker, which is a different job, so it is a different button. Any
  //    fifth thing here is a control that crept back onto a note at rest.
  const linked = noteEditHTML(note({ kind: "tips", text: "x", step_id: 30, step_no: 3 }), TABLE, esc,
                              { place: "section" });
  assert.match(linked, /data-note-kind="7"[^>]*>Tip/);
  assert.match(linked, /data-note-unlink-step="7"/);
  assert.match(linked, /&middot; step 3/, "the link control names the step it points at");
  assert.match(linked, /data-note-del="7"[^>]*aria-label="Delete this note"/);
  assert.equal((linked.match(/class="note-tool/g) || []).length, 4);

  const loose = noteEditHTML(note({ kind: "tips", text: "x" }), TABLE, esc, { place: "section" });
  assert.equal((loose.match(/class="note-tool/g) || []).length, 3);
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

const STEPS = [{ id: 1, text: "chop the onion finely", is_heading: false },
               { id: 2, text: "To cook:", is_heading: true },
               { id: 3, text: "fry until golden", is_heading: false }];
const pickOf = (o = {}) => ({ rows: pickerRows(STEPS), query: "", cursor: null, ...o });

test("the step picker offers steps and never a heading", () => {
  // ⚠️ A NOTE ON A HEADING RESOLVES NO NUMBER, so the page would print it without a link. Offering
  //    one would be offering a pointer the reader can never see. The heading is still PRINTED, as
  //    the grouping, which is why it is a div and not a button.
  const html = stepMenuHTML(note({}), pickOf(), esc);
  assert.equal((html.match(/role="option"/g) || []).length, 2);
  assert.match(html, /data-step-id="1"/);
  assert.match(html, /data-step-id="3"/);
  assert.doesNotMatch(html, /data-step-id="2"/, "the heading is not selectable");
  assert.match(html, /<div class="pk-sect" role="presentation">To cook:<\/div>/,
    "and it is printed, because the recipe's own sections are the grouping");
});

test("the numbers skip the heading, exactly as the page does", () => {
  const html = stepMenuHTML(note({}), pickOf(), esc);
  assert.match(html, /data-step-id="1"[^]*?>step 1</);
  assert.match(html, /data-step-id="3"[^]*?>step 2</);
});

test("the current link is marked, and the cursor separately", () => {
  const html = stepMenuHTML(note({ step_id: 3 }), pickOf({ cursor: 1 }), esc);
  assert.match(html, /class="pk-row on"[^>]*data-step-id="3"/, "the link it already has");
  assert.match(html, /class="pk-row at"[^>]*data-step-id="1"/, "where the arrows are");
  assert.match(html, /aria-activedescendant="pk-7-1"/, "and a screen reader is told which");
});

test("the filter box round-trips what was typed, escaped", () => {
  const html = stepMenuHTML(note({}), pickOf({ query: '"x" & <y>' }), esc);
  assert.match(html, /value="&quot;x&quot; &amp; &lt;y&gt;"/);
});

test("an empty result says so rather than showing an empty box", () => {
  const html = stepMenuHTML(note({}), pickOf({ rows: [], query: "zzz" }), esc);
  assert.match(html, /class="pk-none"/);
  assert.match(html, /zzz/);
});

test("the way out of the list is at the foot of it", () => {
  assert.match(stepMenuHTML(note({}), pickOf(), esc),
    /class="pk-onpage" data-note-pick-page="7">Pick on the page/);
});

test("the pick bar says the gesture the device actually has", () => {
  assert.match(pickBarHTML(7, esc, { phone: true }), /Tap a step to link it/);
  assert.doesNotMatch(pickBarHTML(7, esc, { phone: true }), /Esc/, "a phone has no Escape key");
  assert.match(pickBarHTML(7, esc, {}), /Click the step this note belongs to/);
  assert.match(pickBarHTML(7, esc, {}), /Cancel \(Esc\)/);
  assert.match(pickBarHTML(7, esc, {}), /data-note-pick-cancel="7"/);
});

test("each menu hangs off its own control, not off the panel", () => {
  // ⚠️ A 7-ROW LIST ANCHORED TO THE PANEL'S LEFT EDGE IS NOT ANCHORED TO ANYTHING THE COOK
  //    CLICKED. Both menus were siblings of the footer. They are inside it now, each in its own
  //    positioned span beside the button that opens it.
  const html = noteEditHTML(note({}), TABLE, esc, { stepMenu: true, pick: pickOf() });
  // ⚠️ THE ANCHOR OPENS BEFORE ITS BUTTON, so it is searched BACKWARDS from the button. This read
  //    forwards, found nothing, and the result was checked against -2 — a value indexOf cannot
  //    return — so the assertion was true whether the span was there or not.
  const btn = html.indexOf("data-note-link-menu");
  const menu = html.indexOf("note-step-menu");
  const anchor = html.lastIndexOf('<span class="note-anchor">', btn);
  assert.ok(btn !== -1 && menu !== -1, "the button and its menu are both drawn");
  assert.ok(anchor !== -1, "the link button sits inside an anchor span");
  assert.ok(anchor < btn && btn < menu, "and the menu is inside that same span, after its button");
  assert.ok(menu < html.indexOf("note-tool-del"),
    "which puts it where its own button sits, before Delete");
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


// --- the editor shows what you read ---------------------------------------------------------------

const BAGEL = note({
  id: 158, kind: "variations",
  text: "SAME DAY VERSION: increase water to ~354 grams and then proceed with step 9.",
  refs: [{ ref_index: 0, match_text: "step 9", step_id: 3788, step_no: 8 }],
});

test("the editor is seeded with the words the page shows, not the row", () => {
  // ⚠️ THE CASE THAT STARTED THIS. The bagel's note reads "Increase water… proceed with step 8" and
  //    used to open a box saying "SAME DAY VERSION: increase water… proceed with step 9", which is
  //    a different sentence about a different step.
  assert.equal(noteEditText(BAGEL, TABLE),
               "Increase water to ~354 grams and then proceed with step 8.");
});

test("reading and the editor agree, word for word", () => {
  const read = noteBodyHTML(BAGEL, TABLE, esc).replace(/<[^>]+>/g, "");
  assert.equal(read, noteEditText(BAGEL, TABLE));
});

test("the capital arrives only because a label left", () => {
  // The label carried the sentence's first letter, so stripping it leaves a lowercase opening.
  assert.match(noteEditText(BAGEL, TABLE), /^Increase/);
  const own = note({ text: "increase the water a little.", kind: "notes" });
  assert.equal(noteEditText(own, TABLE), "increase the water a little.",
               "an author's own lowercase opening is left alone");
});

test("a label the table does not know stays in the text", () => {
  // "Form a Pie Shell:" names something and the kind table has never heard of it, so the words are
  // the author's and the editor must not quietly delete them.
  const pie = note({ kind: "notes", text: "Form a Pie Shell: To form the pie shell, take a disk." });
  assert.equal(noteEditText(pie, TABLE), pie.text);
});

test("a label that disagrees with the row's kind stays too", () => {
  // A cook who moved a "Tip:" into Storage changed the kind and not the words.
  const moved = note({ kind: "storage", text: "Tip: freeze it flat." });
  assert.equal(noteEditText(moved, TABLE), "Tip: freeze it flat.");
});

test("opening and closing with no edit is NOT a change", () => {
  // ⚠️ THE GUARANTEE THE WHOLE ROUND RESTS ON. Comparing the draft with the STORED text would call
  //    every glance a change and rewrite 177 rows one at a time.
  assert.equal(noteTextChanged(BAGEL, noteEditText(BAGEL, TABLE), TABLE), false);
  assert.equal(noteTextChanged(BAGEL, noteEditText(BAGEL, TABLE) + " more", TABLE), true);
});

test("a reference the server could not resolve keeps the author's number", () => {
  const broken = note({ text: "see step 40 for this.",
                        refs: [{ ref_index: 0, match_text: "step 40", step_id: null, step_no: null }] });
  assert.equal(noteEditText(broken, TABLE), "see step 40 for this.");
  assert.doesNotMatch(noteBodyHTML(broken, TABLE, esc), /note-stepref/);
});

test("two references each take their own current number", () => {
  const two = note({
    text: "This matters at step 3 and again at step 9.",
    refs: [{ ref_index: 0, match_text: "step 3", step_id: 10, step_no: 3 },
           { ref_index: 1, match_text: "step 9", step_id: 20, step_no: 8 }] });
  assert.equal(noteTextPlain(two), "This matters at step 3 and again at step 8.");
});

test("the walk is one walk: the parts the link and the plain text come from", () => {
  const parts = noteTextParts(BAGEL);
  assert.deepEqual(parts.map((p) => p.t), ["text", "step", "text"]);
  assert.equal(parts[1].step_no, 8);
  assert.equal(parts[1].v, "step 9", "the author's words are still what was matched");
});

// --- the STEP NOTES lead -------------------------------------------------------------------------
// "Step 4 · Tip — " opens a note in the STEP NOTES group. The number is the step's CURRENT one and
// it is a link; the trailing "(step N)" goes, because the lead already said it.

test("the lead opens the note with a linked step number and the type", () => {
  const html = noteRowHTML(note({ step_id: 4, step_no: 2, text: "Rest it." }), TABLE, esc,
    { lead: { no: 2, type: "Tip" } });
  assert.match(html, /<span class="note-lead">/);
  assert.match(html, /data-note-step="2">Step 2<\/a>/, "the number is a link, like other step links");
  assert.match(html, /&middot; Tip: /);
  assert.doesNotMatch(html, /&mdash;/, "a colon introduces what follows, and the house style has no em dashes");
  assert.ok(html.indexOf('class="note-lead"') < html.indexOf('class="note-words"'),
    "the lead is inline before the words, never on its own line");
});

test("a led note does NOT also print the trailing (step N)", () => {
  const n = note({ step_id: 4, step_no: 2, text: "Rest it." });
  assert.match(noteRowHTML(n, TABLE, esc, {}), /\(step 2\)/, "without a lead it still does");
  assert.doesNotMatch(noteRowHTML(n, TABLE, esc, { lead: { no: 2, type: "Tip" } }), /\(step 2\)/);
});

test("the lead's type is escaped like every other injected string", () => {
  const html = noteRowHTML(note({ step_no: 1 }), TABLE, esc, { lead: { no: 1, type: '<b>"x"' } });
  assert.match(html, /&lt;b&gt;&quot;x&quot;/);
  assert.doesNotMatch(html, /<b>/);
});

test("a popover note never takes a lead, because the popover IS the step", () => {
  const html = noteRowHTML(note({ step_id: 4, step_no: 2, text: "Rest it." }), TABLE, esc,
    { where: "pop", place: "pop:4" });
  assert.doesNotMatch(html, /note-lead/);
  assert.doesNotMatch(html, /\(step 2\)/);
});

test("the picker's rows reach the editor through noteRowHTML, not only noteEditHTML", () => {
  // ⚠️ THE OPTS BAG IS FORWARDED BY NAME, so a new opt is invisible until it is named in BOTH
  //    places. `pick` was destructured by noteEditHTML and never passed to it, and the list
  //    rendered "Nothing matches" on a recipe with fifteen steps in it.
  const html = noteRowHTML(note({}), TABLE, esc,
    { editing: true, stepMenu: true, pick: pickOf() });
  assert.match(html, /class="pk-row"/);
  assert.doesNotMatch(html, /pk-none/);
});

test("picking the step a note is already on is not a change", () => {
  // ⚠️ THE PICKER OPENS WITH THE CURRENT LINK UNDER THE CURSOR, so Enter straight away is the
  //    easiest key to press. The server answers 200 for a step_id equal to the stored one, because
  //    its "nothing to change" refusal is stated over the TEXT, so the client decides this one.
  assert.equal(noteStepChanged(note({ step_id: 4 }), 4), false);
  assert.equal(noteStepChanged(note({ step_id: 4 }), "4"), false, "a dataset value is a string");
  assert.equal(noteStepChanged(note({ step_id: 4 }), 5), true);
  assert.equal(noteStepChanged(note({ step_id: 4 }), null), true, "unlinking is a change");
  assert.equal(noteStepChanged(note({ step_id: null }), null), false);
  assert.equal(noteStepChanged(note({ step_id: null }), 5), true);
});

test("a linked note can still open the list, and the × is its own control", () => {
  // ⚠️ THE WHOLE CHIP USED TO BE THE UNLINK, so changing which step a note belonged to meant
  //    removing the link first, and the list's "current link highlighted" row could never be seen.
  const html = noteEditHTML(note({ step_id: 4, step_no: 3 }), TABLE, esc, {});
  assert.match(html, /data-note-link-menu="7"[^>]*>&middot; step 3</, "the step opens the picker");
  assert.match(html, /data-note-unlink-step="7"/, "and the × is a separate button");
  assert.match(html, /aria-label="Remove the link to step 3"/);
  assert.match(html, /aria-label="Linked to step 3\. Pick a different step"/);
});

test("the pencil hangs off a zero-width anchor, so it never costs the note a line", () => {
  // ⚠️ AN INVISIBLE INLINE BUTTON STILL TAKES WIDTH. Measured in Edit mode's boxed look, where the
  //    extra line shows as empty space inside the box: all-butter-pie-crust's Storage note was 64px
  //    tall against 40px of words, and 40px with the pencil hidden.
  const html = noteRowHTML(note({ text: "x" }), TABLE, esc, { editable: true });
  assert.match(html, /<span class="note-pencil-slot"><button[^>]*class="note-pencil"/);
  assert.doesNotMatch(noteRowHTML(note({ text: "x" }), TABLE, esc, {}), /note-pencil/,
    "and a reader who does not own the recipe gets neither");
});

test("the pencil's anchor comes after the toast, so it never sits on top of Undo", () => {
  const html = noteRowHTML(note({ text: "x" }), TABLE, esc, { editable: true, saved: true });
  assert.ok(html.indexOf("note-toast") < html.indexOf("note-pencil-slot"));
});


// --- the decorated row, which is the ONLY shape the page ever renders -----------------------------
// ⚠️ noteBodyHTML BRANCHES ON `display != null`, so every test above that passes a bare note takes
//    the branch the browser never takes. These pin the branch it does take, including the capital
//    rule this round was built for.

test("a decorated row renders its display text, not its stored text", () => {
  const row = decorated({ kind: "tips", text: "Tip: rest it." });
  assert.equal(row.display, "rest it.", "the label is stripped for display");
  assert.ok(row.displayStripped);
  const html = noteBodyHTML(row, TABLE, esc);
  assert.ok(/Rest it\./.test(html), `a stripped label is capitalized at render: ${html}`);
  assert.ok(!/Tip:/.test(html), "and the label itself is not printed twice");
});

test("a label the table does not know keeps its words and its own capital", () => {
  const row = decorated({ kind: "notes", text: "Blind Bake: put the weights in." });
  assert.equal(row.displayStripped, false, "nothing was stripped, so nothing is re-capitalized");
  const html = noteBodyHTML(row, TABLE, esc);
  assert.ok(/Blind Bake/.test(html), html);
});

test("losing displayStripped would lowercase every stripped note, which is why it is pinned", () => {
  const row = decorated({ kind: "tips", text: "Tip: rest it." });
  const lost = { ...row, displayStripped: false };
  assert.ok(/Rest it\./.test(noteBodyHTML(row, TABLE, esc)));
  assert.ok(/rest it\./.test(noteBodyHTML(lost, TABLE, esc)),
    "the flag is what decides the capital, so dropping it is visible on the page");
});

test("the whole row renders from the decorated shape the way app.js passes it", () => {
  const html = noteRowHTML(decorated({ id: 9, kind: "storage", text: "Storage: keep it cold." }),
                           TABLE, esc, { editable: true, place: "ie" });
  assert.ok(/Keep it cold\./.test(html), html);
  assert.ok(/data-note="9"/.test(html));
});

// ---- a note's title -----------------------------------------------------------------------------

test("a title renders as a subheading above the note, outside the paragraph", () => {
  const html = noteRowHTML(decorated({ id: 4, kind: "notes", title: "Flour",
                                       text: "This recipe works best with 11% protein." }),
                           TABLE, esc, { editable: true, place: "ie" });
  assert.ok(/<h4 class="note-title">Flour<\/h4>/.test(html), html);
  assert.ok(html.indexOf('<h4 class="note-title">') < html.indexOf('<p class="notes-para'),
    "the heading has to come before the paragraph it heads");
  assert.ok(/This recipe works best/.test(html), html);
});

test("a titled note takes no bullet, which is a class the stylesheet reads", () => {
  // ⚠️ THE BULLET SAYS "these belong together and there are several". A note that announces itself
  //    with a heading has already said where it starts, so a bullet beside it marks the same
  //    boundary twice. The group still gets .marked, so its untitled siblings keep theirs.
  const titled = noteRowHTML(decorated({ id: 1, kind: "notes", title: "Buying", text: "Look for it." }),
                             TABLE, esc, {});
  assert.ok(/class="notes-para titled"/.test(titled), titled);
  const plain = noteRowHTML(decorated({ id: 2, kind: "notes", text: "Look for it." }), TABLE, esc, {});
  assert.ok(/class="notes-para"/.test(plain), plain);
  assert.ok(!/titled/.test(plain), plain);
});

test("under STEP NOTES the title is the heading and the lead stays on the body", () => {
  // Andy's call: "Step 4 · Tip: " is part of the sentence, inline with the first words by design,
  // so a title above it is a heading over that sentence rather than a replacement for its opening.
  const html = noteRowHTML(
    decorated({ id: 5, kind: "tips", title: "Quick soak", text: "Cover with water." }),
    TABLE, esc, { lead: { no: 4, type: "Tip" } });
  assert.ok(/<h4 class="note-title">Quick soak<\/h4>/.test(html), html);
  assert.ok(/class="note-lead"/.test(html), "the lead is still drawn");
  assert.ok(/Step 4/.test(html) && /Tip: /.test(html), html);
  assert.ok(html.indexOf("note-title") < html.indexOf("note-lead"),
    "the heading is above the sentence the lead opens");
});

test("a step popover shows the title too, so one note does not read two ways", () => {
  const html = noteRowHTML(
    decorated({ id: 6, kind: "storage", title: "To Freeze the pie shell", text: "Wrap it." }),
    TABLE, esc, { where: "pop", place: "pop:3" });
  assert.ok(/note-type/.test(html), "the popover's own type label stays, it has no group heading");
  assert.ok(/<h4 class="note-title">To Freeze the pie shell<\/h4>/.test(html), html);
  assert.ok(html.indexOf("note-type") < html.indexOf("note-title"),
    "the type names the group, the title names the note, so the type is above it");
});

test("a title is escaped like every other stored string", () => {
  const html = noteRowHTML(decorated({ id: 8, kind: "notes", title: '<b>"x"</b> & y',
                                       text: "Body." }), TABLE, esc, {});
  assert.ok(/&lt;b&gt;&quot;x&quot;&lt;\/b&gt; &amp; y/.test(html), html);
  assert.ok(!/<b>/.test(html), html);
});

test("no title means no heading element at all, not an empty one", () => {
  for (const title of [null, undefined, ""]) {
    const html = noteRowHTML(decorated({ id: 3, kind: "notes", title, text: "Body." }),
                             TABLE, esc, {});
    assert.ok(!/note-title/.test(html), `title=${JSON.stringify(title)}: ${html}`);
  }
});

// ---- the Title box ------------------------------------------------------------------------------

test("the editor draws an optional Title box above the text, in one editor for both views", () => {
  const html = noteEditHTML(note({ id: 4, title: "Flour", text: "Body." }), TABLE, esc, {});
  assert.ok(/data-note-title="4"/.test(html), html);
  assert.ok(/value="Flour"/.test(html), html);
  assert.ok(/placeholder="Title \(optional\)"/.test(html), "the box has to say it is optional");
  assert.ok(html.indexOf("data-note-title") < html.indexOf("data-note-input"),
    "the title sits above the text, the way it reads on the page");
});

test("an untitled note opens with an empty Title box, not with no box", () => {
  for (const title of [null, undefined, ""]) {
    const html = noteEditHTML(note({ id: 4, title, text: "Body." }), TABLE, esc, {});
    assert.ok(/data-note-title="4"/.test(html), `title=${JSON.stringify(title)}`);
    assert.ok(/value=""/.test(html), html);
  }
});

test("a title draft wins over the stored title while the box is open", () => {
  const html = noteEditHTML(note({ id: 4, title: "Flour", text: "Body." }), TABLE, esc,
                            { titleDraft: "Bread flour" });
  assert.ok(/value="Bread flour"/.test(html), html);
  assert.ok(!/value="Flour"/.test(html), html);
  // and an empty draft is a CLEARED box, not an absent one
  const cleared = noteEditHTML(note({ id: 4, title: "Flour", text: "Body." }), TABLE, esc,
                               { titleDraft: "" });
  assert.ok(/value=""/.test(cleared), cleared);
});

test("a title is escaped in the box, so a quote in one cannot break out of the attribute", () => {
  const html = noteEditHTML(note({ id: 4, title: '"x" & <b>', text: "Body." }), TABLE, esc, {});
  assert.ok(/value="&quot;x&quot; &amp; &lt;b&gt;"/.test(html), html);
});

test("a save carries the title only when it moved, and a cleared one is a change", () => {
  // ⚠️ notePatchBody TESTS FOR THE KEY, NOT THE VALUE, because clearing a title is a change and
  //    there is no such thing as clearing a note's text.
  assert.deepEqual(notePatchBody({ text: "x" }), { text: "x" });
  assert.deepEqual(notePatchBody({ title: "Flour" }), { title: "Flour" });
  assert.deepEqual(notePatchBody({ title: "" }), { title: "" });
  assert.deepEqual(notePatchBody({ title: null }), { title: null });
  assert.deepEqual(notePatchBody({ text: "x", title: "Flour" }), { text: "x", title: "Flour" });
});

test("opening a note and closing it is not a title change, which is what keeps bytes still", () => {
  // ⚠️ THE SAME RULE THE TEXT FOLLOWS. A write per blur would rewrite 28 rows on a glance and take
  //    every one of their recipes out of the byte-equal short-circuit set.
  const n = note({ id: 4, title: "Flour", text: "Body." });
  assert.equal(noteTitleChanged(n, "Flour"), false);
  assert.equal(noteTitleChanged(n, "  Flour  "), false, "compared trimmed, as the text is");
  assert.equal(noteTitleChanged(n, "Bread flour"), true);
  assert.equal(noteTitleChanged(n, ""), true, "clearing one IS a change");
});

test("null and empty are one resting state, because the box shows them the same way", () => {
  for (const stored of [null, undefined, ""]) {
    const n = note({ id: 4, title: stored, text: "Body." });
    assert.equal(noteTitleChanged(n, ""), false, `stored=${JSON.stringify(stored)}`);
    assert.equal(noteTitleChanged(n, "   "), false, "whitespace is empty");
    assert.equal(noteTitleChanged(n, "Flour"), true);
  }
});
