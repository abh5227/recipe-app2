"use strict";
// What a cook SEES in the ingredient list, at ½x, 1x and 2x. Round B revision 2.
//
// ⚠️ THIS IS ONE LEVEL CLOSER TO THE PAGE THAN EVERY TEST BEFORE IT, AND THAT IS ITS WHOLE POINT.
//    Revision 1's tests checked amountText and passed, and Andy's click-through still saw "about ½
//    cup per person" doubling at 2x. The tests were not checking what the page shows. These render
//    ledger-row.js, which is the HTML app.js inserts for every ingredient row, over the rows AS THE
//    REHEARSAL STORED THEM, and compare the visible text.
//    (Andy's tab was running a8ba985's bundle, from before revision 1, which the :8002 log shows:
//    it never fetched the new one after the restart. The current render could not do it, and this
//    is what now holds that.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { ledgerCellsAt, readNoteAt, amountSubLinesAt, editedAmountCellAt } from "../../static/ledger-row.js";
import { annotationIndex } from "../../static/annotation-index.js";
import { scaleQty, scaleCount, toMetric, amountText } from "../../static/scaler.js";
import { stepSpanTexts, noteSpanTexts, editedAmountParts } from "../../static/annotation-amount.js";

const FACTORS = [0.5, 1, 2];

// The text a reader sees: tags gone, entities decoded, one string per line of the cell.
function seen(html) {
  return [...html.matchAll(/<span class="([^"]+)"[^>]*>([^<]*)<\/span>/g)]
    .map(([, cls, text]) => ({ cls: cls.split(" ")[0], text: text
      .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&amp;/g, "&") }));
}
const amountLines = (row, f) => seen(ledgerCellsAt(row, f)).map((s) => s.text);
const noteLine = (row, f) => (seen(readNoteAt(row, f))[0] || { text: "" }).text;

// ---- R3: the three per-person rows, exactly as the rehearsal stores them ----------------------- //
const PER_PERSON = [
  { id: 5163, recipe: "quick-easy-hainanese-chicken-rice-khao-mun-gai",
    qty: "about 1/2 cup per person", secondary_measure: null, grams_per_ml: null,
    shown: "about ½ cup per person" },
  { id: 4639, recipe: "minestrone-soup", qty: "about 1/4 per person", secondary_measure: null,
    grams_per_ml: null, shown: "about ¼ per person" },
  { id: 4876, recipe: "panang-curry", qty: "3 leaves per serving", secondary_measure: null,
    grams_per_ml: null, shown: "3 leaves per serving" },
];

for (const row of PER_PERSON) {
  test(`${row.recipe} ${row.id}: the per-person amount reads the same at every factor`, () => {
    for (const f of FACTORS) assert.deepEqual(amountLines(row, f), [row.shown], `at ${f}x`);
  });
}

test("a per-person amount with a density keeps its estimate still too", () => {
  // The chart knows chicken stock in another recipe; the estimate is grams PER PERSON.
  const row = { qty: "about 1/2 cup per person", grams_per_ml: 1.0, secondary_measure: null };
  const at = FACTORS.map((f) => amountLines(row, f));
  assert.deepEqual(at[0], at[1]);
  assert.deepEqual(at[2], at[1]);
});

test("no scaler a caller can reach multiplies a per-person amount or a size", () => {
  for (const q of ["about 1/2 cup per person", "3 leaves per serving", "1-inch knob",
                   "3-inch section"]) {
    for (const f of FACTORS) {
      assert.equal(scaleQty(q, f), q, `scaleQty ${q} at ${f}x`);
      assert.equal(scaleCount(q, f), q, `scaleCount ${q} at ${f}x`);
    }
  }
  // The method text's spans and the metric path reach the bottom without passing amountText.
  assert.equal(stepSpanTexts([{ t: "scale", text: "about 1/2 cup per person" }], 2)[0].text,
               "about ½ cup per person");
  assert.equal(toMetric("about 1/2 cup per person", 1.0, 2), toMetric("about 1/2 cup per person", 1.0, 1));
});

// ---- R1: a sized piece scales its count and never its size ------------------------------------- //
test("a doubled knob is two knobs of one inch, never one of two", () => {
  const row = { qty: "1-inch knob", secondary_measure: null, grams_per_ml: null };
  assert.deepEqual(amountLines(row, 2), ["2 × 1-inch knobs"]);
  assert.deepEqual(amountLines(row, 1), ["1-inch knob"]);
  assert.deepEqual(amountLines(row, 0.5), ["½ × 1-inch knob"]);
  for (const f of FACTORS) assert.ok(!/\b(?:2|½)-inch/.test(amountLines(row, f).join(" ")));
});

