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


# The punctuation that is PART OF A NUMBER when it sits between two digits: a decimal point, a
# fraction slash, and the three range dashes. "1.5" is not "15", "1/2" is not "12", "2-3" is not
# "23". A degree sign counts too, directly after a digit: "350°F" is not "350F".
# ⚠️ EVERY DASH A KEYBOARD OR A PASTE ACTUALLY PRODUCES, not just the three that were listed.
# This held the hyphen, the en dash and the em dash, and missed U+2010 HYPHEN, U+2011
# NON-BREAKING HYPHEN, U+2012 FIGURE DASH, U+2015 HORIZONTAL BAR, U+2212 MINUS SIGN and U+FF0D
# FULLWIDTH HYPHEN-MINUS. A PDF, a Word document and several web pages emit those, and with any
# them "4‑6 minutes" compared equal to "4 6 minutes", which is exactly the spiced-scallops
# correction the exception exists to save, undone by one character. 0 of the 13,708 text values
# in the corpus carry one today, so this is the importer's path rather than the corpus's.
_NUMBER_PUNCT = ".‐‑‒–—―−－-/"
# A thousands comma is NOT in that set, and it is dropped rather than spaced, so "1,000" and "1000"
# compare equal. They are the same quantity, which is the question this function asks.
_THOUSANDS = ","
# ⚠️ AN APOSTROPHE IS DROPPED, NOT SPACED, BECAUSE IT NEVER SEPARATES TWO WORDS. Spacing it turns
# "don't" into "don t", which then differs from "dont" — a spelling fix would mark where a full stop
# does not. The straight and curly forms both land here, which is the case that actually matters: a
# keyboard or a paste can swap one for the other without anybody typing a word.
# A HYPHEN IS SPACED, by contrast, because it often does separate words: "skin-on and bone-in" and
# "skin on and bone in" are the same line, and that pair is in the corpus (kuku-paka).
_IN_WORD = "'\u2019\u02bc"


def compare_text(s):
    """The same question for a NAME, a NOTE, a STEP or a HEADING, which carry no amount.

    Whitespace collapsed, null and empty folded together, LETTER CASE AND PUNCTUATION BETWEEN WORDS
    IGNORED. A step re-wrapped across two lines reads identically once it is laid out, and an empty
    string is not an edit of a null.

    ⚠️ CASE AND PUNCTUATION ARE IGNORED FOR THE MARK, NOT FOR THE SAVE. The edit is stored exactly as
    typed either way. This decides only whether the recipe page says the cook changed something, and
    capitalizing a sentence or adding a full stop is not a change to the recipe. Measured against the
    49 real annotation entries on the corpus before it shipped: 0 of them disappear, so this loosens
    the test without quietly dropping a single thing a cook had actually done.

    ⚠️ PUNCTUATION INSIDE A NUMBER ALWAYS COUNTS, which is the whole reason this is not a one-line
    strip. The closest pair in the corpus is spiced-scallops' "simmer for 4 6 minutes" becoming
    "simmer for 4-6 minutes", a real correction that turns two loose numbers into a range. A rule
    that threw away every dash would have erased it.
    """
    s = "" if s is None else str(s)
    out = []
    for i, ch in enumerate(s):
        if ch.isalnum() or ch.isspace():
            out.append(ch)
            continue
        prev = s[i - 1] if i else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch == "\u00b0" and prev.isdigit():
            out.append(ch)                                  # 350°F is not 350F
        elif ch == "." and nxt.isdigit():
            # ⚠️ A DECIMAL POINT IS PART OF THE NUMBER EVEN WITH NOTHING IN FRONT OF IT. The test used
            #    to need a digit on BOTH sides, so ".5 cup" compared equal to "5 cup" and "add .5 tsp"
            #    to "add 5 tsp" — a tenfold quantity change going unmarked. A full stop that ENDS a
            #    sentence is never followed by a digit without a space, so this cannot swallow one.
            out.append(ch)
        elif ch in _NUMBER_PUNCT and prev.isdigit() and nxt.isdigit():
            out.append(ch)                                  # 1.5 / 1/2 / 2-3
        elif ch in _THOUSANDS and prev.isdigit() and nxt.isdigit():
            continue                                        # 1,000 == 1000
        elif ch in _IN_WORD:
            continue                                        # don't == dont, and ' == ’
        else:
            out.append(" ")
    return " ".join("".join(out).split()).lower()


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
