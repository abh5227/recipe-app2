"use strict";
// JS unit tests for the pure scaler/converter (static/scaler.js) — the client-side equivalent
// of the pytest suite. Run with `node --test tests/js`. The grams_per_ml input is stubbed
// here (the matcher itself is server-side and pytest-covered); these target the display logic.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const s = require("../../static/scaler.js");

const WATER = 227 / 236.588;   // ~0.9595 g/mL (a KA-matched liquid)
const OLIVE = 50 / 59.147;     // ~0.8454 g/mL (KA olive oil)
const GENERIC = 0.5;           // a stand-in matched density

// ----------------------------------------------------------- formatAmount / scaleQty
test("formatAmount: kitchen fractions (unicode)", () => {
  assert.equal(s.formatAmount(0.25), "¼");
  assert.equal(s.formatAmount(0.5), "½");
  assert.equal(s.formatAmount(0.75), "¾");
  assert.equal(s.formatAmount(1.5), "1½");
});

test("toUnicodeFractions: ascii -> glyphs (mixed, lone, unknown, ~)", () => {
  assert.equal(s.toUnicodeFractions("1 1/2 cups"), "1½ cups");
  assert.equal(s.toUnicodeFractions("1/4 cup"), "¼ cup");
  assert.equal(s.toUnicodeFractions("8 3/4"), "8¾");
  assert.equal(s.toUnicodeFractions("~8 3/4 cups"), "~8¾ cups");  // ~ passes through
  assert.equal(s.toUnicodeFractions("6½ cups"), "6½ cups");       // already unicode -> unchanged
  assert.equal(s.toUnicodeFractions("1/16 tsp"), "1/16 tsp");     // no glyph -> stays ascii
});

test("formatAmount: >= 20 rounds to a whole number", () => {
  assert.equal(s.formatAmount(20), "20");
  assert.equal(s.formatAmount(187.5), "188");
  assert.equal(s.formatAmount(236), "236");
});

test("formatAmount: zero and small wholes", () => {
  assert.equal(s.formatAmount(0), "0");
  assert.equal(s.formatAmount(3), "3");
});

test("scaleQty: scales numbers, keeps units; mixed + unicode + fraction", () => {
  assert.equal(s.scaleQty("2 tbsp", 2), "4 tbsp");
  assert.equal(s.scaleQty("1 1/2 cups", 2), "3 cups");
  assert.equal(s.scaleQty("1½ cups", 2), "3 cups");
  assert.equal(s.scaleQty("1/2 cup", 2), "1 cup");
});

test("scaleQty: ranges scale BOTH ends and collapse N-to-N (unicode)", () => {
  assert.equal(s.scaleQty("1 to 2 tablespoons", 0.5), "½ to 1 tablespoons");    // both ends scale
  assert.equal(s.scaleQty("1 to 2 tablespoons", 2), "2 to 4 tablespoons");
  assert.equal(s.scaleQty("1 to 1 tablespoons", 1), "1 tablespoons");           // degenerate -> single
  assert.equal(s.scaleQty("1 to 1 tbsp", 0.5), "½ tbsp");                       // scales, collapses, unicode
  assert.equal(s.collapseRange("2 – 2 cups"), "2 cups");                        // en-dash
  assert.equal(s.collapseRange("½ to ½ cups"), "½ cups");                       // unicode ends collapse
});

test("scaleQty: no-op guards (x1 / 0 / negative / NaN / undefined / null)", () => {
  assert.equal(s.scaleQty("2 tbsp", 1), "2 tbsp");
  assert.equal(s.scaleQty("2 tbsp", 0), "2 tbsp");
  assert.equal(s.scaleQty("2 tbsp", -1), "2 tbsp");
  assert.equal(s.scaleQty("2 tbsp", NaN), "2 tbsp");
  assert.equal(s.scaleQty("2 tbsp", undefined), "2 tbsp");
  assert.equal(s.scaleQty(null, 2), "");
});

test("scaleQty: non-numeric quantities pass through", () => {
  assert.equal(s.scaleQty("to taste", 2), "to taste");
  assert.equal(s.scaleQty("pinch", 2), "pinch");
});

// ----------------------------------------------------------- Bug A: count logic
test("counts scale to whole numbers, never fractions", () => {
  assert.equal(s.displayQty("2 medium", null, 2, "imperial"), "4 medium");
  assert.equal(s.displayQty("2 medium", null, 1.5, "imperial"), "3 medium");
  const odd = s.displayQty("2 medium", null, 1.1875, "imperial");
  assert.equal(odd, "2 medium");
  assert.ok(!odd.includes("/"), "count must never render a fraction");
});

test("count-nouns round; bare counts scale; min-1 clamp", () => {
  assert.equal(s.displayQty("4 cloves", null, 1.5, "imperial"), "6 cloves");
  assert.equal(s.displayQty("8", null, 2, "imperial"), "16");
  assert.equal(s.displayQty("2 medium", null, 0.1, "imperial"), "1 medium"); // min 1, not 0
});

test("counts round in metric mode too, and pass through at x1", () => {
  assert.equal(s.displayQty("2 medium", null, 1.5, "metric"), "3 medium");
  assert.equal(s.displayQty("2 medium", null, 1, "imperial"), "2 medium");
});

// ----------------------------------------------------------- Bug B: compound logic
test("same-unit '+'-compound combines before converting", () => {
  assert.deepEqual(s.parseAmount("3 + 2 tbsp"), { value: 5, unit: "tbsp" });
  assert.equal(s.displayQty("3 + 2 tbsp", OLIVE, 1, "metric"), "~63 g"); // 5 tbsp combined
});

