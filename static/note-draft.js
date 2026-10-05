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
import { linkedStepNo, linkedStepId } from "./note-blocks.js";
import { reorderBefore } from "./reorder.js";
import { insertIndexFor } from "./row-insert.js";

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

// ---- the group a note is reordered inside -------------------------------------------------------
// ⚠️ THE GROUP IS WHAT THE READER SEES, NOT A COLUMN. noteSections prints linked notes under STEP
// NOTES ordered by step number, and everything else under its type. So a note's group is its STEP
// when it has one and its KIND when it does not, and a drag may only move a note among the notes
// that share that answer. A drop anywhere else is refused rather than clamped, which is
// insertIndexFor's precedent: the wrong answer here is a note that silently changes what it is
// about.
// ⚠️ AND THE KIND IS THE DECORATED ONE. noteBlocks maps a kind the table does not list onto the
// first kind, so two notes with different stored kinds can read in one group. Keying on the stored
// value would refuse a drop the page plainly offers.
export function noteGroupKey(note, table) {
  const no = linkedStepNo(note);
  if (no != null) return `step:${no}`;
  const kinds = table || [];
  const known = kinds.some((k) => k.kind === note.kind);
  return `kind:${known || !kinds.length ? note.kind : kinds[0].kind}`;
}

// The notes that have somewhere to go: ids whose drag group holds at least one OTHER note.
// ⚠️ A HANDLE THAT CANNOT MOVE ANYTHING IS A PROMISE THE ROW CANNOT KEEP. A note alone in its
// group — the only one on its step, or the only one of its type — has no legal drop target at all,
// so dragging it can only ever snap back. The grip is drawn from this answer and the ⋯ menu is not,
// because adding and deleting are still available to a lone note.
// ⚠️ IT IS ASKED OF THE WHOLE LIST, NOT OF ONE NOTE, so one pass over the draft answers for every
// row and the renderer cannot ask it a different way per group.
// ⚠️ AND THE IDS COME BACK AS STRINGS. Every id in the editor reaches the DOM through a data-
// attribute and comes back a string, which is exactly the mismatch that sent a dropped note to the
// bottom of its group. Keying the set by String() means a caller cannot get that wrong here.
export function noteDragMates(notes, table) {
  const list = notes || [];
  const n = new Map();
  for (const row of list) {
    const k = noteGroupKey(row, table);
    n.set(k, (n.get(k) || 0) + 1);
  }
  return new Set(list.filter((row) => n.get(noteGroupKey(row, table)) > 1)
                     .map((row) => String(row.id)));
}

// Move a note to sit immediately BEFORE `beforeId`, or to the END OF ITS OWN GROUP when that is
// null. Returns a new list, or null for "refused, change nothing".
// ⚠️ THE MOVE ITSELF IS reorderBefore, the same one the album and both editor lists use. What is
// stated here is only which destinations are legal and what "the end" means for a group that is
// not at the end of the list.
// ⚠️ AND IT RENUMBERS position, because that is what the save sends and what the reading page reads
// back. write_notes assigns positions from the order it is given, so the list order IS the order.
export function draftReorder(notes, table, id, beforeId) {
  const list = notes || [];
  const from = list.findIndex((n) => sameId(n.id, id));
  if (from < 0) return null;
  const key = noteGroupKey(list[from], table);
  let ref = beforeId == null ? null : beforeId;
  if (ref == null) {
    // the end of this note's own run: the first note AFTER the last of its mates, or the list's end
    let last = -1;
    list.forEach((n, i) => { if (noteGroupKey(n, table) === key) last = i; });
    if (last < 0 || sameId(list[last].id, id)) return null;       // already last: nothing to do
    ref = last + 1 < list.length ? list[last + 1].id : null;
  } else {
    const t = list.find((n) => sameId(n.id, ref));
    if (!t || sameId(t.id, id)) return null;                       // onto itself, or a stale id
    if (noteGroupKey(t, table) !== key) return null;               // another group: refused
    // ⚠️ THE ROW'S OWN id VALUE, NOT THE CALLER'S. reorderBefore compares ids with !== and
    //    indexOf, which are identity tests, and the caller reads this id off a data- attribute, so
    //    it arrives as the STRING "159" against a list of NUMBERS. indexOf then answered -1,
    //    reorderBefore took its defensive append branch, and a note dropped at the top of its
    //    group landed at the BOTTOM of it. Measured in the browser; the unit tests passed numbers
    //    and never saw it. sameId compares as strings on purpose; what goes on to reorderBefore
    //    has to be the value the list holds.
    ref = t.id;
  }
  const moved = reorderBefore(list.map((n) => n.id), list[from].id, ref);
  const by = new Map(list.map((n) => [String(n.id), n]));
  return moved.map((x, i) => ({ ...by.get(String(x)), position: i }));
}

// A note added above or below another one. Returns a new list, or null for "refused".
// ⚠️ IT COPIES THE TYPE AND THE STEP LINK, WHICH IS THE WHOLE POINT. A blank note with neither
// lands under the first type group, so "Add note below" on a Storage note under Step 4 would put
// the new note somewhere else entirely and the cook would have to find it.
// ⚠️ THE STEP IS COPIED AS AN ID, EVEN WHERE THE NEIGHBOUR REACHED ITS STEP THROUGH ITS WORDS. A
// reference lives in the text and the new note has no text yet, so the only way to put it in the
// same group is its own link. linkedStepId is the one place that rule is written down.
// ⚠️ AND THE NEW ROW'S ID IS nextDraftId(notes), which a caller needs in order to open the editor
// on it. Both read the same list, so both get the same answer; it is not returned twice.
export function draftAddBeside(notes, table, id, pos) {
  const list = notes || [];
  const i = list.findIndex((n) => sameId(n.id, id));
  if (i < 0) return null;
  const at = insertIndexFor(pos, i, list.length);
  if (at == null) return null;
  const mate = list[i];
  const row = { id: nextDraftId(list), kind: mate.kind, text: "",
                step_id: linkedStepId(mate), ingredient_row_id: null,
                position: at, step_no: null, step_ok: true, refs: [] };
  return [...list.slice(0, at), row, ...list.slice(at)]
    .map((n, k) => ({ ...n, position: k }));
}

// What the recipe PUT carries. One shape, built here, so Edit mode cannot send a note the per-note
// endpoints could not have written.
// ⚠️ A ROW WITH NO WORDS IS DROPPED RATHER THAN SENT, matching every other list in draftPayload: a
// blank box is one the cook left half-written, and write_notes filters it out again anyway.
// ⚠️ THE ROW IT CAME FROM IS NAMED, AND A NEW ONE NAMES NOTHING. Without an id the server pairs
// incoming notes to stored ones by wording and then by ORDER, which cannot tell "delete A, add B"
// from "reword A": both arrive as one list of the same length. Sending the id makes the cook's own
// answer the one that decides. A draft id is negative and is never sent, so a note written this
// session has no id and the server gives it a new row.
export function notesPayload(notes) {
  return (notes || [])
    .filter((n) => String(n.text || "").trim())
    .map((n) => ({
      ...(Number.isInteger(+n.id) && +n.id > 0 ? { id: +n.id } : {}),
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
