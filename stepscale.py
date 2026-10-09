#!/usr/bin/env python3
"""stepscale.py — parse method/step text into scalable vs never-scale spans (Phase 1d).

THE SINGLE SOURCE OF TRUTH for step-quantity scaling: both the live API (app.py attaches
display spans to each step) and the build-time coverage report (build_db.py) call this.

Safe-hybrid model, strict priority — markup > guard > heuristic:
  1. EXPLICIT MARKUP wins, always.
       {{2 tbsp}}  -> scale this quantity   (MARKED_SCALE)
       {{!350°F}}  -> lock, never scale     (MARKED_LOCK)   (manual override)
     Distinct from ingredient links [[...]] so the two never collide.
  2. HARD NEVER-SCALE GUARD (runs before the heuristic, not as a heuristic opt-out): any
     number adjacent to a temperature, time, or dimension — including ranges ("20 to 25
     minutes") and N×N ("9x13") — is GUARDED and never scaled.
  3. HEURISTIC scales the rest: a number immediately followed by a recognized volume/weight
     unit that survived layers 1-2.
Bias to UNDER-match: a bare unitless number ("divide into 4") is left alone (UNITLESS) and
flagged for review — never scaled. Failure mode is "miss a quantity," never "scale a fixed
number."

The actual scaling math is NOT done here — the client reuses the Phase 1a scaler
(scaleQty/formatAmount in static/app.js) on each scalable span's text, so step quantities
format identically to the ingredient list.
"""
import re

import units

# Span categories.
MARKED_SCALE = "marked_scale"
MARKED_LOCK = "marked_lock"
GUARDED = "guarded"
HEURISTIC_SCALE = "heuristic_scale"
UNITLESS = "unitless"
PLAIN = "plain"

# Unicode fractions -> ascii (mirrors normalizeFractions in static/app.js).
_UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4",
    "⅓": "1/3", "⅔": "2/3",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
    "⅙": "1/6", "⅚": "5/6",
}
_UNI = "".join(_UNICODE_FRACTIONS)

# A CONNECTIVE spelling of the space in a mixed number: "1 and 1/2" is the same quantity as "1 1/2".
# The signal is INTEGER + connective + FRACTION — never the word alone, which is why "salt and pepper"
# and "cored and diced" cannot match: a fraction must follow. Measured over 7,052 lines (corpus +
# archive + the 9 fixtures): 379 lines contain the word "and", 4 match this shape, and those 4 are
# exactly the intended targets.
#   "and" is EVIDENCED — sallysbakingaddiction.com writes every compound this way (4 of its 17 lines).
#   "&" and "+" are ANTICIPATED, not witnessed: zero instances in any corpus we hold. They occupy the
#   same grammatical slot and cost nothing, but do not cite them as proven. "plus" is deliberately
#   EXCLUDED — a word with a wider false-positive surface and no instance anywhere.
_JOIN = r"(?:\s+and\s+|\s*[&+]\s*)"

# A numeric amount: mixed ("1 1/2" / "1 and 1/2"), fraction ("1/2"), digit+unicode ("1½" / "1 and ½"),
# bare unicode ("½"), or int/decimal ("2", "2.5"). Mirrors AMOUNT_TOKEN in static/app.js (extended to
# also accept the unicode-fraction glyphs the recipes are written with, and the connective above —
# the CLIENT never sees a connective, because parse_amount canonicalizes it away; see _canon_amount).
_NUM = (r"(?:\d+(?:\s+|" + _JOIN + r")\d+/\d+|\d+/\d+|\d+(?:\s*|" + _JOIN + r")["
        + _UNI + r"]|[" + _UNI + r"]|\d+(?:\.\d+)?)")

