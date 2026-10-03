"use strict";
// The plan-ahead editor's two pure decisions: what a wait or storage row's ⋯ menu offers, and what
// an item does to the list. No DOM, no `view`.
//
// ⚠️ EXTRACTED FOR THE REASON note-text.js AND step-row.js WERE. The reorder and the insert are array
// surgery on the rows a recipe is made of, and while they sat inside a DOM handler in app.js there
// was no way to state them in a test: the browser driver this machine has is flaky, and "I clicked
// it and it looked right" is not a regression test. A swap that writes the wrong index corrupts a
// wait's minutes onto another wait's words, which is the class of defect that cost a whole round
// once already (see the note on moving a note in the old editor).

export const PLAN_AHEAD_KINDS = ["wait", "store"];

// ⚠️ A WAIT AND A STORAGE ROW HAVE NO HEADINGS AND NO CONVERSION, so the menu is the three things
// they CAN do. Move up / Move down are the reorder, and they are disabled at the ends rather than
// absent, so the menu does not change shape as you move a row through the list.
export function planAheadMenuItems(kind, i, length) {
  const what = kind === "wait" ? "wait" : "storage row";
  return [
    { act: "add-row", label: `Add ${what}` },
    { sep: true },
    { act: "up", label: "Move up", disabled: i <= 0 },
    { act: "down", label: "Move down", disabled: i >= length - 1 },
    { sep: true },
    { act: "delete", label: "Delete", danger: true },
  ];
}

// ⚠️ IT RETURNS A NEW ARRAY AND NEVER TOUCHES THE ONE IT IS GIVEN, so a refused action cannot leave
// the list half-edited. `null` means "nothing happened", which is how the caller knows not to
// repaint or to mark the draft dirty.
//
// ⚠️ AND A MOVE SWAPS THE ROW OBJECTS, NOT THEIR TEXT. A wait carries its minutes, its step links
// and its condition beside its words; moving the words alone would leave every one of those behind,
// which is the exact defect the old notes editor had ("MOVING A NOTE SWAPS THE OBJECTS").
export function planAheadRowAction(arr, i, act, blank) {
  const rows = Array.isArray(arr) ? arr.slice() : [];
  if (!Number.isInteger(i) || i < 0 || i >= rows.length) {
    // An index that names no row means the menu outlived the row it belonged to. Do nothing rather
    // than guess a position, which is the rule row-insert.js already states for the two big lists.
    return act === "add-row" && rows.length === 0 ? [blank] : null;
  }
  if (act === "add-row") { rows.splice(i + 1, 0, blank); return rows; }
  if (act === "delete") { rows.splice(i, 1); return rows; }
  if (act === "up") {
    if (i === 0) return null;
    [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]];
    return rows;
  }
  if (act === "down") {
    if (i >= rows.length - 1) return null;
    [rows[i], rows[i + 1]] = [rows[i + 1], rows[i]];
    return rows;
  }
  return null;
}

export function blankWait() {
  return { kind: "other", label: "", ext_label: "", when_kind: "always", when_label: "",
           step_id: null, alongside_step_id: null, ext_step_id: null };
}

export function blankStorage() {
  return { where_kept: "fridge", applies_to: "", label: "" };
}