test("mixed-unit compound declines (no malformed sum)", () => {
  assert.equal(s.parseAmount("1 cup + 2 tbsp"), null);
  assert.equal(
    s.displayQty("1 cup + 2 tbsp", GENERIC, 1, "metric"),
    s.scaleQty("1 cup + 2 tbsp", 1) // declines -> scaled original, never "X + Y g"
  );
});

// ----------------------------------------------------------- smart-Metric threshold
test("<= 2 tbsp keeps the measuring-spoon unit", () => {
  assert.equal(s.displayQty("1 tsp", GENERIC, 1, "metric"), "1 tsp");
  assert.equal(s.displayQty("2 tsp", GENERIC, 1, "metric"), "2 tsp");
});

test("exactly 2 tbsp stays tbsp (boundary)", () => {
  assert.equal(s.displayQty("2 tbsp", GENERIC, 1, "metric"), "2 tbsp");
});

test("> 2 tbsp + KA match -> grams with ~", () => {
  const out = s.displayQty("1 cup", GENERIC, 1, "metric");
  assert.ok(out.startsWith("~") && out.endsWith(" g"), out);
  assert.equal(out, "~118 g");
});

test("KA-matched liquid > 2 tbsp -> grams", () => {
  assert.equal(s.displayQty("½ cup", WATER, 1, "metric"), "~114 g");
  assert.equal(s.displayQty("½ cup", WATER, 2, "metric"), "~227 g");
});

test("unmatched > 2 tbsp keeps its unit (declines)", () => {
  assert.equal(s.displayQty("3 tbsp", null, 1, "metric"), "3 tbsp");
  assert.equal(s.displayQty("3 tbsp", null, 2, "metric"), "6 tbsp");
});

test("imperial oz/lb -> grams by fixed factor (no ~)", () => {
  assert.equal(s.displayQty("1 lb", null, 1, "metric"), "454 g");
});

// ----------------------------------------------------------- pass-through
test("already-metric (g / mL) passes through, scaled", () => {
  assert.equal(s.displayQty("450 g", 0.5, 1, "metric"), "450 g");
  assert.equal(s.displayQty("450 g", 0.5, 2, "metric"), "900 g");
  assert.equal(s.displayQty("375 mL", null, 1, "metric"), "375 mL");
});

test("dual-unit passes through (scaled, never converted)", () => {
  assert.equal(s.displayQty("2 lb / 1 kg", null, 1, "metric"), "2 lb / 1 kg");
  assert.equal(s.displayQty("2 lb / 1 kg", null, 2, "metric"), "4 lb / 2 kg");
});

test("imperial mode is plain scaleQty (no conversion; no pluralization)", () => {
  // scaleQty multiplies the number and leaves words alone — "1 cup" -> "2 cup", NOT "2 cups".
  // (Pluralization is a known cosmetic gap, tracked in ROADMAP.)
  assert.equal(s.displayQty("1 cup", WATER, 2, "imperial"), "2 cup");
});

test("empty / to-taste quantities", () => {
  assert.equal(s.displayQty("", null, 2, "metric"), "");
  assert.equal(s.displayQty("to taste", null, 2, "metric"), "to taste");
});

// ----------------------------------------------------------- Stage C: ledger formatting
test("formatAmount: humane snap marks approximate with ~ (unicode)", () => {
  assert.equal(s.formatAmount(8.81), "~8¾");   // false-precise decimal -> nearest kitchen fraction
  assert.equal(s.formatAmount(8.75), "8¾");    // already clean -> no ~
  assert.equal(s.formatAmount(2.5), "2½");
});

test("group: thousands separators", () => {
  assert.equal(s.group(2820), "2,820");
  assert.equal(s.group(118), "118");
  assert.equal(s.formatAmount(2820), "2,820");
});

test("abbrevUnits: canonical unit forms (recognized units only)", () => {
  assert.equal(s.abbrevUnits("1 1/2 tablespoons"), "1 1/2 tbsp");
  assert.equal(s.abbrevUnits("2 teaspoons"), "2 tsp");
  assert.equal(s.abbrevUnits("250 millilitres"), "250 ml");
  assert.equal(s.abbrevUnits("140 grams"), "140 g");
  assert.equal(s.abbrevUnits("8 ounces"), "8 oz");
  assert.equal(s.abbrevUnits("1 pound"), "1 lb");
  assert.equal(s.abbrevUnits("1 cup"), "1 cup");          // already short — unchanged
  assert.equal(s.abbrevUnits("1 can"), "1 can");          // not a unit — unchanged
});

test("amountText: scaled volume in canonical units, unicode; counts + dual", () => {
  assert.equal(s.amountText("1 1/2 tablespoons", 1), "1½ tbsp");   // stored ascii -> unicode + abbrev
  assert.equal(s.amountText("6½ tablespoons", 1), "6½ tbsp");      // stored unicode -> stays unicode
  assert.equal(s.amountText("2 cups", 2), "4 cups");
  assert.equal(s.amountText("140 grams", 1), "140 g");
  assert.equal(s.amountText("1 can", 2), "2 can");             // count
  assert.equal(s.amountText("2 lb / 1 kg", 2), "4 lb / 2 kg"); // dual passes through scaled
  assert.equal(s.amountText("", 2), "");
});

test("weightText: gram estimate for volume + density + > 2 tbsp, else ''", () => {
  assert.equal(s.weightText("1 cup", GENERIC, 1), "~118 g");
  assert.equal(s.weightText("½ cup", WATER, 2), "~227 g");
  assert.equal(s.weightText("2 tbsp", GENERIC, 1), "");   // <= 2 tbsp: spoon zone, no grams
  assert.equal(s.weightText("140 grams", 0.5, 1), "");    // already a weight
  assert.equal(s.weightText("1 cup", null, 1), "");       // no density
  assert.equal(s.weightText("1 can", GENERIC, 1), "");    // not a volume
});
