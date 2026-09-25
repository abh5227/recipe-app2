// gen_save_roundtrip.mjs — regenerate tests/fixtures/save-roundtrip.json.
//
// Captures what the REAL client builders produce for every row shape the save has to survive, so
// the Python suite asserts against the client's own output rather than a hand-written literal.
// That is the gap previews/save-path-scoping.md found: 20-plus PUT tests, every payload a literal,
// none of them the shape the editor actually sends.
//
//   node scripts/gen_save_roundtrip.mjs tests/fixtures/save-roundtrip.json
import { ingToPayload, stepToPayload } from "../static/save-payload.js";
import fs from "node:fs";

const ROWS = [
  { shape: "heading",
    row: { position: 0, is_heading: 1, qty: null, quantity: null, unit: null, ingredient_id: null,
           label: null, note: "", raw_text: "FOR THE SAUCE:", grams: null, secondary_measure: null,
           catalog_id: null, link_confidence: null, link_rule: null, link_matched: null } },

  { shape: "unlinked with a label, raw_text longer (the imported shape)",
    row: { position: 1, is_heading: 0, qty: "25 g", quantity: "25", unit: "g", ingredient_id: null,
           label: "guajillo chillies, dried", note: null,
           raw_text: "25 g (0.9 oz) guajillo chillies, dried", grams: 25.0, secondary_measure: null,
           catalog_id: "en:guajillo-chili", link_confidence: "exact", link_rule: "exact",
           link_matched: "guajillo chili" } },

  { shape: "unlinked with a NULL label (the Paprika shape)",
    row: { position: 2, is_heading: 0, qty: "2 tbsp", quantity: "2", unit: "tbsp", ingredient_id: null,
           label: null, note: null, raw_text: "extra virgin olive oil", grams: null,
           secondary_measure: null, catalog_id: "Q93165", link_confidence: "exact",
           link_rule: "exact", link_matched: "olive oil" } },

  { shape: "unit the client canonicalizes (teaspoon -> tsp)",
    row: { position: 3, is_heading: 0, qty: "1 teaspoon", quantity: "1", unit: "teaspoon",
           ingredient_id: null, label: null, note: null, raw_text: "kosher salt", grams: 6.0,
           secondary_measure: null, catalog_id: "Q4116639", link_confidence: "exact",
           link_rule: "exact", link_matched: "kosher salt" } },

  { shape: "a note row",
    row: { position: 4, is_heading: 0, qty: "2 tbsp", quantity: "2", unit: "tbsp", ingredient_id: null,
           label: "soy sauce", note: "all-purpose or light",
           raw_text: "2 tbsp soy sauceall-purpose or light", grams: null, secondary_measure: null,
           catalog_id: null, link_confidence: null, link_rule: null, link_matched: null } },

  { shape: "duplicate name, different qty",
    row: { position: 5, is_heading: 0, qty: "3 tbsp", quantity: "3", unit: "tbsp", ingredient_id: null,
           label: null, note: null, raw_text: "water", grams: null, secondary_measure: null,
           catalog_id: "water", link_confidence: "exact", link_rule: "exact", link_matched: "water" } },
  { shape: "duplicate name, different qty (the second)",
    row: { position: 6, is_heading: 0, qty: "2 tbsp", quantity: "2", unit: "tbsp", ingredient_id: null,
           label: null, note: null, raw_text: "water", grams: null, secondary_measure: null,
           catalog_id: "water", link_confidence: "form_strip", link_rule: "form_strip:cold",
           link_matched: "water" } },

  { shape: "duplicate name AND qty (the full key collides)",
    row: { position: 7, is_heading: 0, qty: "1 cup", quantity: "1", unit: "cup", ingredient_id: null,
           label: null, note: null, raw_text: "flour", grams: 120.0, secondary_measure: "1 cup",
           catalog_id: "Q95388739", link_confidence: "exact", link_rule: "exact",
           link_matched: "all purpose flour" } },
  { shape: "duplicate name AND qty (the second)",
    row: { position: 8, is_heading: 0, qty: "1 cup", quantity: "1", unit: "cup", ingredient_id: null,
           label: null, note: null, raw_text: "flour", grams: 120.0, secondary_measure: "1 cup",
           catalog_id: "Q95388739", link_confidence: "exact", link_rule: "exact",
           link_matched: "all purpose flour" } },

  { shape: "linked to a library ingredient",
    row: { position: 9, is_heading: 0, qty: "200 g", quantity: "200", unit: "g",
           ingredient_id: "egg_pasta", label: "egg pasta", note: null,
           raw_text: "200 g fresh egg pasta, cut into ribbons", grams: 200.0,
           secondary_measure: null, catalog_id: "en:egg-pasta", link_confidence: "exact",
           link_rule: "exact", link_matched: "egg pasta" } },

  { shape: "trailing space in the name",
    row: { position: 10, is_heading: 0, qty: "1 tbsp", quantity: "1", unit: "tbsp", ingredient_id: null,
           label: "onion, finely grated ", note: "~1/4 onion",
           raw_text: "1 tbsp onion, finely grated ~1/4 onion", grams: null, secondary_measure: null,
           catalog_id: null, link_confidence: null, link_rule: null, link_matched: null } },
];

const STEPS = [
  { position: 0, is_heading: 1, text: "MAKE THE SAUCE" },
  { position: 1, is_heading: 0, text: "Whisk it." },
  { position: 2, is_heading: 0, text: "Rest.\n\nAIR FRYER OPTION:\nShake off excess." },
];

const out = {
  note: "Captured from static/save-payload.js. Regenerate with scripts/gen_save_roundtrip.mjs.",
  rows: ROWS.map((r) => ({ shape: r.shape, row: r.row, payload: ingToPayload(r.row) })),
  steps: STEPS.map((s) => ({ row: s, payload: stepToPayload(s) })),
};
fs.writeFileSync(process.argv[2] || "tests/fixtures/save-roundtrip.json",
                 JSON.stringify(out, null, 1) + "\n");
console.log(`wrote ${out.rows.length} ingredient shapes and ${out.steps.length} steps`);
