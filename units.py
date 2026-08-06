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