# --- Layer 2: never-scale guard units (temperature, time, dimension) ---
_TEMP = r"(?:°\s*[CF]?|degrees?\b)"
# ⚠️ DAYS AND WEEKS ADDED 2026-09-27, and the reason is a MISREAD rather than a scaling risk.
#    Without them "marinate in the fridge for 2 days" tokenized the 2 as a bare UNITLESS number with
#    the word "days" stranded in the plain text beside it. That put a duration in the
#    unitless-for-review bucket, which exists for a genuinely ambiguous count ("divide into 4"), and
#    it split the duration across two spans so nothing downstream could read it whole. Measured on
#    the corpus before the change: 3 live steps, and 0 time-looking spans were ever SCALABLE either
#    before or after, so no number changes what it does at 2x.
#    Months and years are deliberately absent. Neither occurs in any step in the corpus.
_TIME = r"(?:min(?:ute)?s?|h(?:ou)?rs?|sec(?:ond)?s?|days?|weeks?)\b"
_DIM = r'(?:inch(?:es)?\b|"|cm\b|mm\b)'
_GUARD_UNIT = r"(?:" + _TEMP + r"|" + _TIME + r"|" + _DIM + r")"

# --- Layer 3: scalable cooking units (volume + weight) ---
# Mirrors UNIT_TO_ML + UNIT_TO_G in static/app.js, plus metric mass/volume — CROSS-LANGUAGE
# DUPLICATION, keep the two in sync. Ordered longest-first so multi-word units win and
# "fl oz" is matched as ONE unit (its inner "oz" is never tokenized separately). Single
# ambiguous letters (bare "l"/"L" for litre) are deliberately excluded.
_SCALE_UNITS = [
    r"fl\s*oz", r"fluid\s+ounces?",
    "tablespoons?", "teaspoons?", "milli[lL]itres?", "milli[lL]iters?", "kilograms?",
    "tbsp", "tsp", "cups?", "litres?", "liters?", "ml", "kg", "grams?",
    "ounces?", "pounds?", "lbs?", "oz", "lb", "g",
]
_SCALE_UNIT = r"(?:" + "|".join(_SCALE_UNITS) + r")"

# One ordered-alternation scan. Order IS the priority: guard patterns first (range, then
# N×N, then single), then the heuristic, then a bare number. Python's regex engine takes
# the first alternative that matches at each position, so a guarded number is claimed before
# the heuristic can ever see it.
_TOKEN_RE = re.compile(
    r"(?P<grange>" + _NUM + r"\s*(?:to|[-–—])\s*" + _NUM + r"\s*-?\s*" + _GUARD_UNIT + r")"
    r"|(?P<gnxn>" + _NUM + r"\s*[x×]\s*" + _NUM + r")"
    r"|(?P<gsingle>" + _NUM + r"\s*-?\s*" + _GUARD_UNIT + r")"
    r"|(?P<srange>" + _NUM + r"\s*(?:to|[-–—])\s*" + _NUM + r"\s*" + _SCALE_UNIT + r"\b)"
    r"|(?P<heur>" + _NUM + r"\s*" + _SCALE_UNIT + r"\b)"
    r"|(?P<bare>" + _NUM + r")",
    re.IGNORECASE,
)

_MARKUP_RE = re.compile(r"\{\{(!?)([^}]*)\}\}")

_NUM_ASCII = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?"
_QTY_RE = re.compile(r"\s*(" + _NUM_ASCII + r")\s*(.*)$", re.DOTALL)


def _normalize_unicode(s):
    for glyph, ascii_frac in _UNICODE_FRACTIONS.items():
        s = s.replace(glyph, " " + ascii_frac + " ")
    return re.sub(r"\s+", " ", s).strip()


_JOIN_RE = re.compile(_JOIN)


def _canon_amount(s):
    """A matched amount -> its canonical mixed-number spelling: "1 and 1/2" -> "1 1/2".

    WHY CANONICALIZE RATHER THAN STORE THE SOURCE SPELLING. Two downstream consumers cannot read a
    connective, and both fail SILENTLY rather than loudly:
      - _to_value splits a mixed number on whitespace, so "1 and 1/2" raises ValueError and
        parse_amount's except-clause turns that into value=None — the regex would match and the
        quantity would still be lost.
      - static/scaler.js AMOUNT_TOKEN has no connective alternative, so it would tokenize "1" and
        "1/2" SEPARATELY and scale each: 2x "1 and 1/2" would render "2 and 1".
    Canonicalizing here means neither has to change and the client needs no mirrored edit. The
    original spelling is never lost — raw_text keeps the publisher's line verbatim.

    Applied ONLY to text already matched as an amount by _NUM (integer + connective + fraction), so
    it cannot touch an "and" anywhere else in the line."""
    return re.sub(r"\s+", " ", _JOIN_RE.sub(" ", s or "")).strip()


