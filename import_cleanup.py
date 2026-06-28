#!/usr/bin/env python3
"""import_cleanup.py — the source-agnostic IMPORT CLEANUP CORE (preview only).

Takes ONE normalized recipe (the shape emitted by paprika_native_reader.normalize)
and returns structured-or-flagged data. It is the format-agnostic half of Phase 15:
it neither knows nor cares that the source is Paprika.

GUIDING PRINCIPLE: aggressive = extract every CLEAR win, FLAG the ambiguous/risky ones
for review — never force-parse in a way that could corrupt data or break library linkage,
and never silently drop anything. Failure mode = "flagged a line," never "structured it
wrong." (decline-over-guess, applied to import.)

PREVIEW ONLY: writes NOTHING to recipes.db, modifies no app files, builds no write layer.
It reuses the existing amount/fraction machinery from stepscale.py (imported, not copied —
see the ROADMAP note about extracting a shared public amounts.py later).

Run:  python3 import_cleanup.py
"""
import re
import zipfile
from collections import Counter
from pathlib import Path

# Reuse the EXISTING amount/fraction parser — do not write a third copy. These are
# underscore-private in stepscale today; importing them is an accepted temporary
# compromise (ROADMAP: extract a shared public amounts.py).
from stepscale import _NUM, _SCALE_UNIT, _to_value, _normalize_unicode

# The reader is our own preview tool (not an app file); reuse its archive walk + mapping.
import paprika_native_reader as reader

ARCHIVE = Path(__file__).resolve().parent / "My Recipes.paprikarecipes"

# --------------------------------------------------------------------------- #
# Regexes (built from the reused stepscale fragments)
# --------------------------------------------------------------------------- #
_RANGE = r"(?:to|[-–—])"

# Leading amount (optionally a range), an OPTIONAL measure unit (\b so bare "g" can't
# swallow the "g" in "garlic"), then the name. _NUM is required at the start, so a
# no-amount line ("Sea Salt") simply doesn't match.
_LEAD_RE = re.compile(
    r"^\s*(?P<amount>" + _NUM + r"(?:\s*" + _RANGE + r"\s*" + _NUM + r")?)"
    r"(?:\s*(?P<unit>" + _SCALE_UNIT + r")\b)?"
    r"\s*(?P<name>.*)$",
    re.IGNORECASE,
)
# A "N x SIZE" multiplier at the start ("2 x 6oz") — risky, flag it.
_MULT_RE = re.compile(r"^\s*" + _NUM + r"\s*[x×]\s*" + _NUM, re.IGNORECASE)
_RANGE_FIND = re.compile(r"\d\s*(?:to|[-–—])\s*\d", re.IGNORECASE)
_RANGE_SPLIT = re.compile(r"\s*(?:to|[-–—])\s*", re.IGNORECASE)

_EACH_RE = re.compile(r"\beach\b", re.IGNORECASE)
_ALT_RE = re.compile(r"\bor\b", re.IGNORECASE)

# Secondary/dual measure left at the START of the name after the primary amount is parsed:
# "2 tsp / 6 g salt" parses qty "2 tsp" and leaves "/ 6 g salt" as the name. Strip a LEADING
# "/ <amount> <unit>" so the label (and the future linkage key) is the clean ingredient name;
# raw_text keeps the original. A "/ 60 ml" deeper in the line (e.g. inside a note) is untouched.
_SECONDARY_MEASURE = re.compile(r"^/\s*" + _NUM + r"\s*" + _SCALE_UNIT + r"\b\s*", re.IGNORECASE)

# A lone trailing orphan "(" (e.g. "Thai tea mix (") is unbalanced source junk — strip it from
# the parsed name. Only a trailing "(" with nothing after it; a contentful/balanced paren is kept.
_DANGLING_PAREN = re.compile(r"\s*\($")

# A clean VOLUME-measure parenthetical on a dual-measure line — "(1 cup)", "(about 1 ¼ cups)",
# "(240 ml)". Strip it from the name and capture the volume. Matches only a paren whose WHOLE
# content is a volume measure, so "(light roast)" / "(1 cup, packed)" / a gram paren are left be.
_VOL_UNIT = r"(?:tablespoons?|teaspoons?|millilit(?:re|er)s?|lit(?:re|er)s?|cups?|tbsp|tsp|ml|l)"
_VOLUME_PAREN = re.compile(
    r"\(\s*(?:about\s+|~\s*)?(" + _NUM + r"\s*" + _VOL_UNIT + r")\s*\)", re.IGNORECASE)