// ---- R2 (revision 2): the "or" lines are lines of their own, and they scale --------------------- //
test("smashed-cucumber-salad: 500 g, then 1 lb / 4 medium / or 2 long, each on its own line", () => {
  const row = { qty: "500 g", secondary_measure: "1 lb / 4 medium / or 2 long", grams_per_ml: null };
  assert.deepEqual(amountLines(row, 1), ["500 g", "1 lb", "4 medium", "or 2 long"]);
  assert.deepEqual(amountLines(row, 2), ["1,000 g", "2 lb", "8 medium", "or 4 long"]);
  assert.deepEqual(seen(ledgerCellsAt(row, 1)).map((s) => s.cls), ["qty", "qty2", "qty2", "qty2"]);
});

test("an or-line of the same food scales like the amount above it", () => {
  const breast = { qty: "1 large", secondary_measure: "or 2 small", grams_per_ml: null };
  assert.deepEqual(amountLines(breast, 2), ["2 large", "or 4 small"]);
  const cucumber = { qty: "1", secondary_measure: "or ½ English", grams_per_ml: null };
  assert.deepEqual(amountLines(cucumber, 2), ["2", "or 1 English"]);
});

// ---- Part 4: a substitution note's amounts scale, and no other note moves ---------------------- //
const TAO_JIEW = {
  qty: "3 Tbsp", secondary_measure: null, grams_per_ml: null,
  note: "or 2 tablespoons Korean doenjang + 1 tablespoon water",
  // what stepscale.note_spans sends for that note, verbatim
  note_spans: [{ t: "plain", text: "or " }, { t: "scale", text: "2 tablespoons" },
               { t: "plain", text: " Korean doenjang + " }, { t: "scale", text: "1 tablespoon" },
               { t: "plain", text: " water" }],
};

test("the Tao Jiew note reads Andy's words at 2x and the stored words at 1x", () => {
  assert.equal(noteLine(TAO_JIEW, 2), "or 4 tablespoons Korean doenjang + 2 tablespoons water");
  assert.equal(noteLine(TAO_JIEW, 1), TAO_JIEW.note);
  assert.equal(noteLine(TAO_JIEW, 0.5), "or 1 tablespoon Korean doenjang + ½ tablespoon water");
});

test("the note, the ledger and the method agree at 2x", () => {
  // One amount, three renderings: the ledger abbreviates, the method abbreviates, the note keeps
  // the author's word. The QUANTITY is what has to agree, and the per-person one agrees by staying.
  const num = (t) => t.match(/[\d½¼¾⅓⅔⅛]+/)[0];
  for (const q of ["2 tablespoons", "1 tablespoon", "1/2 tsp", "1 ½ cups", "about 1/2 cup per person"]) {
    const ledger = amountText(q, 2);
    const method = stepSpanTexts([{ t: "scale", text: q }], 2)[0].text;
    const note = noteSpanTexts([{ t: "scale", text: q }], 2)[0].text;
    assert.equal(num(ledger), num(method), q);
    assert.equal(num(note), num(ledger), q);
  }
});

for (const note of ["(½ pound each)", "about ½ cup per person", "use 2 tablespoons if dry",
                    "plus more for dusting", "sifted"]) {
  test(`a note the server sends no spans for prints as stored at every factor: ${note}`, () => {
    const row = { qty: "1 cup", secondary_measure: null, grams_per_ml: null, note };
    for (const f of FACTORS) assert.equal(noteLine(row, f), note, `at ${f}x`);
  });
}

test("a size or a per-person figure inside a substitution note never scales", () => {
  const row = { qty: "1", note: "or about ½ cup per person",
                note_spans: [{ t: "plain", text: "or about " }, { t: "scale", text: "½ cup per person" }] };
  assert.equal(noteLine(row, 2), "or about ½ cup per person");
  const ginger = { qty: "1", note: "or 1-inch piece",
                   note_spans: [{ t: "plain", text: "or " }, { t: "scale", text: "1-inch piece" }] };
  assert.equal(noteLine(ginger, 2), "or 2 × 1-inch pieces");
});

// ---- What the revision 2 review found ---------------------------------------------------------- //
test("beef-bulgogi: a tbs in a note scales as a tablespoon, not a count", () => {
  // MUST-FIX: "tbs" was not a unit on the client, so it read as a count and rounded to whole numbers.
  const row = { qty: "2 tbs", note: "or 1 tbs of brown sugar and 1½ tbs rice syrup",
    note_spans: [{ t: "plain", text: "or " }, { t: "scale", text: "1 tbs" },
                 { t: "plain", text: " of brown sugar and " }, { t: "scale", text: "1½ tbs" },
                 { t: "plain", text: " rice syrup" }] };
  assert.equal(noteLine(row, 0.5), "or ½ tbs of brown sugar and ¾ tbs rice syrup");
  assert.equal(noteLine(row, 3), "or 3 tbs of brown sugar and 4½ tbs rice syrup");
});

test("'per each serving' is per serving", () => {
  for (const f of [0.5, 2, 3]) {
    assert.equal(amountText("1 tablespoon per each serving", f), amountText("1 tablespoon per each serving", 1));
  }
});

