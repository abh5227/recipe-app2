// drop-index.js — where a dragged ROW lands. Pure geometry: a list of rects + the pointer's y in, a
// drop target out. No DOM, no globals, no `view` — the caller collects getBoundingClientRect() and
// passes them, so this runs under bare `node --test` (tests/js/drop-index.test.js).
//
// It is a SIBLING of reorder.js rather than part of it, deliberately. reorder.js is geometry-free: it
// knows only an id-list and a "before" reference, which is why the album, this, and any future
// keyboard reorder can all share it unchanged. This module is nothing BUT viewport coordinates, and
// its axis is fixed (y). Folding the one axis-dependent thing into the one axis-independent module
// would couple them for no gain — the album tests clientX, these lists test clientY.
//
// ⚠️ HEIGHT-AGNOSTIC — A RECORDED BUILD CONSTRAINT, NOT AN IMPLEMENTATION DETAIL.
// The target is decided by comparing clientY against each rect's OWN midpoint. There is no row-height
// anywhere in this file and there must never be: no `Math.floor(y / rowHeight)`, no "rows are 44px",
// no total-height division. Editor rows are emphatically not uniform — a step with three sentences of
// method text is several times the height of a one-line ingredient, and either list can hold a heading
// row, a wrapped ingredient name, or an expanded overrides panel. Uniform arithmetic would be correct
// on the demo recipe and wrong on every real one. tests/js/drop-index.test.js pins this with a rects
// list mixing 44px and 140px rows whose midpoint answer differs from the uniform answer, so
// reintroducing height arithmetic fails loudly rather than degrading quietly.
//
// The mechanism is lifted from the album's live drag (app.js reorderDragOver): scan for the first row
// whose midpoint is past the pointer, skipping the dragged row. Same comparator, different axis.

import { reorderBefore } from "./reorder.js";

// Returns the index of the row the dragged row should be inserted BEFORE, or null for "the end".
//
// ⚠️ A BEFORE-REFERENCE, NOT A LANDING INDEX — and the difference is the classic drag off-by-one.
// A landing index means different things before and after the dragged row is removed from the array,
// so it changes with the drag's DIRECTION even when the drop point and the visible outcome do not:
//   [A,B,C,D], drop between C and D. Dragging A down: before-ref 3, landing index 2 (removing A
//   shifted everything left). Dragging D up to the same slot: before-ref 2, landing index 2.
// The before-reference is stable under that removal; the landing index is not. That is why the album
// has no direction bug despite doing no adjustment arithmetic — and why this returns the same shape
// reorderBefore already consumes, so no caller is ever tempted to add or subtract one. Feed the
// result straight to applyRowDrop (or to reorderBefore) and the off-by-one has nowhere to live.
//
// `rects` need only be {top, height} — real DOMRects or plain objects both work.
// `draggedIndex` is skipped so a drag can never target itself (the album skips explicitly too); pass
// null when nothing is being dragged (e.g. painting a drop bar for an insertion with no source row)
// and every row is eligible.
//
// TIE-BREAK: `<` is strict, copied verbatim from the album's comparator so the two cannot drift. A
// pointer exactly ON a midpoint is therefore NOT before that row — it falls through and lands AFTER
// it. Arbitrary but fixed, and pinned by a test; the alternative would make the boundary pixel behave
// differently in the two lists for no reason a user could perceive.
export function dropBeforeIndex(rects, clientY, draggedIndex) {
  if (!Array.isArray(rects) || !Number.isFinite(clientY)) return null;
  for (let i = 0; i < rects.length; i++) {
    if (i === draggedIndex) continue;                       // never target the dragged row itself
    const r = rects[i];
    if (!r || !Number.isFinite(r.top) || !Number.isFinite(r.height)) continue;   // unmeasurable -> not a target
    if (clientY < r.top + r.height / 2) return i;
  }
  return null;                                              // past every midpoint -> dropped at the end
}

// Apply a drop to an array of ROWS, returning a NEW array (the input is never mutated).
//
// The array move itself is NOT reimplemented here: it funnels through reorderBefore, so there stays
// exactly one definition of what a drop does to a list. reorderBefore works on an id-list and the
// editor drafts are arrays of row objects with no ids, so this permutes [0…n-1] — unique integers,
// safe under its identity comparisons — and maps back. That translation is the one line where a
// caller could get the composition wrong, which is why it lives here under test rather than at two
// call sites (ingredients in C1, steps in C2).
//
// REFUSES (returns null, meaning "do nothing") rather than clamping an out-of-range draggedIndex,
// following insertIndexFor's precedent: reorderBefore is defensive about an unknown id and APPENDS
// it, so a stale index would silently grow the list by one phantom row instead of erroring. A stale
// index between a splice and its re-render is a real thing on these delegated handlers.
// beforeIndex === null is the legitimate "drop at the end" and is passed straight through.
export function applyRowDrop(rows, draggedIndex, beforeIndex) {
  if (!Array.isArray(rows)) return null;
  if (!Number.isInteger(draggedIndex) || draggedIndex < 0 || draggedIndex >= rows.length) return null;
  if (beforeIndex != null &&
      (!Number.isInteger(beforeIndex) || beforeIndex < 0 || beforeIndex >= rows.length)) return null;
  const order = rows.map((_, i) => i);
  return reorderBefore(order, draggedIndex, beforeIndex).map((i) => rows[i]);
}
