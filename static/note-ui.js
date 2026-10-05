"use strict";
// The note component's PURE half: what one note looks like reading, what it looks like editing, what
// its type tag says, and what a save sends. No DOM, no `view`, no fetch — app.js does all three.
//
// ⚠️ ONE COMPONENT, BOTH VIEWS, AND THAT IS THE WHOLE POINT OF THIS FILE. Notes used to be edited in
// a block under the method in Edit mode (ieNotesHTML) and read-only everywhere else, so there were
// two renderings of one note and only one of them could be edited. A second editor is a second
// opinion about what a note is. These functions are called from the reading page, from the step
// popover and from Edit mode's Notes block, so there is nothing left to disagree.
//
// ⚠️ NOTES LEFT THE EDIT-MODE DRAFT ENTIRELY, which is what makes that safe. A note writes through
// its own endpoint the moment the cook finishes typing it, in BOTH views, so Edit mode's Cancel does
// not revert a note and does not need to: a note is a playground and takes no part in the tracked
// edit that Save and Cancel exist for. draftPayload no longer sends `notes` at all, and write_notes
// reads an absent key as "leave them alone".
//
// `esc` is INJECTED, exactly as note-blocks.js takes the kind table and note-text.js takes esc: this
// module stays dependency-free for the zero-dep JS suite, and the app keeps ONE escaping function.
import { noteTextHTML, noteTextPlain } from "./note-text.js";
import { displayText, displayParts } from "./note-blocks.js";

// ⚠️ THE TAG LABEL IS DERIVED FROM THE KIND TABLE, NOT LISTED A SECOND TIME. A kind's `header` is
// the plural a section is titled with ("Notes", "Tips") and the tag wants the singular the cook
// picks ("Note", "Tip"). labels[0] is each kind's own canonical singular in static/note-kinds.json,
// so capitalizing it answers the question without a parallel list that could drift from the table
// import_cleanup reads. tests/js/note-ui.test.js pins the five answers.
export function tagLabel(kind) {
  const first = (kind && kind.labels && kind.labels[0]) || kind.kind || "";
  return first.charAt(0).toUpperCase() + first.slice(1);
}

export function kindOf(table, kind) {
  return (table || []).find((k) => k.kind === kind) || (table || [])[0];
}

export function kindMenuHTML(note, table, esc) {
  const items = (table || []).map((k) => {
    const on = k.kind === note.kind;
    return `<button type="button" role="menuitemradio" aria-checked="${on}"` +
      ` class="note-kind-item${on ? " on" : ""}" data-note-set-kind="${note.id}"` +
      ` data-kind="${esc(k.kind)}">${esc(tagLabel(k))}</button>`;
  }).join("");
  return `<div class="note-kind-menu" role="menu" aria-label="Note type">${items}</div>`;
}

// ⚠️ THE SELF-REFERENCE RULE. A note in step 8's popover that says "see step 8" is pointing at the
// step the reader is already on, so the words stay words. Everywhere else the same mention is a
// link. Implemented by hiding the step NUMBER from noteTextHTML for that one reference, which is the
// mechanism a reference whose step became a heading already uses: no number, no link, text
// unchanged.
export function noteBodyHTML(note, table, esc, { selfStepId = null } = {}) {
  const d = displayParts(note, table);
  const shown = { ...note, display: note.display != null ? note.display : d.text,
                  displayStripped: note.displayStripped != null ? note.displayStripped : d.stripped };
  if (selfStepId != null && (note.refs || []).some((r) => r.step_id === selfStepId)) {
    shown.refs = (note.refs || []).map((r) =>
      (r.step_id === selfStepId ? { ...r, step_no: null } : r));
  }
  return noteTextHTML(shown, esc);
}