# Leading-amount unit buckets for dual-measure capture (grams = weight, secondary = volume).
_WEIGHT_LEAD_UNITS = {"g", "gram", "grams"}
_VOLUME_LEAD_UNITS = {"cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon",
                      "teaspoons", "ml", "millilitre", "millilitres", "milliliter", "milliliters",
                      "l", "litre", "litres", "liter", "liters"}

# Parenthetical-grams harvest: find a complete (...) group, then a gram value inside it.
# A dangling "(" never forms a group, so it's silently ignored (no crash, no harvest).
_PAREN_GROUP = re.compile(r"\(([^)]*)\)")
_GRAMS_IN = re.compile(r"(\d+(?:\.\d+)?)\s*g(?:rams?)?\b", re.IGNORECASE)
# Volume-unit words that, inside a gram parenthetical, mean the grams describe a SUB-measure
# ("1/2 cup (15g) once soaked"), not the line's primary amount — the guard declines those.
_VOL_WORDS = re.compile(r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|ml|fl)\b", re.I)

# Prep-note detector — INFORMATIONAL only; the name is kept whole (weights.normalize
# already drops the trailing ", <prep>" clause for the linkage key, non-destructively).
_PREP = re.compile(
    r"\b(minced|chopped|sliced|diced|crushed|peeled|grated|halved|quartered|divided|"
    r"crumbled|melted|softened|beaten|cubed|julienned|trimmed|drained|rinsed|shredded|"
    r"seeded|deboned|sifted|packed|room temperature|finely|roughly|thinly)\b", re.I)

# Servings: an exact bare integer is accepted whole; otherwise a number must be adjacent
# to a servings word (never a stray pan-size number). Longest words first.
_BARE_INT_RE = re.compile(r"^\s*(\d+)\s*$")
_SERV_WORD_RE = re.compile(
    r"(?:servings|serving|serves|makes?|portions?)\s*:?\s*(\d+)"
    r"|(\d+)\s*(?:servings?|portions?)\b",
    re.IGNORECASE)

# --- Header detection (Steps 1 & 2) ---
# A STEP line ending in a trailing dash is a heading ("prepare your pan -"). Archive scan found
# NO real instruction ends in a dash, so the dash alone is a safe heading signal; strip it.
_TRAILING_DASH = re.compile(r"\s*[-–—]\s*$")
# Bare lowercase ingredient section-headers: a NARROW common-section-word list (primary signal),
# plus a same-recipe step-section mirror (secondary). Conservative — every promotion is FLAGGED.
_COMMON_SECTION_WORDS = frozenset({
    "crust", "filling", "topping", "sauce", "dough", "batter", "base", "marinade",
    "glaze", "frosting", "icing", "streusel", "crumble", "coating", "assembly",
    "garnish", "dressing", "syrup",
})
_STEP_HEADING_PREFIX = re.compile(
    r"^(?:to\s+)?(?:make|prepare|assemble|finish|build|cook|for)\s+(?:the\s+)?", re.IGNORECASE)

# --- Canned goods: COUNT + CONTAINER unit + SIZE (any delimiter) ---
# One unified rule for "1 can (15 ounces) chickpeas", "1 (12-ounce) can milk", "1 8-ounce package
# cheese", and the x-form "1 x 397 g can …" -> qty "N <container>", grams from the SIZE (oz->g),
# clean name. SUBSUMES the old N=1 multiplier rule. N>1 containers resolve too (the count is the
# scalable unit: 2 cans -> 4 cans). A bare "N x SIZE thing" with NO container still flags.
_CONT = r"(?:cans?|jars?|packages?|pkgs?|boxes|box|bottles?|tins?|tubs?|containers?|bags?)"
_WT_UNIT = r"(?:ounces?|oz|grams?|g|pounds?|lbs?|lb|kilograms?|kg)"
# a weight SIZE: number + weight unit (allows the hyphen in "8-ounce"), optional dual "/ 600g".
_SIZE = r"\d+(?:\.\d+)?\s*-?\s*" + _WT_UNIT + r"(?:\s*[./]\s*\d+(?:\.\d+)?\s*(?:grams?|g)\b)?"
_CANNED_X = re.compile(r"^\s*(?P<count>" + _NUM + r")\s*[x×]\s*(?P<size>" + _SIZE + r")\s+"
                       r"(?P<unit>" + _CONT + r")\b\s+(?:of\s+)?(?P<rest>\S.*)$", re.IGNORECASE)
