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

// A row the user just added has no id yet. `undefined` and `null` are the same answer here, and
// sending the key always means the server never has to tell "no id" from "the key is missing".
const rowId = (x) => (x && x.id != null ? x.id : null);

// The name is a .ie-line (soft-wrap only), so a hard newline is the only thing folded away.
const oneLine = (v) => (v || "").replace(/[\r\n]+/g, " ");

export function ingToPayload(x) {
  const id = rowId(x);
  if (x.is_heading) return { id, heading: oneLine(x.heading || x.label || x.raw_text) };   // dedicated field, back-compat fallbacks
  // Stage 4 (B): send the STRUCTURED parts — quantity + canonical unit. The server recombines
  // qty = quantity + " " + unit, so qty is omitted. Authority is quantity+unit.
  const quantity = oneLine(x.quantity);
  const unit = canonicalizeUnit(x.unit);
  if (x.ingredient_id) return { id, quantity, unit, item: x.ingredient_id, label: oneLine(x.label || x.raw_text), note: x.note || "" };
  return { id, quantity, unit, text: oneLine(x.label || x.raw_text), note: x.note || "" };
}

// ⚠️ A NON-HEADING STEP USED TO GO BACK AS A BARE STRING, and it is now an object, because a string
// has nowhere to put an id. The server still accepts the string form and always will: the import
// review posts plain text, and a browser holding an old bundle over a deploy posts it too. See
// app.py _step_parts, which reads both forms and is the only place that knows about either.
export function stepToPayload(x) {
  const id = rowId(x);
  return x.is_heading ? { id, heading: x.text || "" } : { id, text: x.text || "" };
}
