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
import { canonicalizeUnit } from "./scaler.js";

// The name is a .ie-line (soft-wrap only), so a hard newline is the only thing folded away.
const oneLine = (v) => (v || "").replace(/[\r\n]+/g, " ");

export function ingToPayload(x) {
  if (x.is_heading) return { heading: oneLine(x.heading || x.label || x.raw_text) };   // dedicated field, back-compat fallbacks
  // Stage 4 (B): send the STRUCTURED parts — quantity + canonical unit. The server recombines
  // qty = quantity + " " + unit, so qty is omitted. Authority is quantity+unit.
  const quantity = oneLine(x.quantity);
  const unit = canonicalizeUnit(x.unit);
  if (x.ingredient_id) return { quantity, unit, item: x.ingredient_id, label: oneLine(x.label || x.raw_text), note: x.note || "" };
  return { quantity, unit, text: oneLine(x.label || x.raw_text), note: x.note || "" };
}

export function stepToPayload(x) {
  return x.is_heading ? { heading: x.text || "" } : (x.text || "");
}
