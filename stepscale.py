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

# A numeric amount: mixed ("1 1/2"), fraction ("1/2"), digit+unicode ("1½"), bare
# unicode ("½"), or int/decimal ("2", "2.5"). Mirrors AMOUNT_TOKEN in static/app.js
# (extended to also accept the unicode-fraction glyphs the recipes are written with).
_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+\s*[" + _UNI + r"]|[" + _UNI + r"]|\d+(?:\.\d+)?)"

# --- Layer 2: never-scale guard units (temperature, time, dimension) ---
_TEMP = r"(?:°\s*[CF]?|degrees?\b)"
_TIME = r"(?:min(?:ute)?s?|h(?:ou)?rs?|sec(?:ond)?s?)\b"
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
        elif kind == "heur":
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


def api_spans(text):
    """Client-ready spans for rendering. Contiguous fixed text (plain/guarded/unitless/locked)
    is merged into one "plain" span (the client linkifies it, never scales it); scalable spans
    are emitted as "scale" (the client rescales the text via the 1a scaler). Markup markers are
    already stripped."""
    out = []
    buf = []

    def flush():
        if buf:
            out.append({"t": "plain", "text": "".join(buf)})
            buf.clear()

    for sp in parse_step(text):
        if sp["category"] in (MARKED_SCALE, HEURISTIC_SCALE):
            flush()
            out.append({"t": "scale", "text": sp["text"], "value": sp.get("value"), "unit": sp.get("unit")})
        else:
            buf.append(sp["text"])
    flush()
    return out
