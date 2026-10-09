"use strict";
// Pure ingredient-row transforms (no DOM, no `view`) so they're unit-testable in node. ES module,
// like scaler.js: app.js imports these names in the browser (loaded as <script type="module">)
// and the tests under tests/js/ import them the same way.
import { SECOND_AMOUNT_JOIN } from "./scaler.js";

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
    else if (key === "second") row.secondary_measure = val;   // round B: the author's second amount
    else if (key === "name") row.label = val;
    else if (key === "note") row.note = val;
    else if (key === "heading") row.heading = val;
    return row;
  }

  // Edit mode shows the FIRST amount only, with the second behind an expand (Andy's call on the
  // round B click-through). C1 is how it is drawn (Andy, 9 Oct, decisions-4): a small arrow beside
  // the amount, and nothing else while it is closed. The arrow is FILLED when the row has a second
  // amount and an outline when it has none, so a second amount is never hidden in silence, and its
  // title and label carry the value. Open, the field or fields sit under the amount.
  //
  // ⚠️ `_secondOpen` IS A DRAFT-ONLY FLAG AND IT IS NEVER SAVED. ingToPayload builds its object by
  // naming each key, so an underscore field on the draft row cannot reach the wire. That is also
  // why opening the field is not a content change: Save, Undo and the "your changes" mark see
  // exactly what they saw before, which is the condition Andy put on this.
  //
  // ⚠️ AND IT DOES NOT AUTO-OPEN THE WAY A NOTE DOES. addNote opens its field whenever the row
  // HAS a note, because a note is prose a cook reads while editing. The second amount is a
  // measurement, and the whole point of the change is that the amount column shows one figure.
  //
  // ⚠️ THE VALUE IS WHAT A SAVE WOULD SEND. A row whose lines were all cleared holds " / " while its
  //    fields are open, and that is not a second amount: the arrow drew filled with the title
  //    "Second amount: /" while the save stored NULL. Found by a fresh review.
  function secondToggle(row) {
    const value = secondForSave(row && row.secondary_measure).trim();
    return { open: !!(row && row._secondOpen), value, has: value !== "" };
  }

  // The lines the open arrow shows, one field each, split exactly the way the reading view splits
  // them (scaler.js secondAmountParts), so "1 lb / 4 medium / or 2 long" opens as three fields. A
  // row with no second amount opens one empty field to type into.
  function secondLines(row) {
    const value = String((row && row.secondary_measure) || "");
    return value.trim() === "" ? [""] : value.split(SECOND_AMOUNT_JOIN);
  }

  // The slot, rebuilt from the open fields in order. The fields are read as a whole rather than one
  // line patched by position, so a line the cook splits by typing " / " cannot push the line below
  // it out from under the next keystroke.
  function joinSecondLines(values) {
    return values.join(SECOND_AMOUNT_JOIN);
  }

  // What a save sends for the slot. ⚠️ A CLEARED LINE STAYS IN THE DRAFT, EMPTY, while the fields
  // are open, because dropping it on the keystroke would renumber the fields under the cursor. It
  // is left out here, on the way to the server. A slot with no blank line goes back EXACTLY as it
  // is, which is every row nobody typed into, so the payload of an untouched row cannot move.
  function secondForSave(value) {
    const s = value == null ? "" : String(value);
    const lines = s.split(SECOND_AMOUNT_JOIN);
    if (!lines.some((l) => l.trim() === "")) return s;
    return lines.filter((l) => l.trim() !== "").join(SECOND_AMOUNT_JOIN);
  }

  export { headingText, toggleRowType, rowIsBlank, nonEmptyRows, writeIngField, secondToggle,
           secondLines, joinSecondLines, secondForSave };
