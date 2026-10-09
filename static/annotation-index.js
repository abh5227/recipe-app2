"use strict";
// Which annotations belong to which rendered row — pure (no DOM, no `view`), so it's unit-testable in
// node like annotation-place.js / ingredient-row.js. app.js imports it in the browser.
//
// ⚠️ KEYED ON THE ROW'S DATABASE ID, WHICH USED TO BE ITS POSITION. The diff emitted new_pos, the
// heading-EXCLUDED ordinal of the row in its own kind's sequence, and the reading view had to rebuild
// that same number by walking its rendered rows and skipping headings in exactly the same places. Two
// independent counters agreeing by convention, and every feature that inserts a row into the rendered
// list (a struck removal, a synthesized row) had to know not to advance one of them. Option C gave
// every content row a database id that survives a save, the baseline records it, and the diff now
// carries it on each entry as row_id, so the lookup is the row itself.
//
// A REMOVED entry is still different in kind and still handled separately: the row is gone from the
// current data, so there is no rendered row to attach it to and no id to key on. Those are returned as
// flat lists and placed by `section` (annotation-place.js). Ordered by old_pos so several removals out
// of one section keep their original relative order.
//
// A single row may carry BOTH an amount and a name edit, so entries are grouped into one slot per row.
// kind "heading" is ignored: a heading change carries no annotation by standing ruling.
//
// ⚠️ THE SECOND AMOUNT HAS A SLOT OF ITS OWN (Andy, round B revision 4). snapshot_diff has emitted a
//    second_amount entry since Edit mode first carried the field, and this index dropped it, so the
//    change was recorded and the page drew nothing. A row may now carry amount, name and
//    second_amount at once. Only the slot is new, and the entries are the server's, unchanged.
const MARKED_FIELDS = new Set(["amount", "name", "second_amount"]);

function annotationIndex(anns) {
  const ing = new Map();
  const step = new Map();
  const removedIng = [];
  const removedStep = [];
  for (const a of (anns || [])) {
    if (a.type === "removed") {
      if (a.kind === "ingredient") removedIng.push(a);
      else if (a.kind === "step") removedStep.push(a);
      continue;
    }
    if (a.row_id == null) continue;        // field entries, and anything with no current row
    if (a.kind === "ingredient") {
      const slot = ing.get(a.row_id) || {};
      if (a.type === "added") slot.added = a;
      else if (a.type === "modified" && MARKED_FIELDS.has(a.field)) slot[a.field] = a;
      ing.set(a.row_id, slot);
    } else if (a.kind === "step") {
      const slot = step.get(a.row_id) || {};
      if (a.type === "added") slot.added = a;
      else if (a.type === "modified") slot.mod = a;
      step.set(a.row_id, slot);
    }
  }
  const byOldPos = (x, y) => (x.old_pos == null ? 0 : x.old_pos) - (y.old_pos == null ? 0 : y.old_pos);
  removedIng.sort(byOldPos);
  removedStep.sort(byOldPos);
  return { ing, step, removedIng, removedStep };
}

export { annotationIndex };