def _to_value(tok):
    tok = tok.strip()
    if " " in tok:                       # mixed number "1 1/2"
        whole, frac = tok.split(None, 1)
        num, den = frac.split("/")
        return int(whole) + int(num) / int(den)
    if "/" in tok:                       # fraction "1/2"
        num, den = tok.split("/")
        return int(num) / int(den)
    return float(tok)                    # whole / decimal


def _parse_qty(text):
    """Best-effort (value, unit) for a scalable span — metadata only (the client rescales
    via the shared 1a scaler, so exactness here just feeds the coverage report)."""
    m = _QTY_RE.match(_normalize_unicode(text))
    if not m:
        return None, text.strip()
    try:
        return _to_value(m.group(1)), m.group(2).strip()
    except (ValueError, ZeroDivisionError):
        return None, m.group(2).strip()


def _parse_free(segment):
    """Categorize a markup-free segment via the ordered-alternation scan."""
    spans = []
    last = 0
    for m in _TOKEN_RE.finditer(segment):
        if m.start() > last:
            spans.append({"category": PLAIN, "text": segment[last:m.start()]})
        kind = m.lastgroup
        tok = m.group()
        if kind in ("grange", "gnxn", "gsingle"):
            spans.append({"category": GUARDED, "text": tok})
        elif kind in ("heur", "srange"):
            # srange ("1 to 2 tbsp") is ONE scalable span -> the client scaler scales BOTH ends
            # together (not just the unit-bearing one), so a range can't collapse to "1 to 1".
            value, unit = _parse_qty(tok)
            spans.append({"category": HEURISTIC_SCALE, "text": tok, "value": value, "unit": unit})
        else:                            # bare number, no unit
            spans.append({"category": UNITLESS, "text": tok})
        last = m.end()
    if last < len(segment):
        spans.append({"category": PLAIN, "text": segment[last:]})
    return spans


def parse_step(text):
    """Parse step text into ordered, categorized spans (priority markup > guard > heuristic).
    Each span is {"category", "text"}; scalable spans also carry "value" + "unit". The
    {{...}}/{{!...}} markers are stripped from the emitted text. Single source of truth."""
    if not text:
        return []
    spans = []
    pos = 0
    for m in _MARKUP_RE.finditer(text):
        if m.start() > pos:
            spans.extend(_parse_free(text[pos:m.start()]))
        bang, content = m.group(1), m.group(2)
        if bang:
            spans.append({"category": MARKED_LOCK, "text": content})
        else:
            value, unit = _parse_qty(content)
            spans.append({"category": MARKED_SCALE, "text": content, "value": value, "unit": unit})
        pos = m.end()
    if pos < len(text):
        spans.extend(_parse_free(text[pos:]))
    return spans


# ⚠️ AN AMOUNT MARKED PER PERSON IS LOCKED IN THE METHOD TOO, AND LEAVING IT OUT PUT THE TWO
#    COLUMNS OF ONE PAGE IN DISAGREEMENT. Round B's R3 locks such an amount in the ingredient
#    ledger; without the same guard here, at 2x the ledger read "about 1/2 cup per person" while
#    the step beside it read "1 cup rice per person". Found by a fresh review of R3.
#
#    ⚠️ THE LOOKAHEAD STOPS AT A COMMA, not at the sentence. "Divide 2 cups rice among the bowls,
#       about 1/2 cup per person" has to scale the 2 cups and lock the 1/2 cup, and a lookahead
#       that ran to the full stop would have locked both. The words live in units.py, which is the
#       one home this rule, import_cleanup's R3 and static/scaler.js all read.
_PER_SERVING_CLAUSE_END = re.compile(r"[,.;:]")


