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
import { noteTextHTML } from "./note-text.js";
import { displayText } from "./note-blocks.js";

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

// The "Note ▾" tag. A real button with a real menu, because it CHANGES the note rather than
// describing it.
export function kindTagHTML(note, table, esc, { editable = true } = {}) {
  const k = kindOf(table, note.kind);
  const text = esc(tagLabel(k));
  if (!editable) return `<span class="note-tag note-tag-flat">${text}</span>`;
  return `<button type="button" class="note-tag" data-note-kind="${note.id}"` +
    ` aria-haspopup="true" aria-expanded="false"` +
    ` aria-label="${esc(`Type: ${tagLabel(k)}. Change this note's type`)}">` +
    `${text}<span class="note-tag-caret" aria-hidden="true">&#9662;</span></button>`;
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
  const shown = { ...note, display: note.display != null ? note.display : displayText(note, table) };
  if (selfStepId != null && (note.refs || []).some((r) => r.step_id === selfStepId)) {
    shown.refs = (note.refs || []).map((r) =>
      (r.step_id === selfStepId ? { ...r, step_no: null } : r));
  }
  return noteTextHTML(shown, esc);
}

// One note, reading. `editable` is the OWNER's answer and it comes from the server's is_mine.
// ⚠️ THE TEXT IS NOT GIVEN A role, AND THAT IS DELIBERATE. Clicking it starts editing, which is a
// mouse affordance, and it holds step links so calling it a button would be a lie to a screen
// reader. The keyboard route is the real "Edit this note" button beside it, which is in the tab
// order and labelled.
// ⚠️ A NOTE APPEARS IN MORE THAN ONE PLACE AT ONCE, AND ONLY ONE OF THEM MAY BE AN EDITOR. A note
// linked to a step is drawn in the Notes section AND in that step's popover, and in Edit mode in its
// own block. Scoping "editing" to the note id alone opened a live textarea in every one of them:
// measured on the bagel, one click produced three editors and three identical link chips, and
// whichever one lost focus last decided what was saved. `place` is the instance, so the click that
// opened an editor is the only place that gets one.
export function noteRowHTML(note, table, esc, opts = {}) {
  const { editable = false, selfStepId = null, editing = false, draft = null,
          showTag = true, saved = false, place = "" } = opts;
  const body = noteBodyHTML(note, table, esc, { selfStepId });
  const tag = showTag ? kindTagHTML(note, table, esc, { editable }) : "";
  if (editing) {
    // ⚠️ THE LINK CHIPS ONLY EXIST WHILE EDITING, because that is the only time "remove link" is a
    //    question. Reading, the same reference is just a link in the sentence.
    return `<div class="note-row note-editing" data-note="${note.id}"` +
      ` data-note-place="${esc(place)}">` +
      tag + noteInputHTML(note.id, draft != null ? draft : note.text, esc) +
      refChipsHTML(note, esc) +
      `</div>`;
  }
  const controls = editable
    ? `<span class="note-actions">` +
        `<button type="button" class="note-act" data-note-edit="${note.id}"` +
        ` aria-label="Edit this note">Edit</button>` +
        `<button type="button" class="note-act" data-note-del="${note.id}"` +
        ` aria-label="Delete this note">Delete</button></span>`
    : "";
  return `<div class="note-row${editable ? " note-mine" : ""}" data-note="${note.id}"` +
    ` data-note-place="${esc(place)}">` +
    tag +
    `<div class="note-text"${editable ? ` data-note-edit="${note.id}"` : ""}>${body}</div>` +
    controls + (saved ? savedToastHTML() : "") +
    `</div>`;
}

// ⚠️ A TEXTAREA, NOT AN INPUT, BECAUSE Shift+Enter HAS TO MAKE A LINE. Enter saves and Shift+Enter
// breaks the line, which is only possible in a control that can hold one.
// ⚠️ ONE CHIP PER LINKED MENTION, NAMING THE WORDS AND THE STEP IT REACHED. A mention the server
// could not resolve has no chip: there is no link to remove.
export function refChipsHTML(note, esc) {
  const linked = (note.refs || []).filter((r) => r.step_no);
  if (!linked.length) return "";
  // ⚠️ THE ARROW ONLY APPEARS WHEN THE NUMBER HAS MOVED. "step 1 → step 1" was what this printed
  //    for every chip, which is three words to say nothing. The author's own words are what the cook
  //    typed, so they lead; the resolved number follows only where it DIFFERS, which is the bagel's
  //    "step 9 → step 8" and the whole reason a reference stores an id.
  return `<span class="note-chips">` + linked.map((r) => {
    const said = Number(String(r.match_text).match(/(\d+)/)?.[1]);
    const moved = said !== r.step_no;
    const face = moved ? `${esc(r.match_text)} &rarr; step ${r.step_no}` : esc(r.match_text);
    const label = moved
      ? `${r.match_text} links to step ${r.step_no}. Remove this link`
      : `${r.match_text} is a link. Remove it`;
    return `<button type="button" class="note-chip" data-note-unlink="${note.id}"` +
      ` data-ref-index="${r.ref_index}" aria-label="${esc(label)}">` +
      `${face}<span class="note-chip-x" aria-hidden="true">×</span></button>`;
  }).join("") + `</span>`;
}

export function noteInputHTML(id, text, esc) {
  return `<textarea class="note-input" data-note-input="${id}" rows="2"` +
    ` aria-label="Note text. Enter saves, Shift and Enter makes a new line, Escape cancels"` +
    ` placeholder="A note…">${esc(text || "")}</textarea>` +
    `<span class="note-hint" aria-hidden="true">Enter saves · Shift+Enter new line · Esc cancels</span>`;
}

// The box that opens under a step for "+ note". id is the STEP's id, so the draft cannot collide
// with an open note editor.
export function newNoteBoxHTML(stepId, esc, { text = "" } = {}) {
  return `<div class="note-row note-editing note-new" data-new-note="${stepId}">` +
    `<span class="note-tag note-tag-flat">Note</span>` +
    `<textarea class="note-input" data-new-note-input="${stepId}" rows="2"` +
    ` aria-label="A new note on this step. Enter saves, Shift and Enter makes a new line,` +
    ` Escape cancels" placeholder="A note on this step…">${esc(text || "")}</textarea>` +
    `<span class="note-hint" aria-hidden="true">Enter saves · Shift+Enter new line · Esc cancels` +
    `</span></div>`;
}

export function addNoteButtonHTML(stepId, esc, label = "+ note") {
  return `<button type="button" class="step-add-note" data-add-note="${stepId}"` +
    ` aria-label="Add a note to this step">${esc(label)}</button>`;
}

export function savedToastHTML() {
  return `<span class="note-toast" role="status">Saved</span>`;
}

// ⚠️ THE UNDO IS PART OF THE MESSAGE, NOT A SEPARATE CONTROL SOMEWHERE ELSE. role="status" so a
// screen reader hears it without the focus moving, and the button is reachable straight after.
export function undoToastHTML(what, token, esc) {
  return `<div class="note-toast note-toast-undo" role="status" data-note-toast="${esc(token)}">` +
    `${esc(what)} · <button type="button" class="note-undo" data-note-undo="${esc(token)}">Undo` +
    `</button></div>`;
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
export function noteTextChanged(note, draft) {
  return String(draft == null ? "" : draft).trim() !== String(note.text || "").trim();
}