_CANNED_UP = re.compile(r"^\s*(?P<count>" + _NUM + r")\s+(?P<unit>" + _CONT + r")\s*\(\s*"
                        r"(?P<size>" + _SIZE + r")[^)]*\)\s*(?:of\s+)?(?P<rest>\S.*)$", re.IGNORECASE)
_CANNED_PU = re.compile(r"^\s*(?P<count>" + _NUM + r")\s*\(\s*(?P<size>" + _SIZE + r")[^)]*\)\s*"
                        r"(?P<unit>" + _CONT + r")\b\s*(?:of\s+)?(?P<rest>\S.*)$", re.IGNORECASE)
_CANNED_HY = re.compile(r"^\s*(?P<count>" + _NUM + r")\s+(?P<size>" + _SIZE + r")\s+"
                        r"(?P<unit>" + _CONT + r")\b\s*(?:of\s+)?(?P<rest>\S.*)$", re.IGNORECASE)
_WT_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(ounces?|oz|grams?|g|pounds?|lbs?|lb|kilograms?|kg)\b", re.I)
_OZ_TO_G = {"ounce": 28.35, "ounces": 28.35, "oz": 28.35, "gram": 1.0, "grams": 1.0, "g": 1.0,
            "pound": 453.592, "pounds": 453.592, "lb": 453.592, "lbs": 453.592,
            "kilogram": 1000.0, "kilograms": 1000.0, "kg": 1000.0}


# --------------------------------------------------------------------------- #
# Subsystems
# --------------------------------------------------------------------------- #
def is_section(text):
    """Reliable section header: colon-terminated OR all-caps (with letters). Callers only
    ask this for NO-amount lines, so a quantity line is never mistaken for a section."""
    t = text.strip()
    if not t:
        return False
    if t.endswith(":"):
        return True
    return any(c.isalpha() for c in t) and t == t.upper()


def parse_amount(line):
    """Leading amount/unit/name split. Returns (amount_text, value, unit, name, range).
    range is (lo, hi) for "N–M"/"N to M", else None; value is None for a range."""
    m = _LEAD_RE.match(line)
    if not m:
        return "", None, "", line.strip(), None
    amount = m.group("amount").strip()
    unit = (m.group("unit") or "").strip()
    name = (m.group("name") or "").strip()
    if _RANGE_FIND.search(amount):
        parts = _RANGE_SPLIT.split(amount, maxsplit=1)
        try:
            lo = _to_value(_normalize_unicode(parts[0]))
            hi = _to_value(_normalize_unicode(parts[1]))
            return amount, None, unit, name, (lo, hi)
        except (ValueError, ZeroDivisionError, IndexError):
            return amount, None, unit, name, None
    try:
        value = _to_value(_normalize_unicode(amount))
    except (ValueError, ZeroDivisionError):
        value = None
    return amount, value, unit, name, None


def _strip_secondary_measure(name):
    """Strip a LEADING secondary measure ('/ 6 g …') the primary-amount parse left at the
    front of the name on a dual-unit line. Returns (clean_name, stripped_fragment|None); only
    the leading one is removed and the original survives in raw_text (caller never loses it)."""
    m = _SECONDARY_MEASURE.match(name)
    if not m:
        return name, None
    return name[m.end():].strip(), m.group(0).strip()


