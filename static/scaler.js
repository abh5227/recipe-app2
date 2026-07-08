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

  // The reverse, for DISPLAY: ascii fractions -> unicode glyphs, so every amount looks the same
  // (cookbook style) whether it came from storage ("1 1/2") or the scaler ("8 3/4"). "1 1/2" -> "1½",
  // "3/4" -> "¾"; the "~" prefix and unknown fractions (e.g. "1/16", no glyph) pass through.
  const ASCII_TO_GLYPH = {};
  for (const g in UNICODE_FRACTIONS) ASCII_TO_GLYPH[UNICODE_FRACTIONS[g]] = g;
  function toUnicodeFractions(s) {
    return String(s).replace(/(\d+)\s+(\d+\/\d+)|(\d+\/\d+)/g, (m, w, wf, lone) => {
      if (w !== undefined) { const glyph = ASCII_TO_GLYPH[wf]; return glyph ? w + glyph : m; }
      return ASCII_TO_GLYPH[lone] || m;
    });
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
  // Group an integer with thousands separators: 2820 -> "2,820".
  function group(n) { return Math.round(n).toLocaleString("en-US"); }

  function formatAmount(n) {
    if (!isFinite(n)) return String(n);
    if (n === 0) return "0";
    // Large amounts (metric mL/g, big batches) read better as a rounded whole number, with
    // thousands separators: 187.5 -> "188", 2820 -> "2,820". Small cooking amounts keep fractions.
    if (n >= 20) return group(n);
    const whole = Math.floor(n + 1e-9);
    const frac = n - whole;
    let best = NICE_FRACTIONS[0], bestErr = Infinity;
    for (const cand of NICE_FRACTIONS) {
      const err = Math.abs(frac - cand[0]);
      if (err < bestErr) { bestErr = err; best = cand; }
    }
    // Always snap to the nearest kitchen fraction — never a false-precise decimal like "8.81".
    // When the snap moved the value more than a hair, mark it approximate with a leading "~"
    // (so "8.81" -> "~8 3/4"); a value that was already clean (err ~0) gets no "~".
    const w = whole + (best[0] === 1 ? 1 : 0);   // e.g. 1.97 rounds up to the next whole
    const label = best[0] === 1 ? "" : best[1];
    let text;
    if (label && w > 0) text = w + " " + label;
    else if (label) text = label;
    else if (w > 0) text = String(w);
    else text = String(Math.round(n * 1000) / 1000); // positive but rounds toward 0 — a small decimal
    return (bestErr > 0.02 ? "~" : "") + toUnicodeFractions(text);
  }

  // Matches one amount token, longest form first (mixed > fraction > int/decimal).
  const AMOUNT_TOKEN = /\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:\.\d+)?/g;

  // Collapse a degenerate range whose two ends render EQUAL: "1 to 1 tbsp" -> "1 tbsp",
  // "2 – 2 cups" -> "2 cups". A real range ("1 to 2") is untouched. (Step ranges scale both
  // ends together now, so this mainly catches genuinely-equal ends / degenerate sources.)
  function collapseRange(s) {
    // collapse "N to N" (identical ends) -> "N"; N may be whole, ascii fraction, or unicode glyph
    const G = "¼½¾⅓⅔⅛⅜⅝⅞⅙⅚";
    const TOK = `\\d+\\s+\\d+\\/\\d+|\\d+\\/\\d+|\\d+\\s*[${G}]|[${G}]|\\d+(?:\\.\\d+)?`;
    return String(s).replace(new RegExp(`(${TOK})\\s*(?:to|[-–—])\\s*(${TOK})(?=\\s|$)`, "g"),
      (m, a, b) => (a === b ? a : m));
  }

  // Scale a quantity string by `factor`; unchanged at factor 1 or a 0/negative/NaN factor
  // (but a degenerate "N to N" range still collapses to "N"). factor is passed in — in the
  // browser it's view.scale; in tests it's explicit.
  function scaleQty(qty, factor) {
    if (qty == null) return "";
    if (factor === 1 || !(factor > 0)) return collapseRange(qty);   // x1 / invalid: still collapse N-to-N
    let found = false;
    const scaled = normalizeFractions(qty).replace(AMOUNT_TOKEN, (token) => {
      const n = tokenToNumber(token);
      if (!isFinite(n)) return token;
      found = true;
      return formatAmount(n * factor);
    });
    return collapseRange(found ? scaled : qty);
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
    let found = false, clampedUp = false;
    const out = normalizeFractions(String(qty)).replace(AMOUNT_TOKEN, (token) => {
      const n = tokenToNumber(token);
      if (!isFinite(n)) return token;
      found = true;
      const scaled = n * factor;
      if (scaled > 0 && scaled < 1) clampedUp = true;   // true amount < 1, shown as a clamped-up 1
      return String(Math.max(1, Math.round(scaled)));
    });
    if (!found) return qty;
    return clampedUp ? "~" + out : out;   // "~1 egg" — honest that the true amount is less than 1
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

  // ---- Stage-C ledger: amount column + weight column (no units toggle — both are shown) ----

  // Standardize recognized measuring units to their canonical short form at display
  // ("tablespoons" -> "tbsp"); descriptors and unrecognized words are left as authored.
  const UNIT_ABBREV = [
    [/\bfluid\s+ounces?\b/gi, "fl oz"],
    [/\btablespoons?\b/gi, "tbsp"],
    [/\bteaspoons?\b/gi, "tsp"],
    [/\bkilograms?\b/gi, "kg"],
    [/\bmilli(?:lit(?:re|er)s?)\b/gi, "ml"],
    [/\bounces?\b/gi, "oz"],
    [/\bpounds?\b/gi, "lb"],
    [/\bgrams?\b/gi, "g"],
  ];
  function abbrevUnits(s) {
    for (const [re, a] of UNIT_ABBREV) s = String(s).replace(re, a);
    return s;
  }

  // Canonicalize a bare UNIT to its short lowercase form for the editor (reuses UNIT_ABBREV):
  // "tablespoons" -> "tbsp", "Tbsp" -> "tbsp", "Cup" -> "cup" (cup/cups left as-is, already short),
  // count-nouns/textual left as-is ("cloves" -> "cloves"), "" -> "". Editor-only — reading already
  // abbreviates at display, and the scaler maps both long and short forms, so storage self-heals.
  function canonicalizeUnit(u) {
    return abbrevUnits(String(u == null ? "" : u)).trim().toLowerCase();
  }

  // The ledger AMOUNT column: the authored quantity, scaled, in canonical units (the volume the
  // recipe was written in). Counts round to whole; dual-unit ("2 lb / 1 kg") passes through scaled.
  function amountText(qty, factor) {
    if (qty == null || String(qty).trim() === "") return "";
    const f = factor > 0 ? factor : 1;
    let t;
    if (isCountAmount(qty)) t = scaleCount(qty, f);
    else if (String(qty).includes(" / ")) t = scaleQty(qty, f);
    else t = abbrevUnits(scaleQty(qty, f));
    return toUnicodeFractions(t);   // stored ascii ("1 1/2") -> unicode, so all amounts match
  }

  // The ledger WEIGHT column: the estimated gram weight of a VOLUME amount, for ingredients the
  // weight chart knows (gramsPerMl set) and above the 2-tbsp spoon threshold — else "" (empty for
  // spoon-sized amounts, weights/counts, already-metric amounts, and unmatched names).
  function weightText(qty, gramsPerMl, factor) {
    if (gramsPerMl == null) return "";
    const parsed = parseAmount(normalizeFractions(String(qty)));
    if (!parsed) return "";
    const mlPer = UNIT_TO_ML[parsed.unit];
    if (!mlPer) return "";                               // not a volume (oz/lb/g/kg/ml/count)
    const ml = parsed.value * (factor > 0 ? factor : 1) * mlPer;
    if (ml <= SPOON_MAX_ML + 1e-9) return "";            // <= 2 tbsp stays a measuring spoon
    return "~" + group(Math.max(1, Math.round(ml * gramsPerMl))) + " g";
  }

  return {
    UNICODE_FRACTIONS, normalizeFractions, tokenToNumber, NICE_FRACTIONS, formatAmount, group,
    AMOUNT_TOKEN, scaleQty, collapseRange, UNIT_TO_ML, UNIT_TO_G, MEASURE_UNIT_RE, MEASURE_UNIT_RE_G,
    SPOON_MAX_ML, isCountAmount, scaleCount, parseAmount, toMetric, displayQty,
    abbrevUnits, canonicalizeUnit, amountText, weightText, toUnicodeFractions,
  };
});
