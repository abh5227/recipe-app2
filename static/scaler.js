// scaler.js — the pure quantity scaler / unit converter (Phase 1a-1d + smart-Metric).
//
// This is the SAME code the browser uses and the Node test suite imports: no DOM, no globals,
// every input passed explicitly. It's loaded as a plain <script> before app.js (the wrapper
// attaches its exports to globalThis, so app.js keeps calling these as globals exactly as
// before), and `require()`d by tests under tests/js/. Keep it pure — anything touching the
// DOM or the `view` state belongs in app.js, which passes view.scale / view.units in.
//
// The volume->mL factors below MUST stay in sync with weights.py VOLUME_TO_ML (cross-language;
// tests/js/factor-sync.test.js guards this).
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api; // Node: require()
  else Object.assign(root, api);                                             // browser: globals
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅙": "1/6", "⅚": "5/6",
  };

  // Turn "1½" into "1 1/2" and "½" into "1/2", then tidy whitespace.
  function normalizeFractions(s) {
    return s
      .replace(/[¼½¾⅓⅔⅛⅜⅝⅞⅙⅚]/g,
               (m) => " " + UNICODE_FRACTIONS[m] + " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // Parse one numeric token ("4", "1.5", "1/2", "1 1/2") into a Number, or NaN.
  function tokenToNumber(token) {
    token = token.trim();
    if (/^\d+(\.\d+)?$/.test(token)) return parseFloat(token);
    let m = token.match(/^(\d+)\s+(\d+)\/(\d+)$/);          // mixed, e.g. "1 1/2"
    if (m) { const d = parseInt(m[3], 10); return d ? parseInt(m[1], 10) + parseInt(m[2], 10) / d : NaN; }
    m = token.match(/^(\d+)\/(\d+)$/);                       // fraction, e.g. "1/2"
    if (m) { const d = parseInt(m[2], 10); return d ? parseInt(m[1], 10) / d : NaN; }
    return NaN;
  }

  // Render a number back as a readable amount, preferring common kitchen fractions.
  const NICE_FRACTIONS = [
    [0, ""], [1 / 16, "1/16"], [1 / 8, "1/8"], [1 / 6, "1/6"], [1 / 4, "1/4"],
    [1 / 3, "1/3"], [3 / 8, "3/8"], [1 / 2, "1/2"], [5 / 8, "5/8"], [2 / 3, "2/3"],
    [3 / 4, "3/4"], [7 / 8, "7/8"], [1, ""],
  ];
  function formatAmount(n) {
    if (!isFinite(n)) return String(n);
    if (n === 0) return "0";
    // Large amounts (metric mL/g, big batches) read better as a rounded whole number than as
    // a mixed fraction or a decimal: 187.5 -> "188", not "187 1/2" or "187.5". Small cooking
    // amounts keep their fractions.
    if (n >= 20) return String(Math.round(n));
    const whole = Math.floor(n + 1e-9);
    const frac = n - whole;
    let best = NICE_FRACTIONS[0], bestErr = Infinity;
    for (const cand of NICE_FRACTIONS) {
      const err = Math.abs(frac - cand[0]);
      if (err < bestErr) { bestErr = err; best = cand; }
    }
    if (bestErr < 0.04) {
      const w = whole + (best[0] === 1 ? 1 : 0);   // e.g. 1.97 rounds up to the next whole
      const label = best[0] === 1 ? "" : best[1];
      if (label && w > 0) return w + " " + label;
      if (label) return label;
      if (w > 0) return String(w);
      // positive but rounded toward zero — show a small decimal, never a misleading "0"
      return String(Math.round(n * 1000) / 1000);
    }
    return String(Math.round(n * 100) / 100);       // otherwise a trimmed decimal
  }

  // Matches one amount token, longest form first (mixed > fraction > int/decimal).
  const AMOUNT_TOKEN = /\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:\.\d+)?/g;

  // Scale a quantity string by `factor`; unchanged at factor 1 or a 0/negative/NaN factor.
  // (factor is passed in — in the browser it's view.scale; in tests it's explicit.)
  function scaleQty(qty, factor) {
    if (qty == null) return "";
    if (factor === 1 || !(factor > 0)) return qty;   // x1, or 0/negative/NaN: leave as-is
    let found = false;
    const scaled = normalizeFractions(qty).replace(AMOUNT_TOKEN, (token) => {
      const n = tokenToNumber(token);
      if (!isFinite(n)) return token;
      found = true;
      return formatAmount(n * factor);
    });
    return found ? scaled : qty;
  }

  // Metric/imperial conversion tables (Phase 1b). KEEP IN SYNC with weights.py VOLUME_TO_ML.
  const UNIT_TO_ML = {
    tsp: 4.92892, teaspoon: 4.92892, teaspoons: 4.92892,
    tbsp: 14.7868, tablespoon: 14.7868, tablespoons: 14.7868,
    "fl oz": 29.5735, "fluid oz": 29.5735, "fluid ounce": 29.5735, "fluid ounces": 29.5735,
    cup: 236.588, cups: 236.588,
  };
  const UNIT_TO_G = {
    oz: 28.3495, ounce: 28.3495, ounces: 28.3495,
    lb: 453.592, lbs: 453.592, pound: 453.592, pounds: 453.592,
  };
  // All measuring units (volume + weight, imperial + metric) — used to tell a real measure
  // from a bare count/descriptor. Excludes bare "l"/"L" (it would match "small", "oil").
  const MEASURE_UNIT_RE = /\b(fl\s+oz|fluid\s+ounces?|cups?|tbsp|tablespoons?|tsp|teaspoons?|ounces?|oz|lbs?|pounds?|kilograms?|kg|grams?|g|millilit(?:er|re)s?|ml|lit(?:er|re)s?)\b/i;
  const MEASURE_UNIT_RE_G = new RegExp(MEASURE_UNIT_RE.source, "gi");

  // Metric threshold: amounts at or below 2 tbsp stay in measuring spoons (tsp/tbsp).
  const SPOON_MAX_ML = 2 * UNIT_TO_ML.tbsp;

  // A "count" amount has a number but no measuring unit — a bare count ("8"), a size descriptor
  // ("2 medium"), or a count-noun ("4 cloves"). A count is not a measure, so it scales to a
  // whole number rather than a fraction (no "2 3/8 medium").
  function isCountAmount(qty) {
    const s = normalizeFractions(String(qty));
    if (s.includes(" / ")) return false;             // dual-unit handled separately
    if (!/\d/.test(s)) return false;                 // no number (pinch, to taste)
    return !MEASURE_UNIT_RE.test(s);
  }

  // Scale a countable amount, rounding to a whole number (min 1). Left as authored at factor 1.
  function scaleCount(qty, factor) {
    if (!(factor > 0) || factor === 1) return qty;
    let found = false;
    const out = normalizeFractions(String(qty)).replace(AMOUNT_TOKEN, (token) => {
      const n = tokenToNumber(token);
      if (!isFinite(n)) return token;
      found = true;
      return String(Math.max(1, Math.round(n * factor)));
    });
    return found ? out : qty;
  }

  // Reduce an amount to a single {value, unit}, combining a same-unit "+"-compound
  // ("3 + 2 tbsp" -> 5 tbsp). Returns null if it can't reduce to one unit (different units or
  // none) — the caller then declines, so we never emit a malformed sum like "53 + 35 mL".
  function parseAmount(normalized) {
    const units = normalized.match(MEASURE_UNIT_RE_G);
    if (!units) return null;
    const unit = units[0].toLowerCase().replace(/\s+/g, " ");
    if (!units.every((u) => u.toLowerCase().replace(/\s+/g, " ") === unit)) return null;
    let sum = 0, found = false;
    normalized.replace(AMOUNT_TOKEN, (tok) => {
      const n = tokenToNumber(tok);
      if (isFinite(n)) { sum += n; found = true; }
      return tok;
    });
    return found ? { value: sum, unit } : null;
  }

  // Smart Metric: each amount picks its own unit.
  //  - <= 2 tbsp           -> keep the measuring-spoon unit (scaled);
  //  - > 2 tbsp + KA match  -> grams (approximate "~"), deferring to the KA table incl. liquids;
  //  - > 2 tbsp, no match   -> keep the original unit (decline);
  //  - oz/lb                -> grams by fixed factor; already-metric/uncombinable -> scaled as-is.
  // `factor` (view.scale) and `gramsPerMl` (server-attached, or null) are passed in.
  function toMetric(qty, gramsPerMl, factor) {
    const parsed = parseAmount(normalizeFractions(String(qty)));
    if (!parsed) return scaleQty(qty, factor);
    const scaledValue = parsed.value * factor;
    const gPer = UNIT_TO_G[parsed.unit];
    if (gPer) return String(Math.max(1, Math.round(scaledValue * gPer))) + " g";   // oz/lb -> g
    const mlPer = UNIT_TO_ML[parsed.unit];
    if (!mlPer) return scaleQty(qty, factor);                  // already metric (g/kg/mL)
    const ml = scaledValue * mlPer;
    if (ml <= SPOON_MAX_ML + 1e-9) return scaleQty(qty, factor); // measuring-spoon zone
    if (gramsPerMl != null) return "~" + Math.max(1, Math.round(ml * gramsPerMl)) + " g";
    return scaleQty(qty, factor);                              // > 2 tbsp, no KA match: decline
  }

  // Full display pipeline: counts round to whole (both systems); Imperial = scaleQty; Metric is
  // the smart per-ingredient rule. Dual-unit ("2 lb / 1 kg") passes through as authored.
  // `factor` (view.scale) and `units` (view.units) are passed by app.js.
  function displayQty(qty, gramsPerMl, factor, units) {
    if (qty == null) return "";
    const f = factor > 0 ? factor : 1;
    if (isCountAmount(qty)) return scaleCount(qty, f);
    if (units !== "metric") return scaleQty(qty, f);
    if (String(qty).includes(" / ")) return scaleQty(qty, f);
    return toMetric(qty, gramsPerMl, f);
  }

  return {
    UNICODE_FRACTIONS, normalizeFractions, tokenToNumber, NICE_FRACTIONS, formatAmount,
    AMOUNT_TOKEN, scaleQty, UNIT_TO_ML, UNIT_TO_G, MEASURE_UNIT_RE, MEASURE_UNIT_RE_G,
    SPOON_MAX_ML, isCountAmount, scaleCount, parseAmount, toMetric, displayQty,
  };
});