def harvest_grams(text):
    """Authoritative grams from a weight-focused "(NNN g/grams)". Returns
    (grams, declined, gram_paren): grams is the float harvested or None; declined is True when a
    gram value WAS present in a paren but the confidence guard rejected it (nothing harvested) —
    so the caller can flag what we decline; gram_paren is the FULL matched "(NNN g)" substring
    that was harvested (so the caller can strip it from the name), else None.

    Paren-safe: a dangling/unclosed "(" forms no group and is ignored (no crash, no harvest).
    CONFIDENCE GUARD: harvest only when the gram paren is weight-only — no volume-unit words
    and no other numbers — so "1/2 cup (15g) once soaked" declines instead of mis-harvesting."""
    saw_gram = False
    for grp in _PAREN_GROUP.finditer(text or ""):
        content = grp.group(1)
        m = _GRAMS_IN.search(content)
        if not m:
            continue
        saw_gram = True
        if _VOL_WORDS.search(content):
            continue
        if [n for n in re.findall(r"\d+(?:\.\d+)?", content) if n != m.group(1)]:
            continue
        try:
            return float(m.group(1)), False, grp.group(0)
        except ValueError:
            pass
    return None, saw_gram, None


def _strip_gram_paren(name, gram_paren):
    """Remove the exact harvested gram parenthetical (e.g. '(250g)') from the name and collapse
    the gap it leaves — so '(250g) dried chickpeas' -> 'dried chickpeas'. ONLY the harvested
    paren is removed; a contentful paren like '(light roast)' is left untouched."""
    if not gram_paren:
        return name
    return re.sub(r"\s+", " ", name.replace(gram_paren, "", 1)).strip()


def _strip_volume_paren(name):
    """Strip a clean VOLUME parenthetical ('(1 cup)', '(about 1 ¼ cups)', '(240 ml)') from the
    name and return (clean_name, volume_text|None). Only a paren whose WHOLE content is a volume
    measure is removed — a contentful paren like '(light roast)' or '(1 cup, packed)' is kept."""
    m = _VOLUME_PAREN.search(name)
    if not m:
        return name, None
    cleaned = re.sub(r"\s+", " ", name[:m.start()] + name[m.end():]).strip()
    return cleaned, m.group(1).strip()


def _dual_measure(amount, value, unit, name, grams):
    """Capture a dual-measure line's two measures, EITHER order. Returns
    (clean_name, grams, secondary_measure). Net rule: grams = the WEIGHT (the paren-harvested gram,
    else the leading amount when its unit is grams); secondary_measure = the VOLUME (a clean volume
    paren stripped from the name, else the leading amount when it's a volume on a line that also
    carries a weight); name = clean. The caller's raw_text keeps the full original."""
    name, volume = _strip_volume_paren(name)
    u = (unit or "").lower()
    if grams is None and value is not None and u in _WEIGHT_LEAD_UNITS:
        grams = value                                    # weight-first: the gram IS the leading amount
    secondary = volume                                   # weight-first / metric-volume: from the paren
    if secondary is None and grams is not None and u in _VOLUME_LEAD_UNITS:
        secondary = ("%s %s" % (amount, unit)).strip()   # volume-first dual: the leading volume
    return name, grams, secondary


def parse_servings(raw):
    """Exact bare integer -> accept; else a number adjacent to a servings word -> accept;
    else BLANK (never a stray number like a pan size)."""
    if not raw:
        return None
    s = raw.strip()
    m = _BARE_INT_RE.match(s)
    if m:
        return int(m.group(1))
    m = _SERV_WORD_RE.search(s)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def classify_step(text):
    """A direction line -> (is_heading, clean_text). Heading if colon-terminated / ALL-CAPS
    (is_section) OR ending in a trailing dash ("prepare your pan -"); the trailing dash is
    stripped. STEPS only — never applied to ingredient lines."""
    t = (text or "").strip()
    if _TRAILING_DASH.search(t):
        return True, _TRAILING_DASH.sub("", t).strip()
    return is_section(t), t