// ---- Round B revision 4, A1: the second amount's "your changes" mark --------------------------- //
// Andy: an edit to only the second amount gets the same mark as an edit to the first amount. The
// entries come from the server (tests/test_second_amount_mark.py pins when one exists). These read
// the cell the page inserts for a row carrying one, the way plainRow builds it.
const TOFU = { id: 11, qty: "1 block", secondary_measure: "400 g", grams_per_ml: null };
const secondEntry = (from, to, row_id = 11) =>
  ({ kind: "ingredient", type: "modified", field: "second_amount", from, to, row_id });
// The cell plainRow inserts for this row, given the recipe's entries.
function cellFor(row, anns, f) {
  const slot = annotationIndex(anns).ing.get(row.id);
  const amt = slot && slot.amount, second = slot && slot.second_amount;
  return (amt || second) ? editedAmountCellAt(amt, second, row, f) : ledgerCellsAt(row, f);
}

test("an edit to only the second amount is struck and inked, and the first amount is not", () => {
  const html = cellFor(TOFU, [secondEntry("14 oz", "400 g")], 1);
  assert.deepEqual(seen(html), [{ cls: "qty", text: "1 block" }, { cls: "was", text: "14 oz" },
                                { cls: "fix", text: "400 g" }]);
  assert.match(html, /<span class="qty2"><span class="was">14 oz<\/span><\/span>/,
               "the struck line keeps the sub-line's print look");
  assert.match(html, /<\/span><span class="fix">400 g<\/span><\/span>$/,
               "the ink is a line of the cell itself, outside .qty2");
});

test("putting it back takes the mark away: no entry, no strike, no ink", () => {
  const row = { ...TOFU, secondary_measure: "14 oz" };
  const html = cellFor(row, [], 1);
  assert.equal(html, ledgerCellsAt(row, 1));
  assert.doesNotMatch(html, /class="(was|fix)"/);
});

test("both sides of a second-amount mark scale with the rows around it", () => {
  const row = { id: 2, qty: "2 cups", secondary_measure: "1 lb", grams_per_ml: null };
  const anns = [secondEntry("8 oz", "1 lb", 2)];
  assert.deepEqual(seen(cellFor(row, anns, 2)).map((s) => s.text), ["4 cups", "16 oz", "2 lb"]);
  assert.deepEqual(seen(cellFor(row, anns, 0.5)).map((s) => s.text), ["1 cup", "4 oz", "½ lb"]);
});

test("a two-line second amount strikes each old line and inks each new one", () => {
  const row = { id: 5, qty: "1 cup", secondary_measure: "8 ounces / 227 grams", grams_per_ml: null };
  const lines = seen(cellFor(row, [secondEntry("8 ounces / 225 grams", "8 ounces / 227 grams", 5)], 1));
  assert.deepEqual(lines.map((s) => `${s.cls} ${s.text}`),
                   ["qty 1 cup", "was 8 oz", "was 225 g", "fix 8 oz", "fix 227 g"]);
});

test("a cleared second amount is struck, and the row gets the estimate an unedited row would", () => {
  const row = { id: 6, qty: "1 cup", secondary_measure: null, grams_per_ml: 0.5 };
  const lines = seen(cellFor(row, [secondEntry("120 g", "", 6)], 1));
  assert.deepEqual(lines.map((s) => `${s.cls} ${s.text}`), ["qty 1 cup", "was 120 g", "weight ~118 g"]);
  assert.equal(lines.filter((s) => s.cls === "fix").length, 0);
});

test("an amount-only edit renders byte for byte as it did before revision 4", () => {
  // The markup app.js's editedAmountCell built until revision 4, written out here.
  const row = { id: 8, qty: "4", secondary_measure: "1 lb", grams_per_ml: null };
  for (const f of FACTORS) {
    const p = editedAmountParts("2", "4", row.grams_per_ml, f);
    const before = `<span class="amount-cell"><span class="qty"><span class="was">${p.was}</span>` +
      `<span class="fix">${p.fix}</span></span>${amountSubLinesAt(row, f)}</span>`;
    assert.equal(editedAmountCellAt({ from: "2", to: "4" }, undefined, row, f), before, `at ${f}x`);
  }
});

test("an amount and a second amount edited together each get the mark", () => {
  const row = { id: 12, qty: "2 blocks", secondary_measure: "800 g", grams_per_ml: null };
  const anns = [{ kind: "ingredient", type: "modified", field: "amount", from: "1 block", to: "2 blocks",
                  row_id: 12 }, secondEntry("14 oz", "800 g", 12)];
  assert.deepEqual(seen(cellFor(row, anns, 1)).map((s) => `${s.cls} ${s.text}`),
                   ["was 1 block", "fix 2 blocks", "was 14 oz", "fix 800 g"]);
});
