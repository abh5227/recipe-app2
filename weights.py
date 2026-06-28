#!/usr/bin/env python3
"""weights.py — volume→weight reference data and ingredient-name matching (Phase 1c).

One Python home for everything the cups→grams converter needs that must NOT drift
between the live converter (app.py attaches a per-line grams_per_ml when serving a
recipe) and the build-time coverage report (build_db.py). Name-matching lives here and
ONLY here, so there is a single source of truth.

Source of the weight chart: King Arthur Baking Ingredient Weight Chart
(king-arthur-staples-v2.csv, loaded by build_db.py).
"""
import re

# Volume units → millilitres. PHYSICAL CONSTANTS, deliberately duplicated from the
# Phase 1b converter in static/app.js (UNIT_TO_ML): the SAME numbers in two languages.
# JS and Python can't literally share a constant, so if you change one, change the other.
VOLUME_TO_ML = {
    "cup": 236.588, "cups": 236.588,
    "tablespoon": 14.7868, "tablespoons": 14.7868, "tbsp": 14.7868,
    "teaspoon": 4.92892, "teaspoons": 4.92892, "tsp": 4.92892,
}

def _to_number(tok):
    """'2 1/4' -> 2.25, '1/2' -> 0.5, '1' -> 1.0."""
    tok = tok.strip()
    if " " in tok:                       # mixed number: whole + fraction
        whole, frac = tok.split(None, 1)
        num, den = frac.split("/")
        return int(whole) + int(num) / int(den)
    if "/" in tok:                       # plain fraction
        num, den = tok.split("/")
        return int(num) / int(den)
    return float(tok)                    # whole or decimal


def parse_reference_volume(text):
    """A King Arthur reference volume ("1 cup", "1/2 cup", "2 1/4 teaspoons") -> mL.
    Returns None if the amount can't be parsed or the unit isn't a known volume."""
    if not text:
        return None
    amount, _, unit = text.strip().lower().rpartition(" ")
    ml_per = VOLUME_TO_ML.get(unit)
    if not amount or ml_per is None:
        return None
    try:
        return _to_number(amount) * ml_per
    except (ValueError, ZeroDivisionError):
        return None


def normalize(name):
    """Lowercased, punctuation-stripped lookup key. Keeps parenthetical words
    ("Sugar (granulated white)" -> "sugar granulated white") and drops a trailing
    clause after a comma ("olive oil, divided" -> "olive oil")."""
    if not name:
        return ""
    s = name.strip().lower()
    s = s.split(",")[0]                  # drop trailing clause: ", divided", ", chopped"
    s = s.replace("-", " ")             # all-purpose -> all purpose
    s = re.sub(r"[^a-z0-9 ]+", " ", s)  # drop ()'/&. -> spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Volume units the converter recognizes (the volume subset of MEASURE_UNIT_RE in
# static/scaler.js). Includes spelled-out millilitres/milliliters so a metric-volume line
# reads as a volume, not an unrecognized unit.
_VOLUME_UNIT_RE = re.compile(
    r"\b(fl\s+oz|fluid\s+ounces?|cups?|tbsp|tablespoons?|tsp|teaspoons?"
    r"|millilit(?:re|er)s?)\b", re.I)


def has_volume_unit(qty):
    """True if a quantity string carries a volume unit the converter can turn into grams."""
    return bool(qty) and _VOLUME_UNIT_RE.search(qty) is not None


def base_name(name):
    """Like normalize, but also drops any parenthetical qualifier entirely:
    "Sugar (granulated white)" -> "sugar", "Garlic (minced)" -> "garlic". Used for the
    conservative fallback, where a recipe says "sugar" but the chart row is
    "Sugar (granulated white)"."""
    if not name:
        return ""
    return normalize(re.sub(r"\([^)]*\)", " ", name))


def _row_convert(r):
    """The row's convert_to_grams flag (migration 013), defaulting to True when the column
    is absent — older callers and test fixtures that don't supply it still behave as before."""
    try:
        v = r["convert_to_grams"]
    except (KeyError, IndexError):
        return True
    return True if v is None else bool(v)


def build_index(rows):
    """Build a matcher from ingredient_weights rows (each supporting row["lookup_key"],
    row["display_name"], row["grams_per_ml"], and optionally row["convert_to_grams"]).
    Returns {"exact": {...}, "base": {...}}, each mapping a name ->
    (grams_per_ml, display_name, convert_to_grams).

    The base index only keeps a name when every chart row sharing that base agrees on
    grams_per_ml (within a tiny epsilon). Where they disagree — table vs kosher salt,
    minced vs sliced garlic — the base is dropped so the matcher DECLINES instead of
    guessing which density was meant.
    """
    exact = {}
    groups = {}
    for r in rows:
        key, display, gpm = r["lookup_key"], r["display_name"], r["grams_per_ml"]
        conv = _row_convert(r)
        exact.setdefault(key, (gpm, display, conv))
        groups.setdefault(base_name(display), []).append((gpm, display, conv))
    base = {}
    for b, entries in groups.items():
        gpms = [g for g, _, _ in entries]
        if max(gpms) - min(gpms) <= 1e-9:
            base[b] = entries[0]
    return {"exact": exact, "base": base}


# Curated aliases: recipe wording -> a name the chart already knows, for cases that are
# genuinely the same ingredient (same density) but won't connect by normalization alone.
# This stays within "decline over guess" — known equalities, not heuristics. Deliberately
# excludes near-but-different names (e.g. caster sugar ~190 g/cup vs granulated 198; golden
# syrup) so we never point a name at a wrong density.
#
# Grouped by canonical chart name (each appears once), then flattened to synonym->canonical.
_ALIAS_GROUPS = {
    "olive oil": ["extra virgin olive oil", "virgin olive oil", "evoo"],  # grades / abbrev
    "all-purpose flour": ["plain flour"],                                 # British
    "confectioners' sugar": ["powdered sugar", "icing sugar"],            # US / British
    "baking soda": ["bicarbonate of soda", "bicarb"],                    # British
    # Single-user default: bare "kosher salt" is genuinely ambiguous (Diamond Crystal
    # ~8 g/tbsp vs Morton's ~16 — an imported recipe assuming Morton's would convert ~2x
    # light). We resolve it to MY kitchen's salt (Diamond Crystal) on purpose, not by guessing.
    "salt (kosher diamond crystal)": ["kosher salt"],
}
ALIASES = {syn: canon for canon, syns in _ALIAS_GROUPS.items() for syn in syns}


def match_weight(name, index):
    """Resolve a recipe line's ingredient name to (grams_per_ml, display_name,
    convert_to_grams), or None. (Callers that only want the density read element [0].)

    1) exact normalized match;
    2) conservative fallback: unambiguous base-name match;
    3) curated alias (e.g. "extra virgin olive oil" / "EVOO" -> "olive oil");
    4) otherwise DECLINE (None) — never guess.
    """
    n = normalize(name)
    if n and n in index["exact"]:
        return index["exact"][n]
    b = base_name(name)
    if b and b in index["base"]:
        return index["base"][b]
    alias = ALIASES.get(n) or ALIASES.get(b)
    if alias:
        a = normalize(alias)
        if a in index["exact"]:
            return index["exact"][a]
        if a in index["base"]:
            return index["base"][a]
    return None