def _section_key(text):
    """Normalize a line to a comparable key: lowercase, alphanumerics + single spaces only."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def _step_heading_key(text):
    """A step heading -> its core-noun key, stripping a leading verb phrase ("make the crust"
    -> "crust"), so a step section can be mirrored onto a matching ingredient header."""
    return _section_key(_STEP_HEADING_PREFIX.sub("", (text or "").strip()))


def _is_section_candidate(line, hints):
    """Narrow, conservative test for a bare lowercase ingredient section-header: SHORT (<=3
    words, no amount) AND its key ENDS WITH a common section word (head-noun match: "lemon glaze"
    -> glaze, "habanero syrup" -> syrup) OR it mirrors a same-recipe step-section (hints). Bias
    to NOT promote — a wrongly-promoted ingredient disappears from the list, the worse error; the
    <=3-word bound keeps a longer line that merely CONTAINS a section word from promoting."""
    key = _section_key(line)
    if not key or len(key.split()) > 3:
        return False
    return key.split()[-1] in _COMMON_SECTION_WORDS or key in (hints or frozenset())


def _size_to_grams(size):
    """A canned-good SIZE ('15 ounces', '12-ounce', '21 oz / 600g') -> grams. Prefer an explicit
    gram token (a dual 'oz / g' -> take the grams); else convert oz/lb/kg. None if no weight."""
    toks = _WT_TOKEN.findall(size or "")
    if not toks:
        return None
    for num, unit in toks:
        if unit.lower() in ("g", "gram", "grams"):
            return float(round(float(num)))
    num, unit = toks[0]
    return float(round(float(num) * _OZ_TO_G[unit.lower()]))


def _parse_canned(line):
    """Unified canned-good parse: COUNT + CONTAINER + SIZE across delimiters (x / paren / hyphen).
    Returns a res-update — qty 'N <container>', grams from the SIZE (oz->g), name = the thing
    (alternatives/prep kept) — or None if it's not a canned-good shape (caller falls through).
    N>1 resolves WITHOUT flagging (the count is the scalable unit); raw_text keeps the original."""
    for rx in (_CANNED_X, _CANNED_UP, _CANNED_PU, _CANNED_HY):
        m = rx.match(line)
        if not m:
            continue
        grams = _size_to_grams(m.group("size"))
        if grams is None:          # the matched paren/segment wasn't a real weight size -> skip
            continue
        count = m.group("count").strip()
        try:
            value = _to_value(_normalize_unicode(count))
        except (ValueError, ZeroDivisionError):
            value = None
        return {"amount": count, "value": value, "unit": m.group("unit").lower(),
                "name": m.group("rest").strip(), "grams_harvested": grams}
    return None


def classify_line(raw, section_hints=None):
    """Turn one raw ingredient line into a structured-or-flagged record."""
    line = raw.strip()
    grams, grams_declined, gram_paren = harvest_grams(line)
    res = {
        "raw": raw, "kind": "ingredient", "amount": "", "value": None, "unit": "",
        "name": line, "range": None, "grams_harvested": grams,
        "has_alternative": False, "has_prep_note": False, "secondary_measure": None,
        # grams_declined: a gram value was present but the guard didn't trust it — flag what we
        # decline, never silently drop it. Soft signal: doesn't by itself flag the line.
        "flags": ["grams_declined"] if grams_declined else [],
        "flag_reason": "", "suggestion": None,
    }

    # 1. Canned good: COUNT + CONTAINER + SIZE (paren / hyphen / x) -> qty "N container" + grams
    #    (subsumes the N x SIZE can case). N>1 resolves (the count is the scalable unit).
    canned = _parse_canned(line)
    if canned:
        res.update(canned)
        res["has_alternative"] = bool(_ALT_RE.search(res["name"]))
        res["has_prep_note"] = bool(_PREP.search(res["name"]))
        return res

    # 2. Bare N x SIZE multiplier (NO container) -> genuinely ambiguous, flag for review.
    if _MULT_RE.match(line):
        res["kind"] = "flagged"
        res["flags"].append("multiplier")
        res["flag_reason"] = "N x SIZE multiplier — ambiguous semantics, review"
        res["has_alternative"] = bool(_ALT_RE.search(line))
        return res

    amount, value, unit, name, rng = parse_amount(line)

    # 2. Has a leading amount -> ingredient (then layer on informational signals): the "/ N unit"
    #    slash secondary, then dual-measure capture (a "(1 cup)" / "(250 g)" paren — grams = weight,
    #    secondary_measure = volume, name cleaned, either order). raw_text keeps the original.
    if amount:
        name, slash_secondary = _strip_secondary_measure(name)
        name = _DANGLING_PAREN.sub("", name)         # drop a lone trailing orphan "("
        name = _strip_gram_paren(name, gram_paren)   # drop the harvested "(NNN g)" paren
        name, grams, secondary = _dual_measure(amount, value, unit, name, grams)
        res.update(amount=amount, value=value, unit=unit, name=name, range=rng)
        res["grams_harvested"] = grams
        res["secondary_measure"] = secondary or slash_secondary
        res["has_alternative"] = bool(_ALT_RE.search(name))
        res["has_prep_note"] = bool(_PREP.search(name))
        if _EACH_RE.search(line):
            res["kind"] = "flagged"
            res["flags"].append("each_multi")
            res["flag_reason"] = "'each' distributes one amount over several ingredients — review"
        return res

    # 3. No amount, but a reliable section header (colon-terminated / ALL-CAPS).
    if is_section(line):
        res["kind"] = "section"
        return res

    # 3b. No amount; matches a NARROW section signal (a common section word, or a same-recipe
    #     step-section mirror) -> treat as a section header, but FLAG it for confirmation.
    if _is_section_candidate(line, section_hints):
        res["kind"] = "section"
        res["flags"].append("section_suggested")
        res["flag_reason"] = "no amount, matches section pattern — treated as section header, confirm"
        return res

    # 4. No amount, not a clear section -> ambiguous; suggest (never decide).
    res["kind"] = "flagged"
    res["flags"].append("ambiguous_section")
    low = line.lower()
    res["suggestion"] = "section" if low.startswith(("for ", "to ")) else "ingredient"
    res["flag_reason"] = "no amount and not clearly a section — suggest %s" % res["suggestion"]
    res["has_alternative"] = bool(_ALT_RE.search(line))
    return res


def clean_recipe(norm):
    """Map a normalized recipe -> structured/flagged result. Carries every field through;
    drops nothing; flags incompletes at the recipe level."""
    directions = [s.strip() for s in (norm["directions"] or "").split("\n") if s.strip()]
    # step-section headings -> hint words, so a bare ingredient header that mirrors a step section
    # (e.g. "Habanero Syrup" ~ the "Habanero Syrup -" step) can be promoted (secondary signal, 3b).
    hints = {_step_heading_key(t) for t in directions if classify_step(t)[0]} - {""}
    ings = [classify_line(ln, hints) for ln in norm["ingredient_lines"]]
    has_img = bool(norm.get("images") or norm.get("primary_photo"))
    no_ing = len(norm["ingredient_lines"]) == 0
    no_dir = len(directions) == 0
    flags = []
    if no_ing:
        flags.append("no_ingredients")
    if no_dir:
        flags.append("no_directions")
    if no_ing and no_dir and has_img:
        flags.append("photo_only")
    return {
        "name": norm["name"], "uid": norm["uid"], "hash": norm["hash"],
        "servings": parse_servings(norm["servings_raw"]),
        "servings_raw": norm["servings_raw"],
        "categories": norm["categories"], "source": norm["source"],
        "source_url": norm["source_url"], "notes": norm["notes"],
        "description": norm["description"], "rating": norm["rating"],
        "times": {"prep": norm["prep_time"], "cook": norm["cook_time"], "total": norm["total_time"]},
        "ingredients": ings,
        "directions": directions,
        "images": norm["images"],
        "recipe_flags": flags,
        "review_count": sum(1 for i in ings if i["kind"] == "flagged"),
    }


# --------------------------------------------------------------------------- #
# Preview (writes nothing)
# --------------------------------------------------------------------------- #
TARGETS = [
    ("acqua pazza", "Acqua Pazza — sections, range, N x SIZE, alternatives"),
    ("blueberry muffin sugar cookies", "Blueberry Muffin Sugar Cookies — parenthetical grams + unicode fractions"),
    ("thai tea ice cream", "Thai Tea Ice Cream — dangling open paren (must not crash/harvest)"),
    ("panang curry", "Panang Curry — 'each' multi-ingredient + no-amount ambiguous lines"),
    ("beef and pepper", "Beef and Pepper Stir-Fry — all-caps colon sections"),
    ("blueberry muffins", "Blueberry Muffins — stub (photo-only)"),
]


def trunc(s, n=66):
    s = " ".join(str(s if s is not None else "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def fmt_line(d):
    ann = []
    if d["range"]:
        ann.append("range=%s–%s" % d["range"])
    if d["grams_harvested"] is not None:
        ann.append("grams=%g" % d["grams_harvested"])
    if "grams_declined" in d["flags"]:
        ann.append("grams-declined")
    if d["has_alternative"]:
        ann.append("alt")
    if d["has_prep_note"]:
        ann.append("prep")
    if d.get("secondary_measure"):
        ann.append("2nd=%s" % d["secondary_measure"])
    tail = ("   [" + ", ".join(ann) + "]") if ann else ""
    if d["kind"] == "section":
        return "[SECTION   ] %s" % d["raw"].strip()
    if d["kind"] == "flagged":
        sug = " ->%s" % d["suggestion"] if d["suggestion"] else ""
        blocking = [f for f in d["flags"] if f != "grams_declined"]  # grams-declined shown in tail
        parsed = "  {amt=%r unit=%r}" % (d["amount"], d["unit"]) if d["amount"] else ""
        return "[FLAGGED   ] (%s%s) %s%s%s\n             reason: %s" % (
            ",".join(blocking), sug, trunc(d["name"]), parsed, tail, d["flag_reason"])
    return "[INGREDIENT] amt=%-8r unit=%-7r | %s%s" % (d["amount"], d["unit"], trunc(d["name"], 48), tail)


def print_recipe(r, label):
    print("\n" + "=" * 88)
    print("%s" % label)
    print("  name=%s" % r["name"])
    print("=" * 88)
    print("  servings : %s   (raw %r)" % (r["servings"] if r["servings"] is not None else "BLANK", r["servings_raw"]))
    print("  recipe_flags: %s    review_count: %d" % (r["recipe_flags"] or "none", r["review_count"]))
    print("  ingredients (%d):" % len(r["ingredients"]))
    for d in r["ingredients"]:
        print("    " + fmt_line(d))
    if not r["ingredients"]:
        print("    (none)")
    print("  directions: %d step-line(s) carried as-is" % len(r["directions"]))


def print_summary(results):
    lines = [d for r in results for d in r["ingredients"]]
    kinds = {k: sum(d["kind"] == k for d in lines) for k in ("ingredient", "section", "flagged")}
    flagtypes = Counter(f for d in lines for f in d["flags"] if f != "grams_declined")
    declined = sum("grams_declined" in d["flags"] for d in lines)
    grams = sum(d["grams_harvested"] is not None for d in lines)
    servings_ok = sum(r["servings"] is not None for r in results)
    print("\n" + "=" * 88)
    print("SAMPLE SUMMARY (%d recipes)" % len(results))
    print("=" * 88)
    print("  line kinds       : %s" % kinds)
    print("  flag types       : %s" % (dict(flagtypes) or "none"))
    print("  grams harvested  : %d line(s)   (declined low-confidence: %d)" % (grams, declined))
    print("  servings parsed  : %d   blank: %d" % (servings_ok, len(results) - servings_ok))
    print("  recipe_flags     : %s" % {r["name"]: r["recipe_flags"] for r in results if r["recipe_flags"]})


def collect_samples(zf):
    """Scan the archive once; return {label: cleaned recipe} for the TARGETS found."""
    found = {}
    for _name, rec, err in reader.iter_entries(zf):
        if err or not rec:
            continue
        nm = reader.strip_quotes(rec.get("name") or "").lower()
        for sub, label in TARGETS:
            if sub in nm and label not in found:
                found[label] = clean_recipe(reader.normalize(rec))
    return found


def main():
    if not ARCHIVE.is_file():
        raise SystemExit("Archive not found: %s" % ARCHIVE)
    print("IMPORT CLEANUP CORE — preview only (writes nothing; archive read in memory)")

    with zipfile.ZipFile(ARCHIVE) as zf:
        found = collect_samples(zf)

    results = []
    for sub, label in TARGETS:
        if label in found:
            print_recipe(found[label], label)
            results.append(found[label])
        else:
            print("\n(sample not found: %s)" % label)

    print_summary(results)


if __name__ == "__main__":
    main()