def _locked_per_serving(text, after):
    """Does the amount ending at `after` belong to a per-person figure in its own clause?"""
    end = _PER_SERVING_CLAUSE_END.search(text, after)
    clause = text[after:end.start() if end else len(text)]
    return bool(units.PER_SERVING_RE.search(clause))


def api_spans(text, _parsed=None, _promote=None):
    """Client-ready spans for rendering. Contiguous fixed text (plain/guarded/unitless/locked)
    is merged into one "plain" span (the client linkifies it, never scales it); scalable spans
    are emitted as "scale" (the client rescales the text via the 1a scaler). Markup markers are
    already stripped. `_parsed` and `_promote` are note_spans' and nothing else's."""
    out = []
    buf = []
    at = 0

    def flush():
        if buf:
            out.append({"t": "plain", "text": "".join(buf)})
            buf.clear()

    for i, sp in enumerate(_parsed if _parsed is not None else parse_step(text)):
        at += len(sp["text"])
        scalable = sp["category"] in (MARKED_SCALE, HEURISTIC_SCALE) or i == _promote
        if scalable and _locked_per_serving(text, at):
            scalable = False               # per person is per person at every factor
        if scalable:
            flush()
            out.append({"t": "scale", "text": sp["text"], "value": sp.get("value"), "unit": sp.get("unit")})
        else:
            buf.append(sp["text"])
    flush()
    return out


# ---- round B revision 2: the amounts in a substitution note scale with the servings ------------ #
# ⚠️ ANDY'S CALL (decisions-3): AT 2x THE TAO JIEW NOTE "or 2 tablespoons Korean doenjang + 1
#    tablespoon water" READS "or 4 tablespoons Korean doenjang + 2 tablespoons water". Only a note
#    that OPENS "or <amount>" scales, because that opening is what R5 and R2 write and what says the
#    note is a quantity of something else. "(½ pound each)", "plus more for dusting", "sifted" and
#    every note a cook typed stay exactly as stored. Display only: the stored text, Edit mode and
#    "your changes" never see a scaled note.
# ⚠️ THE GRAMMAR IS THE METHOD TEXT'S, NOT A SECOND READER. parse_step tags the note the way it
#    tags a step, so a size ("2-inch") and a time are guarded, and _locked_per_serving holds a
#    per-person figure, exactly as they are in the method. One thing is added: the bare count right
#    after the "or" is the alternative's own quantity ("or 2 pureed tomatoes"), which the method
#    tagger leaves alone because "divide into 4" in a step is not one.
# ⚠️ AND A NOTE THE TAGGER CANNOT READ WHOLE IS NOT SCALED AT ALL. beef-bulgogi's "or 1 tbs of brown
#    sugar and 1½ tbs rice syrup" writes "tbs", which is not a unit the tagger knows, so after the
#    leading count every other number is a bare one. Scaling the brown sugar and not the syrup would
#    print a substitution that no longer adds up, which is worse than the note as written.
_NOTE_OR_LEAD_RE = re.compile(r"^\s*or\s+(?:about\s+|approximately\s+|approx\.?\s+|~\s*)?",
                              re.IGNORECASE)


def note_spans(text):
    """Display spans for an ingredient row's note that opens "or <amount>", else None."""
    m = _NOTE_OR_LEAD_RE.match(text or "")
    if not m or not re.match(_NUM, text[m.end():]):
        return None
    parsed = parse_step(text)
    at, promote = 0, None
    for i, sp in enumerate(parsed):
        if at == m.end() and sp["category"] == UNITLESS:
            promote = i                      # the alternative's own count
        at += len(sp["text"])
    if any(sp["category"] == UNITLESS and i != promote for i, sp in enumerate(parsed)):
        return None                          # a number the tagger cannot read: leave it whole
    spans = api_spans(text, _parsed=parsed, _promote=promote)
    return spans if any(sp["t"] == "scale" for sp in spans) else None