// One note, READING. The look is live's: the words, and where the note is linked to a step, live's
// own "(step N)" at the end of its own text. Nothing else, because the type is on the group heading
// and the controls belong to the editor.
// ⚠️ THE ONLY THING THE OWNER SEES AT REST IS A PENCIL, AND IT RESERVES ITS SPACE. It sits in the
// markup always at opacity 0 and fades in on hover or keyboard focus, which is the rule the ⋯
// clusters already follow: a control revealed by being INSERTED moves the text as the pointer
// crosses it.
// ⚠️ THE TEXT IS NOT GIVEN A role, AND THAT IS DELIBERATE. Clicking it starts editing, which is a
// mouse affordance, and it holds step links so calling it a button would be a lie to a screen
// reader. The keyboard route is the labelled pencil beside it, which is in the tab order.
// ⚠️ A NOTE APPEARS IN MORE THAN ONE PLACE AT ONCE, AND ONLY ONE OF THEM MAY BE AN EDITOR. A note
// linked to a step is drawn in the Notes section AND in that step's popover, and in Edit mode in its
// own block. Scoping "editing" to the note id alone opened a live textarea in every one of them:
// measured on the bagel, one click produced three editors and three identical link chips, and
// whichever one lost focus last decided what was saved. `place` is the instance, so the click that
// opened an editor is the only place that gets one.
export function noteRowHTML(note, table, esc, opts = {}) {
  const { editable = false, selfStepId = null, editing = false, draft = null,
          saved = false, place = "", where = "section", steps = null,
          kindMenu = false, stepMenu = false, lead = null } = opts;
  if (editing) return noteEditHTML(note, table, esc, { draft, place, steps, kindMenu, stepMenu });
  const body = noteBodyHTML(note, table, esc, { selfStepId });
  // ⚠️ THE SAME SHAPE A WAIT'S LINK HAS, for the same reason: one pattern for "this belongs to step
  //    N" means a cook learns it once. It appears only where the server resolved a number, so a note
  //    attached to a heading reads without it rather than with a wrong one. NOT inside the step's
  //    own popover, where it would point at the step the reader is already standing on — the same
  //    reasoning as the self-reference rule above.
  const link = (where !== "pop" && !lead && note.step_no)
    ? ` <a class="meta-step note-step" href="#" data-note-step="${note.step_no}">(step ${note.step_no})</a>`
    : "";
  // ⚠️ THE GROUP SAYS WHERE, THE LEAD SAYS WHICH, AND THE TRAILING LINK GOES. A note under STEP
  //    NOTES opens with the step it belongs to and its type, so repeating "(step N)" at the end
  //    would print the same pointer twice in one sentence. The number is the step's CURRENT one and
  //    it is a link, the same promise the reference inside a note's words already makes.
  const leadHTML = lead
    ? `<span class="note-lead">` +
      `<a class="meta-step note-lead-step" href="#" data-note-step="${lead.no}">Step ${lead.no}</a>` +
      ` &middot; ${esc(lead.type)} &mdash; </span>`
    : "";
  const pencil = editable
    ? `<button type="button" class="note-pencil" data-note-edit="${note.id}" aria-label="Edit this note">&#9998;</button>`
    : "";
  const toast = saved ? savedToastHTML(note.id) : "";
  // ⚠️ NO NEWLINES INSIDE THE PARAGRAPH. .notes-para is white-space: pre-wrap, so an indent in this
  //    template renders as visible dead space before the pencil.
  if (where === "pop") {
    // ⚠️ EACH NOTE IN A POPOVER CARRIES ITS OWN TYPE LABEL. A popover has no group heading to carry
    //    it, and two notes on one step are two different kinds of thing as often as not.
    const type = `<span class="note-type">${esc(tagLabel(kindOf(table, note.kind)))}</span>`;
    return `<span class="step-note-line" data-note="${note.id}" data-note-place="${esc(place)}">` +
      `${type}<span class="note-words"${editable ? ` data-note-edit="${note.id}"` : ""}>${body}</span>${pencil}${toast}</span>`;
  }
  return `<p class="notes-para" data-note="${note.id}" data-note-place="${esc(place)}">` +
    `${leadHTML}<span class="note-words"${editable ? ` data-note-edit="${note.id}"` : ""}>${body}</span>${link}${pencil}${toast}</p>`;
}

