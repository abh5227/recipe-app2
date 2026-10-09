// save-payload.js — the DB row shape -> the PUT payload the server writes from.
//
// Extracted from app.js so a test can reach it. The wire format is unchanged, byte for byte: this
// is the same code, moved. It matters because the SERVER's carry logic (app.py _Carry) has to match
// what this produces, and until now no test could hold the two together.
// tests/fixtures/save-roundtrip.json is captured FROM these functions and asserted by both suites.
//
// ⚠️ canonicalizeUnit REWRITES THE UNIT, AND THAT IS DELIBERATE. "1 teaspoon" goes back as "1 tsp".
// Measured on live data: 1,157 of 3,349 rows. The server's carry key compares amounts through
// units.canon_unit_str, the Python mirror of it, so an untouched row still matches itself.
//
// ⚠️ EVERY ROW NOW CARRIES ITS DATABASE id, AND A NEW ROW CARRIES null (option C, commit 1). The GET
// already served `id` on every ingredient and step row, and enterEditMode's structuredClone already
// copied it into the draft. It was dropped here, on the way back, which is why no row id survived a
// save: write_recipe_rows deletes the recipe's rows and reinserts them with no id at all. The server
// IGNORES the id until commit 2 gives it a meaning, so this is additive on its own.
import { canonicalizeUnit } from "./scaler.js";
// ⚠️ IMPORTED, NOT RE-SPELLED. This used to read `x.heading || x.label || x.raw_text`, which was the
// same fallback one letter longer and went wrong the moment a heading row kept its label: migration
// 052 lets a heading hold the line's dormant name, so the `|| x.label` arm would have sent "salt"
// back as the section title and renamed the heading on the next save. headingText is the one
// definition of "which string is the title", and the server's _heading_title mirrors it.
import { headingText, secondForSave } from "./ingredient-row.js";
import { stepLevel } from "./step-row.js";

// A row the user just added has no id yet. `undefined` and `null` are the same answer here, and
// sending the key always means the server never has to tell "no id" from "the key is missing".
const rowId = (x) => (x && x.id != null ? x.id : null);

// The name is a .ie-line (soft-wrap only), so a hard newline is the only thing folded away.
const oneLine = (v) => (v || "").replace(/[\r\n]+/g, " ");

export function ingToPayload(x) {
  const id = rowId(x);
  if (x.is_heading) return { id, heading: oneLine(headingText(x)) };   // `heading`, else raw_text
  // Stage 4 (B): send the STRUCTURED parts — quantity + canonical unit. The server recombines
  // qty = quantity + " " + unit, so qty is omitted. Authority is quantity+unit.
  const quantity = oneLine(x.quantity);
  const unit = canonicalizeUnit(x.unit);
  // ⚠️ THE SECOND AMOUNT IS SENT ON EVERY LINE, AND THE KEY BEING PRESENT IS WHAT MAKES IT AN
  // ANSWER. A cook who clears the field sends "", which stores NULL. A client too old to know
  // about the field sends no key at all, and the server then keeps what it has rather than
  // reading the silence as a deletion. Same rule a note's kind and step link follow.
  // ⚠️ AND A LINE THE COOK CLEARED IS LEFT OUT (C1's fields, one per line). secondForSave returns
  // every slot without a blank line unchanged, so an untouched row sends what it always sent.
  const second = oneLine(secondForSave(x.secondary_measure));
  if (x.ingredient_id) return { id, quantity, unit, secondary_measure: second, item: x.ingredient_id, label: oneLine(x.label || x.raw_text), note: x.note || "" };
  return { id, quantity, unit, secondary_measure: second, text: oneLine(x.label || x.raw_text), note: x.note || "" };
}

// ⚠️ A NON-HEADING STEP USED TO GO BACK AS A BARE STRING, and it is now an object, because a string
// has nowhere to put an id. The server still accepts the string form and always will: the import
// review posts plain text, and a browser holding an old bundle over a deploy posts it too. See
// app.py _step_parts, which reads both forms and is the only place that knows about either.
export function stepToPayload(x) {
  const id = rowId(x);
  // ⚠️ THE LEVEL RIDES ON THE HEADING FORM ONLY, and `level` rather than `heading_level` because the
  // wire form has always named the field for what it is on THIS object ({heading: ...} for a row
  // whose column is `text`). A non-heading sends none: app.py's _step_parts stores 1 on every
  // ordinary step, so a dormant level would be a key the server throws away.
  return x.is_heading
    ? { id, heading: x.text || "", level: stepLevel(x) }
    : { id, text: x.text || "" };
}
