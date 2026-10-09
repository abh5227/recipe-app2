// scaler.js — the pure quantity scaler / unit converter (Phase 1a-1d + smart-Metric).
//
// This is the SAME code the browser uses and the Node test suite imports: no DOM, no globals,
// every input passed explicitly. It's an ES module: the browser loads app.js as
// <script type="module"> and app.js imports these names; the tests under tests/js/ import them
// the same way. Keep it pure — anything touching the DOM or the `view` state belongs in app.js,
// which passes view.scale / view.units in.
//
// The volume->mL factors below MUST stay in sync with weights.py VOLUME_TO_ML (cross-language;
// tests/js/factor-sync.test.js guards this).
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
  // ⚠️ THE TWO AMOUNTS THAT NEVER SCALE ARE REFUSED HERE, AT THE BOTTOM, so no caller can scale
  //    them. Revision 1 refused them in amountText, one layer up, and every caller that reached
  //    scaleQty or scaleCount directly (the method spans, toMetric, and the note amounts revision
  //    2 adds) was on its own. Andy's click-through then showed "about ½ cup per person" doubling
  //    at 2x. That page was running a bundle from before revision 1 (the :8002 log shows his tab
  //    never fetched the new one), but the lesson stands: a rule stated one layer up from where
  //    the scaling happens protects only the callers that pass through that layer.
  //    PER_SERVING and PIECE_ANYWHERE are declared further down; both are read at call time.
  function neverScales(qty) {
    const s = String(qty == null ? "" : qty);
    return PER_SERVING.test(s) || PIECE_ANYWHERE.test(s);
  }

  function scaleQty(qty, factor) {
    if (qty == null) return "";
    if (factor === 1 || !(factor > 0) || neverScales(qty)) return collapseRange(qty);   // x1 / invalid / locked: still collapse N-to-N
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
  // ⚠️ "tbs" IS HERE SINCE ROUND B REVISION 2. Without it a "tbs" amount read as a COUNT and
  //    rounded to whole numbers: beef-bulgogi's note at ½x printed "~1 tbs" for ½ and ¾ of one.
  //    stepscale.py's tagger learned the word in the same revision. It has no entry in UNIT_TO_ML,
  //    so no estimate or metric conversion reads it, which is what it had before.
  const MEASURE_UNIT_RE = /\b(fl\s+oz|fluid\s+ounces?|cups?|tbsp|tbs|tablespoons?|tsp|teaspoons?|ounces?|oz|lbs?|pounds?|kilograms?|kg|grams?|g|millilit(?:er|re)s?|ml|lit(?:er|re)s?)\b/i;
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
    if (!(factor > 0) || factor === 1 || neverScales(qty)) return qty;
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
    // ⚠️ THE "~" GOES AFTER A LEADING CONNECTIVE, NOT IN FRONT OF IT. Round B stores an
    //    alternative count as "or 1 large", and prefixing the whole string printed "~or 1 large".
    if (!clampedUp) return out;
    const lead = /^\s*(?:or|plus|and)\s+/i.exec(out);
    return lead ? out.slice(0, lead[0].length) + "~" + out.slice(lead[0].length) : "~" + out;
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
    if (neverScales(qty)) factor = 1;     // converted, never multiplied (see neverScales)
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
    // display-only: "litre"/"litres" -> "liter"/"liters" (American spelling).
    // ⚠️ THE PLURAL IS ITS OWN ROW. One pattern ending in s? collapsed both to "liter", so the
    // liter entries in UNIT_PLURALS could never take effect and "2 liters" printed "2 liter".
    [/\blit(?:re|er)s\b/gi, "liters"],
    [/\blit(?:re|er)\b/gi, "liter"],
    [/\bounces?\b/gi, "oz"],
    [/\bpounds?\b/gi, "lb"],
    [/\bgrams?\b/gi, "g"],
  ];
  function abbrevUnits(s) {
    for (const [re, a] of UNIT_ABBREV) s = String(s).replace(re, a);
    return s;
  }

  // ⚠️ SCALING MOVES THE NUMBER AND LEAVES THE UNIT SAYING THE OLD ONE. "1 cup" doubled printed
  // "2 cup" and "2 cups" halved printed "1 cups". The word is corrected to agree with the figure
  // in front of it, in BOTH directions, and an abbreviation is never touched: "2 tbsp" is right
  // and "2 tbsps" is not a thing anyone writes.
  //
  // The table is spelled out rather than derived with a trailing "s", because the plurals that
  // are not formed that way are exactly the ones a bare rule gets wrong: pinches, boxes, bunches,
  // loaves, leaves.
  const UNIT_PLURALS = {
    cup: "cups", tablespoon: "tablespoons", teaspoon: "teaspoons", ounce: "ounces",
    pound: "pounds", gram: "grams", kilogram: "kilograms", liter: "liters", litre: "litres",
    milliliter: "milliliters", millilitre: "millilitres", quart: "quarts", pint: "pints",
    stick: "sticks", block: "blocks", clove: "cloves", sprig: "sprigs", stalk: "stalks",
    slice: "slices", piece: "pieces", head: "heads", jar: "jars", bag: "bags", box: "boxes",
    ear: "ears", fillet: "fillets", can: "cans", tin: "tins", bulb: "bulbs", bottle: "bottles",
    packet: "packets", package: "packages", tub: "tubs", sheet: "sheets", handful: "handfuls",
    pinch: "pinches", bunch: "bunches", loaf: "loaves", leaf: "leaves",
    // Added with R1's agreePiece: "2 × 1-inch slice" has to read "slices". The editor's own unit
    // datalist already offers "knob", so these are words the app writes.
    knob: "knobs", section: "sections", chunk: "chunks",
  };
  const UNIT_SINGULARS = {};
  for (const one in UNIT_PLURALS) UNIT_SINGULARS[UNIT_PLURALS[one]] = one;

  // "<number> <unit word>" — the number longest-form-first so "1 1/2" is one token, not two.
  // ⚠️ AND IT HAS TO READ THE GLYPHS, BECAUSE scaleQty ALREADY WROTE THEM. formatAmount returns
  // "½" rather than "1/2", so a pattern that only knew the ascii forms never saw the fraction:
  // amountText("2 cups", 0.25) printed "½ cups" while amountText("1 cup", 0.5) printed "½ cup".
  // Same quantity on screen, two spellings, decided by what the author happened to type.
  const GLYPHS = "¼½¾⅓⅔⅛⅜⅝⅞⅙⅚";
  const NUMBER_THEN_WORD = new RegExp(
    // ⚠️ AND IT NEEDS A RIGHT-HAND BOUNDARY. Without it "2 pint-sized jars" became
    // "2 pints-sized jars": the word matched "pint" and the hyphen did not stop it. A unit used
    // attributively is not the thing being counted.
    `(\\d+\\s+\\d+\\/\\d+|\\d+\\/\\d+|\\d+\\s*[${GLYPHS}]|[${GLYPHS}]|\\d+(?:\\.\\d+)?)(\\s*)([A-Za-z]+)(?![-\\w])`,
    "g");

  // Keep the capital the author wrote: "2 Cups" stays "2 Cups" and does not become "2 cups".
  function matchCase(sample, word) {
    if (sample === sample.toUpperCase() && sample !== sample.toLowerCase()) return word.toUpperCase();
    if (sample.charAt(0) === sample.charAt(0).toUpperCase()) {
      return word.charAt(0).toUpperCase() + word.slice(1);
    }
    return word;
  }

  function fixPlurals(s) {
    return String(s).replace(NUMBER_THEN_WORD, (whole, num, gap, word) => {
      const low = word.toLowerCase();
      const one = UNIT_SINGULARS[low] || (low in UNIT_PLURALS ? low : null);
      if (one === null) return whole;                 // an abbreviation, a descriptor, a name
      const n = tokenToNumber(normalizeFractions(num));
      if (!isFinite(n)) return whole;
      const wanted = n > 0 && n <= 1 ? one : UNIT_PLURALS[one];
      return num + gap + matchCase(word, wanted);
    });
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
  // ---- round B revision 1: two amounts that do not scale the way an ordinary one does ------- //

  // R3. AN AMOUNT MARKED PER PERSON DOES NOT MOVE WITH THE SERVINGS. "about ½ cup per person" is
  // half a cup each whether the cook is making it for two or for ten, so multiplying it by the
  // factor would state a quantity the author never wrote.
  // ⚠️ THE WORD LIST LIVES IN units.py AND HAS THREE CALLERS: this one, import_cleanup's R3 which
  // writes the amount, and stepscale.py which locks the same figure in the METHOD text. Kept in
  // step by tests/js/per-serving-sync.test.js. A first draft put the list in import_cleanup where
  // only one of the three could see it, and a fresh review found the ledger and the method
  // disagreeing on one page at 2x.
  const PER_SERVING = /\bper\s+(?:each\s+)?(?:person|serving|servings|guest|portion|diner)\b/i;

  // R1. A SIZED PIECE IS THE AMOUNT, AND THE SIZE IS NEVER A QUANTITY. "1-inch knob" doubled must
  // not print "2-inch knob", which is what the ordinary number scaler does to it: the figure in
  // front of the unit is the SIZE of one piece. What scales is how many pieces, so the count is
  // written in front with a "×" and the piece is carried through untouched.
  //
  // ⚠️ THE NUMBER GRAMMAR MIRRORS import_cleanup's, AND A FIRST DRAFT DID NOT, which is the worst
  // defect a fresh review found in this round. The Python side WRITES "1/2-inch slices",
  // "1 to 2-inch chunks", "roughly 3 cm chunk", "about 2-inch piece", "4 in. piece" and
  // "1 1/2-inch piece"; the first draft here read only bare integers and single glyphs, so all six
  // fell through to the ordinary scaler and had their SIZE doubled. The guard is now two-layered:
  // this reader, and PIECE_ANYWHERE below.
  //
  // ⚠️ AND THE MULTIPLIER IS "×" ONLY, NEVER A LETTER x. "1 x 2-inch piece" is a dimension PAIR, a
  // sheet of kombu an inch by two, which the Python side declines to write an amount for at all.
  // Reading its "1 x" as a count printed "2 × 2-inch piece" at 2x for a sheet that got no bigger.
  const PIECE_WORDS = ["knob", "knobs", "piece", "pieces", "section", "sections", "chunk",
                       "chunks", "slice", "slices", "stick", "sticks"];
  const PIECE_QUALIFIER = "(?:about|approx\\.?|approximately|around|roughly|~|scant|heaped|" +
                          "heaping|generous|rounded|packed|full|up\\s+to|a\\s+scant|a\\s+heaped|" +
                          "a\\s+generous)";
  const PIECE_ONE_NUM = `\\d+(?:\\s+|\\s+and\\s+|\\s*[&+]\\s*)\\d+\\/\\d+|\\d+\\/\\d+` +
                        `|\\d+(?:\\s*|\\s+and\\s+|\\s*[&+]\\s*)[${GLYPHS}]|[${GLYPHS}]` +
                        `|\\d+(?:\\.\\d+)?`;
  const PIECE_NUM = `(?:(?:${PIECE_ONE_NUM})\\s*(?:to|or|[-–—])\\s*(?:${PIECE_ONE_NUM})` +
                    `|(?:${PIECE_ONE_NUM}))`;
  const PIECE_DIM_UNIT = `(?:"|''|”|″|inch(?:es)?|in\\.|\\bin\\b|cm|` +
                         `centimet(?:re|er)s?|mm|millimet(?:re|er)s?)`;
  const PIECE_DIM = `(?:${PIECE_QUALIFIER}\\s*)?${PIECE_NUM}\\s*(?:-\\s*)?${PIECE_DIM_UNIT}`;
  const PIECE_RE = new RegExp(
    `^\\s*(?:(${PIECE_NUM})\\s*×\\s*)?` +
    `((?:${PIECE_DIM})\\s*-?\\s*(?:${PIECE_WORDS.join("|")}))\\s*$`, "i");
  // ⚠️ THE BELT, AND IT IS WHAT MAKES THE NEXT DRIFT HARMLESS. Any amount holding a dimension next
  // to a piece word is never scaled, whether or not the count above reads. The worst case then
  // becomes "the count did not scale", which a cook can see, instead of "the size doubled", which
  // reads as a perfectly ordinary amount and is wrong.
  const PIECE_ANYWHERE = new RegExp(
    `${PIECE_DIM}\\s*-?\\s*(?:${PIECE_WORDS.join("|")})\\b`, "i");

  // The sized piece inside an amount, as {count, piece}, else null. Mirrors
  // import_cleanup.sized_piece_text, held to it by tests/fixtures/sized-piece.json, which is
  // generated FROM the Python side and asserted by both suites.
  function sizedPiece(qty) {
    const m = PIECE_RE.exec(String(qty == null ? "" : qty));
    return m ? { count: m[1] || "1", piece: m[2].trim() } : null;
  }

  // One piece reads as itself; any other count reads "<n> × <piece>", with the piece word agreed
  // to the count.
  // ⚠️ THE COUNT IS NOT CLAMPED TO A WHOLE NUMBER, AND THAT IS A DELIBERATE DIFFERENCE FROM
  // scaleCount. An egg is indivisible, so "~1 egg" is the honest answer for half of one. A 1-inch
  // knob is a MEASUREMENT of something you cut, which is the whole premise of R1, so half of it is
  // half of it: "½ × 1-inch knob" states the quantity where "~1-inch knob" overstates it.
  function sizedPieceText(piece, factor) {
    const n = tokenToNumber(normalizeFractions(piece.count));
    const scaled = (isFinite(n) && n > 0 ? n : 1) * (factor > 0 ? factor : 1);
    if (Math.abs(scaled - 1) < 1e-9) return piece.piece;
    return `${formatAmount(scaled)} × ${agreePiece(piece.piece, scaled)}`;
  }

  // The piece word, agreed to its count. fixPlurals cannot reach it: NUMBER_THEN_WORD wants the
  // number adjacent to the word and "1-inch" sits between them.
  function agreePiece(piece, count) {
    return String(piece).replace(/([A-Za-z]+)\s*$/, (whole, word) => {
      const low = word.toLowerCase();
      const one = UNIT_SINGULARS[low] || (low in UNIT_PLURALS ? low : null);
      if (one === null) return whole;
      return matchCase(word, count > 0 && count <= 1 ? one : UNIT_PLURALS[one]);
    });
  }

  // `opts.words` keeps the author's unit words ("tablespoons") instead of the ledger's
  // abbreviation ("Tbsp"). Round B revision 2's note amounts use it: Andy's 2x of the Tao Jiew note
  // reads "or 4 tablespoons Korean doenjang + 2 tablespoons water", in the words the author wrote,
  // with every other step of the scaling exactly the ledger's.
  function amountText(qty, factor, opts) {
    if (qty == null || String(qty).trim() === "") return "";
    const f = factor > 0 ? factor : 1;
    const abbrev = opts && opts.words ? (x) => x : abbrevUnits;
    // R3 first: an amount marked per person is printed as the author wrote it, at every factor.
    // ⚠️ REFUSING TO SCALE IS NOT A REASON TO SKIP THE FACTOR-INDEPENDENT FIXES, and a first draft
    //    skipped both. fixPlurals agrees the unit with its figure ("1 cups" -> "1 cup") and
    //    collapseRange reduces a degenerate "1 to 1 tbsp" to "1 tbsp". Neither depends on the
    //    factor, and the old path applied both at factor 1.
    if (PER_SERVING.test(String(qty))) {
      return toUnicodeFractions(abbrev(fixPlurals(collapseRange(String(qty).trim()))));
    }
    // R1 next: a sized piece scales by its count and never by its size.
    const piece = sizedPiece(qty);
    if (piece) return toUnicodeFractions(sizedPieceText(piece, f));
    // And the belt: a dimension next to a piece word is never scaled even when the count above
    // could not be read, because scaling a SIZE is the one outcome R1 exists to prevent.
    if (PIECE_ANYWHERE.test(String(qty))) {
      return toUnicodeFractions(abbrev(fixPlurals(collapseRange(String(qty).trim()))));
    }
    let t;
    if (isCountAmount(qty)) t = fixPlurals(scaleCount(qty, f));
    // ⚠️ A DUAL AMOUNT IS SPLIT BY THE CALLER NOW, so this branch is the one that is left when a
    // stored qty still carries a " / " of its own. It is abbreviated like any other, which it
    // was not: the branch skipped abbrevUnits, and four rounds of the round B preview judged a
    // wrapping problem that only existed because full words were being printed where the page
    // prints "tbsp".
    else t = abbrev(fixPlurals(scaleQty(qty, f)));
    return toUnicodeFractions(t);   // stored ascii ("1 1/2") -> unicode, so all amounts match
  }

  // The ledger's SECOND amount: the author's own backup, scaled the same way the first one is.
  // Two backups are stored in one slot joined by " / " and the display stacks each on its own
  // line, so this answers with a list rather than a string.
  const SECOND_AMOUNT_JOIN = " / ";
  function secondAmountParts(secondary, factor) {
    if (secondary == null) return [];
    return String(secondary).split(SECOND_AMOUNT_JOIN)
      .map((part) => amountText(part.trim(), factor))
      .filter((t) => t !== "");
  }

  // The ledger WEIGHT column: the estimated gram weight of a VOLUME amount, for ingredients the
  // weight chart knows (gramsPerMl set) and above the 2-tbsp spoon threshold — else "" (empty for
  // spoon-sized amounts, weights/counts, already-metric amounts, and unmatched names).
  function weightText(qty, gramsPerMl, factor) {
    if (gramsPerMl == null) return "";
    // ⚠️ AND THE ESTIMATE UNDER A PER-PERSON AMOUNT DOES NOT SCALE EITHER. A fresh review found
    //    the figure above holding at "about ½ cup per person" while the gram sub-line directly
    //    beneath it went 63 g, 125 g, 251 g. The grams PER PERSON are a true figure, so the line
    //    is kept rather than suppressed, and it is computed at the factor the amount itself uses.
    if (PER_SERVING.test(String(qty))) factor = 1;
    const parsed = parseAmount(normalizeFractions(String(qty)));
    if (!parsed) return "";
    const mlPer = UNIT_TO_ML[parsed.unit];
    if (!mlPer) return "";                               // not a volume (oz/lb/g/kg/ml/count)
    const ml = parsed.value * (factor > 0 ? factor : 1) * mlPer;
    if (ml <= SPOON_MAX_ML + 1e-9) return "";            // <= 2 tbsp stays a measuring spoon
    return "~" + group(Math.max(1, Math.round(ml * gramsPerMl))) + " g";
  }

  export {
    UNICODE_FRACTIONS, normalizeFractions, tokenToNumber, NICE_FRACTIONS, formatAmount, group,
    AMOUNT_TOKEN, scaleQty, collapseRange, UNIT_TO_ML, UNIT_TO_G, MEASURE_UNIT_RE, MEASURE_UNIT_RE_G,
    SPOON_MAX_ML, isCountAmount, scaleCount, parseAmount, toMetric, displayQty,
    abbrevUnits, canonicalizeUnit, amountText, weightText, toUnicodeFractions,
    UNIT_PLURALS, fixPlurals, secondAmountParts, SECOND_AMOUNT_JOIN,
    PER_SERVING, PIECE_WORDS, sizedPiece, sizedPieceText, agreePiece, PIECE_ANYWHERE,
    neverScales,
  };