// One note, EDITING: the note lifts onto a small panel and its controls sit in the panel's footer.
// ⚠️ THE CONTROLS EXIST ONLY HERE. The type, the step link and the delete are questions you ask
// about a note you are changing, so the reading page carries none of them and reads exactly as live.
// ⚠️ THE FOOTER'S RULE BELONGS TO THE PANEL, NOT TO THE LIST. A line between notes would make the
// Notes section read as a form, which is the thing this design exists to avoid.
export function noteEditHTML(note, table, esc, { draft = null, place = "", steps = null,
                                                 kindMenu = false, stepMenu = false } = {}) {
  const kind = kindOf(table, note.kind);
  const link = note.step_no
    ? `<button type="button" class="note-tool" data-note-unlink-step="${note.id}"` +
      ` aria-label="Linked to step ${note.step_no}. Remove the link">` +
      `&middot; step ${note.step_no}<span class="note-x" aria-hidden="true">&times;</span></button>`
    : `<button type="button" class="note-tool note-tool-off" data-note-link-menu="${note.id}"` +
      ` aria-haspopup="true" aria-expanded="${stepMenu}" aria-label="Link this note to a step">` +
      `link a step<span class="note-caret" aria-hidden="true">&#9662;</span></button>`;
  return `<div class="note-edit" data-note="${note.id}" data-note-place="${esc(place)}">` +
    noteInputHTML(note.id, draft != null ? draft : noteEditText(note, table), esc) +
    `<div class="note-foot">` +
      `<button type="button" class="note-tool" data-note-kind="${note.id}"` +
      ` aria-haspopup="true" aria-expanded="${kindMenu}"` +
      ` aria-label="${esc(`Type: ${tagLabel(kind)}. Change this note's type`)}">` +
      `${esc(tagLabel(kind))}<span class="note-caret" aria-hidden="true">&#9662;</span></button>` +
      link +
      `<button type="button" class="note-tool note-tool-del" data-note-del="${note.id}"` +
      ` aria-label="Delete this note">Delete</button>` +
      `<span class="note-hint" aria-hidden="true">Enter saves &middot; Esc cancels</span>` +
    `</div>` +
    (kindMenu ? kindMenuHTML(note, table, esc) : "") +
    (stepMenu && steps ? stepMenuHTML(note, steps, esc) : "") +
    `</div>`;
}

// The step picker, open only while "link a step" is. Headings are not offered: a note attached to a
// heading resolves no number and would print without a link, which is a pointer the page cannot show.
export function stepMenuHTML(note, steps, esc) {
  const items = (steps || []).filter((s) => !s.is_heading).map((s, i) =>
    `<button type="button" role="menuitem" class="note-kind-item" data-note-link-step="${note.id}"` +
    ` data-step-id="${s.id}">step ${i + 1}` +
    `<span class="note-menu-words"> &mdash; ${esc(String(s.text || "").slice(0, 40))}&hellip;</span>` +
    `</button>`).join("");
  return `<div class="note-kind-menu note-step-menu" role="menu" aria-label="Link a step">${items}</div>`;
}

// ⚠️ A TEXTAREA, NOT AN INPUT, BECAUSE Shift+Enter HAS TO MAKE A LINE. Enter saves and Shift+Enter
// breaks the line, which is only possible in a control that can hold one.
export function noteInputHTML(id, text, esc) {
  return `<textarea class="note-input" data-note-input="${id}" rows="2"` +
    ` aria-label="Note text. Enter saves, Shift and Enter makes a new line, Escape cancels"` +
    ` placeholder="A note…">${esc(text || "")}</textarea>`;
}

// The box that opens for "+ note". `where` is a STEP's id, or "general" for the Notes section's own
// adder, so the draft cannot collide with an open note editor.
export function newNoteBoxHTML(where, esc, { text = "" } = {}) {
  const onStep = String(where) !== "general";
  return `<div class="note-edit note-new" data-new-note="${esc(String(where))}">` +
    `<textarea class="note-input" data-new-note-input="${esc(String(where))}" rows="2"` +
    ` aria-label="A new note. Enter saves, Shift and Enter makes a new line, Escape cancels"` +
    ` placeholder="${onStep ? "A note on this step…" : "A note…"}">${esc(text || "")}</textarea>` +
    `<div class="note-foot"><span class="note-hint" aria-hidden="true">` +
    `Enter saves &middot; Esc cancels</span></div></div>`;
}

