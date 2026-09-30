"""units.py — the unit ABBREVIATOR: a small pure mirror of static/scaler.js's UNIT_ABBREV /
abbrevUnits / canonicalizeUnit. Standardizes a measuring-unit word to its canonical short form
("tablespoons" -> "tbsp"), leaving numbers and unrecognized words untouched.

Shared "brain" (the weights.py <-> scaler.js pattern): the client canonicalizes units on EVERY save
(canonicalizeUnit, so "1 teaspoon" is stored back as "1 tsp"), which would make the change diff
(snapshot_diff) read an untouched row's baseline-vs-current as a phantom amount edit. snapshot_diff
canonicalizes amounts through THIS module before comparing, so a representation-only unit difference
never registers. Pure: `re` only, no deps — safe to import from the pure snapshot_diff.

Keep UNIT_ABBREV in sync with scaler.js:211-221 (SAME ordered pattern sources + replacements) —
guarded cross-language by tests/js/unit-abbrev-sync.test.js.
"""
import re

# Ordered (pattern-source, replacement) — the SAME rule set and order as scaler.js's UNIT_ABBREV. The
# pattern sources are byte-for-byte the JS regex bodies (between the /.../), applied case-insensitively,
# singular+plural, replacing with the lowercase short form. Order matters: "fluid ounce" before "ounce".
UNIT_ABBREV = [
    (r"\bfluid\s+ounces?\b", "fl oz"),
    (r"\btablespoons?\b", "tbsp"),
    (r"\bteaspoons?\b", "tsp"),
    (r"\bkilograms?\b", "kg"),
    (r"\bmilli(?:lit(?:re|er)s?)\b", "ml"),
    (r"\blit(?:re|er)s?\b", "liter"),   # display-only: "litre"/"litres" -> "liter" (American spelling)
    (r"\bounces?\b", "oz"),
    (r"\bpounds?\b", "lb"),
    (r"\bgrams?\b", "g"),
]
_COMPILED = [(re.compile(pattern, re.IGNORECASE), repl) for pattern, repl in UNIT_ABBREV]


# The SAME map as scaler.js UNICODE_FRACTIONS, in the same order, guarded cross-language by
# tests/js/fraction-sync.test.js. A glyph and its ascii spelling are the same amount, and the reading
# view proves it: amountText runs every amount through toUnicodeFractions, so "1/2 tsp" and "½ tsp"
# are rendered as the same characters on the page. Comparing them as different text marked a row the
# cook could not see a change in.
UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅙": "1/6", "⅚": "5/6",
}
_FRACTION_RX = re.compile("[" + "".join(UNICODE_FRACTIONS) + "]")


def normalize_fractions(s):
    """Mirrors scaler.js normalizeFractions: every vulgar glyph becomes its ascii spelling with a
    space on each side, then whitespace collapses and the ends are trimmed. "1½" -> "1 1/2",
    "½ tsp" -> "1/2 tsp". Unknown fractions and plain numbers pass through untouched."""
    s = "" if s is None else str(s)
    return " ".join(_FRACTION_RX.sub(lambda m: " " + UNICODE_FRACTIONS[m.group()] + " ", s).split())


def compare_key(s):
    """⚠️ THE COMPARISON FORM, AND IT IS DELIBERATELY STRONGER THAN canon_unit_str. Two amounts are
    the same for diffing purposes when the cook cannot tell them apart on the page: same number, same
    unit, whatever the fraction glyph, the spacing or the case. canon_unit_str stays a faithful mirror
    of the client's canonicalizeUnit, which is what the client actually writes to storage, so it must
    NOT gain the fraction rule. This is the one that answers "did anything visible change".

    Detection only. Every from/to the diff emits keeps the raw stored string, so a real change still
    shows the real values."""
    return canon_unit_str(normalize_fractions(s))


def compare_text(s):
    """The same question for a NAME, a NOTE, a STEP or a HEADING, which carry no amount. Trimmed,
    whitespace collapsed, null and empty folded together. A step re-wrapped across two lines reads
    identically once it is laid out, and an empty string is not an edit of a null."""
    return " ".join(("" if s is None else str(s)).split())


def abbrev_units(s):
    """Apply every UNIT_ABBREV rule in order (case-insensitive) and return the result. Mirrors
    scaler.js abbrevUnits: only recognized unit words match; numbers/other words are left as authored."""
    s = "" if s is None else str(s)
    for rx, repl in _COMPILED:
        s = rx.sub(repl, s)
    return s


def canon_unit_str(s):
    """The canonical COMPARISON form of an amount string: abbrev_units + strip + lowercase — mirrors the
    client's canonicalizeUnit (abbrevUnits(...).trim().toLowerCase()), so "1 teaspoon", "1 Teaspoon", and
    "1 tsp" all collapse to "1 tsp". Representation-only: the numeric value is never changed."""
    return abbrev_units(s).strip().lower()
