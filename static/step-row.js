"use strict";
// Pure step-row transforms (no DOM, no `view`) so they're unit-testable in node — the step sibling of
// ingredient-row.js. app.js imports these names in the browser (loaded as <script type="module">) and
// the tests under tests/js/ import them the same way. Deliberately NOT in step-adapter.js, which is
// scoped to the [[key|label]] text <-> ProseMirror round-trip (gated by a byte-fidelity test); this is
// draft-row save semantics, a separate concern.

  // A step is "blank" (dropped on save): no text once trimmed. BOTH kinds keep their text in `text` —
  // a heading step carries its label there too (see stepToPayload / renderStepRow) — so one check
  // covers both. Mirrors ingredient-row's rowIsBlank, which likewise prunes a textless heading: such a
  // heading renders as nothing, and the server would silently DEMOTE {heading: ""} to an empty
  // non-heading row anyway (write_recipe_rows branches on `step.get("heading")`, which "" fails).
  function stepIsBlank(step) {
    return !((step && step.text) || "").trim();
  }

  // Prune blank steps at SAVE time only — work-in-progress blanks are fine while editing (the same
  // contract as nonEmptyRows for ingredients). Clearing a step's text is therefore how you delete it.
  function nonEmptySteps(steps) {
    return steps.filter((s) => !stepIsBlank(s));
  }

  // Where the caret goes after step `i` is deleted, given the list length AFTER the splice: the step
  // that TOOK its place, or the new last step when the deleted one was last. null when nothing is left.
  function focusIndexAfterRemove(i, lenAfter) {
    if (!(lenAfter > 0)) return null;
    return Math.min(Math.max(i, 0), lenAfter - 1);
  }

  // Buffer a typed value into a draft STEP row — the step twin of ingredient-row.js's writeIngField.
  // Its existence IS the reason step headings get their own data-inline-edit-step namespace: every
  // caller of writeIngField indexes view.draft.ingredients, so routing a heading through that path
  // would write into the ingredient array at the STEP's index — silent cross-array corruption.
  // A heading's label lives in `text`, the same field a non-heading step uses (see stepIsBlank and
  // stepToPayload), so both keys land there. Tolerates a missing row on purpose: the delegated
  // listeners can fire on a stale data-i between a splice and its re-render, and Esc-revert reads the
  // row through an optional chain. Returns the row, like writeIngField.
  function writeStepField(row, key, val) {
    if (!row) return row;
    if (key === "heading" || key === "text") row.text = val;
    return row;
  }

  export { stepIsBlank, nonEmptySteps, focusIndexAfterRemove, writeStepField };