// ⚠️ IT HANGS OFF A ZERO-WIDTH ANCHOR, AND THAT IS NOT A DETAIL. An inline button at the end of a
// step takes WIDTH even at opacity 0, and a step whose last line nearly fills the measure then wraps
// one word onto a new line. Measured against the live commit on the same database: apple-pie's
// method grew 24px — one line — on a recipe with no notes at all, which is a visible change to a
// page this round promised not to touch. The anchor is zero-width inline, so the flow is live's
// flow exactly, and the button is positioned out of it.
export function addNoteButtonHTML(stepId, esc, label = "+ note") {
  return `<span class="step-add-slot"><button type="button" class="step-add-note"` +
    ` data-add-note="${stepId}" aria-label="Add a note to this step">${esc(label)}</button></span>`;
}

// ⚠️ THE SAVE OFFERS AN UNDO TOO, NOT JUST THE DELETE. A save that silently replaced the words with
// no way back is the one edit a playground should not have.
export function savedToastHTML(id) {
  return `<span class="note-toast" role="status">Saved &middot; ` +
    `<button type="button" class="note-undo" data-note-undo="s${id}">Undo</button></span>`;
}

// ⚠️ THE UNDO IS PART OF THE MESSAGE, NOT A SEPARATE CONTROL SOMEWHERE ELSE. role="status" so a
// screen reader hears it without the focus moving, and the button is reachable straight after.
export function undoToastHTML(what, token, esc) {
  return `<div class="note-toast note-toast-undo" role="status" data-note-toast="${esc(token)}">` +
    `${esc(what)} &middot; <button type="button" class="note-undo" data-note-undo="${esc(token)}">Undo` +
    `</button></div>`;
}

// ⚠️ THE EDITOR IS SEEDED WITH WHAT THE PAGE SHOWS, NOT WITH WHAT THE ROW HOLDS. A cook reading
// "Increase water to ~354 grams… proceed with step 8." used to open a box saying "SAME DAY VERSION:
// increase water… proceed with step 9.", which is a different sentence about a different step. One
// rule (displayParts) decides the label, one walk (noteTextParts) decides the numbers, and this is
// the single place that turns them into the field's value.
export function noteEditText(note, table) {
  const d = displayParts(note, table);
  return noteTextPlain({ ...note, display: d.text, displayStripped: d.stripped });
}

// What a save sends. One place, so the reading view and Edit mode cannot send different shapes.
export function notePatchBody(fields) {
  const out = {};
  if (fields.text != null) out.text = String(fields.text);
  if (fields.kind != null) out.kind = String(fields.kind);
  if ("step_id" in fields) out.step_id = fields.step_id == null ? null : +fields.step_id;
  if (fields.position != null) out.position = +fields.position;
  return out;
}

// ⚠️ AN UNCHANGED SAVE SENDS NOTHING. Click-away fires on every blur, including the ones where the
// cook changed their mind and retyped the same words, and a PATCH per blur would be a write per
// glance. The server answers "nothing to change" with a 400, so deciding here keeps that out of the
// log and off the wire.
// ⚠️ AND IT COMPARES AGAINST WHAT THE FIELD WAS SEEDED WITH, NOT AGAINST THE STORED ROW. Now that
// the editor shows the display text, comparing with the stored text would call every open-and-close
// a change and rewrite the row on a glance: the label would be dropped and the step number frozen
// on 177 notes, one at a time, without the cook typing anything. Opening and closing has to leave
// the row byte-identical, which is what tests/test_note_api.py and the JS suite both state.
export function noteTextChanged(note, draft, table) {
  const was = table ? noteEditText(note, table) : String(note.text || "");
  return String(draft == null ? "" : draft).trim() !== was.trim();
}
