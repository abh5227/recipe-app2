"use strict";
// Notes held in the Edit-mode draft: the operations Save writes and Cancel throws away.
//
// ⚠️ TWO VIEWS, TWO PROMISES, AND THIS FILE IS THE SECOND ONE. On the recipe page a note is written
// the moment the cook finishes typing it, with an Undo. Inside Edit mode the page already has a
// Save and a Cancel, and a note that ignored them was the one thing on that screen a Cancel did not
// cancel. These functions change a LIST and nothing else, so the only way a note reaches the
// database from Edit mode is the recipe PUT.
//
// ⚠️ EVERY ONE RETURNS A NEW ARRAY. view.draft is a structuredClone of view.data, and an in-place
// splice on a row object would reach the copy that the page is still reading from.
//
// ⚠️ AND THE RULES HERE MIRROR write_notes, DELIBERATELY AND NARROWLY. The server re-scans a note's
// step mentions on every save and carries a stored reference only while its (ref_index, match_text)
// survives. The draft has to show what the save will store, so it carries them the same way. Where
// the two could disagree, the server wins: it is the one that writes.
import { STEP_MENTION } from "./note-text.js";

// {step id -> the number the page prints}, null for a heading.
// ⚠️ THE PYTHON SIDE IS notes.py::step_numbers AND THE TWO ANSWER THE SAME QUESTION. The server
// resolves this for the rows it sends; the draft holds steps the server has not seen yet (one added
// this session, one deleted), so the client has to be able to answer it too.
export function noteStepNumbers(steps) {
  const by = new Map();
  let n = 0;
  for (const s of steps || []) {
    if (!s.is_heading) n += 1;
    by.set(s.id, s.is_heading ? null : n);
  }
  return by;
}

// Fill each note's step_no / step_ok and each reference's step_no, against THESE steps.
// ⚠️ A LINK TO A STEP THAT IS NO LONGER IN THE DRAFT RESOLVES TO NOTHING, which is what makes
// "delete the step, the note survives unlinked" visible before the save rather than only after it.
// The stored step_id is kept, exactly as the server keeps it, so nothing is decided here that the
// save cannot decide again.
export function resolveNoteSteps(notes, steps) {
  const by = noteStepNumbers(steps);
  return (notes || []).map((n) => {
    const no = n.step_id ? (by.has(n.step_id) ? by.get(n.step_id) : null) : null;
    return { ...n, step_no: no, step_ok: n.step_id == null ? true : no != null,
             refs: (n.refs || []).map((r) => ({
               ...r, step_no: r.step_id ? (by.has(r.step_id) ? by.get(r.step_id) : null) : null })) };
  });
}

// Every "step N" in a piece of text, as {ref_index, match_text}. The same walk note-text.js renders
// with, so the editor and the carry below count the same mentions.
export function scanMentions(text) {
  const out = [];
  const re = new RegExp(STEP_MENTION.source, STEP_MENTION.flags);
  for (let m = re.exec(String(text || "")); m; m = re.exec(String(text || ""))) {
    out.push({ ref_index: out.length, match_text: m[0] });
  }
  return out;
}

// ⚠️ A REFERENCE SURVIVES ONLY WHILE ITS MENTION DOES, KEYED ON THE WORDS AND THE ORDINAL. This is
// write_notes' carry rule, stated on the client so the draft shows what the save will store.
// Inserting a sentence before "step 9" keeps the link. Rewording "step 9" to "step 3" drops it, and
// the editor then reads 3 rather than quietly printing the old step's current number.
export function carryRefs(refs, text) {
  const had = new Map((refs || []).map((r) => [`${r.ref_index}\u0000${r.match_text}`, r]));
  return scanMentions(text).map((m) => {
    const was = had.get(`${m.ref_index}\u0000${m.match_text}`);
    return { ref_index: m.ref_index, match_text: m.match_text,
             step_id: was ? was.step_id : null, step_no: was ? was.step_no : null };
  });
}

// ⚠️ A NEW NOTE'S ID IS NEGATIVE, so it cannot be mistaken for a row the database has. It never
// leaves the client: write_notes matches incoming notes to stored ones by WORDING and then by
// order, and reads no id at all.
export function nextDraftId(notes) {
  let lowest = 0;
  for (const n of notes || []) if (+n.id < lowest) lowest = +n.id;
  return lowest - 1;
}

const sameId = (a, b) => String(a) === String(b);

export function draftSetText(notes, id, text) {
  return (notes || []).map((n) => (sameId(n.id, id)
    ? { ...n, text: String(text), refs: carryRefs(n.refs, text) } : n));
}

export function draftSetKind(notes, id, kind) {
  return (notes || []).map((n) => (sameId(n.id, id) ? { ...n, kind: String(kind) } : n));
}

export function draftSetStep(notes, id, stepId) {
  const to = stepId == null ? null : +stepId;
  return (notes || []).map((n) => (sameId(n.id, id) ? { ...n, step_id: to } : n));
}

// A new note goes at the END of the list, which is where the adder is and where the server will put
// it: write_notes assigns positions from the order it is given.
export function draftAdd(notes, { text, stepId = null, kind = "notes" }) {
  const list = notes || [];
  const row = { id: nextDraftId(list), kind, text: String(text), step_id: stepId == null ? null : +stepId,
                ingredient_row_id: null, position: list.length, step_no: null, step_ok: true,
                refs: carryRefs([], text) };
  return [...list, row];
}

export function draftDelete(notes, id) {
  return (notes || []).filter((n) => !sameId(n.id, id)).map((n, i) => ({ ...n, position: i }));
}

// Putting back a deleted note, at the place it came from. The Undo offer in Edit mode is a list
// operation like every other one here, so Cancel still throws the whole thing away.
export function draftRestore(notes, row, at) {
  const list = [...(notes || [])];
  const i = Math.max(0, Math.min(list.length, at == null ? list.length : +at));
  list.splice(i, 0, { ...row });
  return list.map((n, k) => ({ ...n, position: k }));
}

// What the recipe PUT carries. One shape, built here, so Edit mode cannot send a note the per-note
// endpoints could not have written.
// ⚠️ A ROW WITH NO WORDS IS DROPPED RATHER THAN SENT, matching every other list in draftPayload: a
// blank box is one the cook left half-written, and write_notes filters it out again anyway.
export function notesPayload(notes) {
  return (notes || [])
    .filter((n) => String(n.text || "").trim())
    .map((n) => ({
      text: String(n.text).trim(),
      kind: n.kind,
      step_id: n.step_id == null ? null : +n.step_id,
      ingredient_row_id: n.ingredient_row_id == null ? null : +n.ingredient_row_id,
      // ⚠️ ROUND-TRIPPED VERBATIM, exactly as a wait's step check is. The server takes a sent
      //    reference only when its (ref_index, match_text) still matches what it re-scans, so a
      //    stale one is dropped there rather than trusted here.
      refs: (n.refs || []).map((r) => ({ ref_index: r.ref_index, match_text: r.match_text,
                                         step_id: r.step_id == null ? null : +r.step_id })),
    }));
}
