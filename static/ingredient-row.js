"use strict";
// Pure ingredient-row transforms (no DOM, no `view`) so they're unit-testable in node. ES module,
// like scaler.js: app.js imports these names in the browser (loaded as <script type="module">)
// and the tests under tests/js/ import them the same way.

  // The heading text to DISPLAY / SAVE for a heading row. Heading text lives in its own `heading`
  // field; `raw_text` is only a back-compat fallback for drafts that predate the dedicated field.
  function headingText(row) {
    return row.heading != null ? row.heading : (row.raw_text || "");
  }

  // Lossless ingredient<->heading toggle (Option A1): MUTATE the row in place, never destroy the
  // ingredient fields. qty / label / note / ingredient_id (and grams / secondary_measure / position)
  // stay on the object while it's a heading (dormant, just not rendered), so a round-trip restores
  // them exactly. Heading text lives in its OWN `heading` field — it never shares raw_text with the
  // name, so neither clobbers the other. Returns the same (mutated) row.
  function toggleRowType(row) {
    if (row.is_heading) {
      // heading -> ingredient: the ingredient fields are still here (dormant) -> restored as-is.
      row.is_heading = 0;
      // A "born" heading has no dormant name; carry its current heading text into the name.
      if (!(row.label || "").trim()) row.label = headingText(row);
    } else {
      // ingredient -> heading: keep qty/label/note/ingredient_id untouched; seed the heading text
      // from the current name only when it's still blank (so a re-toggle preserves an edited heading).
      row.is_heading = 1;
      if (!(row.heading || "").trim()) row.heading = row.label || row.raw_text || "";
    }
    return row;
  }

  // A row is "blank" (dropped on save): an ingredient with no name (label/raw_text all blank —
  // regardless of a stray qty/note), or a heading with no heading text. Work-in-progress blanks are
  // fine while editing; this only prunes them at save time.
  function rowIsBlank(row) {
    return row.is_heading ? !headingText(row).trim()
                          : !((row.label || row.raw_text || "").trim());
  }
  function nonEmptyRows(rows) {
    return rows.filter((r) => !rowIsBlank(r));
  }

  // Write an edited value into the right draft-row field for a given field key. Shared by the input
  // handler (live buffering) and the Esc-revert (restore the focus-time snapshot). `name` writes to
  // `label` (the convention ingToPayload reads); `heading` has its own field. Returns the (mutated) row.
  function writeIngField(row, key, val) {
    if (key === "qty") row.qty = val;
    else if (key === "quantity") row.quantity = val;   // Stage 4: structured amount expression
    else if (key === "unit") row.unit = val;           // Stage 4: structured unit
    else if (key === "name") row.label = val;
    else if (key === "note") row.note = val;
    else if (key === "heading") row.heading = val;
    return row;
  }

  export { headingText, toggleRowType, rowIsBlank, nonEmptyRows, writeIngField };
