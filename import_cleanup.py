#!/usr/bin/env python3
"""import_cleanup.py — the source-agnostic IMPORT CLEANUP CORE (preview only).

Takes ONE normalized recipe (the shape emitted by paprika_native_reader.normalize)
and returns structured-or-flagged data. It is the format-agnostic half of Phase 15:
it neither knows nor cares that the source is Paprika.

GUIDING PRINCIPLE: aggressive = extract every CLEAR win, FLAG the ambiguous/risky ones
for review — never force-parse in a way that could corrupt data or break library linkage,
and never silently drop anything. Failure mode = "flagged a line," never "structured it
wrong." (decline-over-guess, applied to import.)

PURE: writes NOTHING and imports NOTHING source-specific. It reuses the existing
amount/fraction machinery from stepscale.py (imported, not copied — see the ROADMAP note
about extracting a shared public amounts.py later), and that is its whole dependency list.

⚠️ KEEP IT THAT WAY. app.py and build_db.py import split_qty from here, so every module-level
import in this file is paid on every Flask boot. The Paprika-shaped preview that used to live
at the bottom — with its `import paprika_native_reader`, `import zipfile` and hardcoded
ARCHIVE — is now import_cleanup_preview.py, which imports THIS module rather than the reverse.
A new source belongs in its own reader + preview, never here.
"""
import re

# Reuse the EXISTING amount/fraction parser — do not write a third copy. These are
# underscore-private in stepscale today; importing them is an accepted temporary
# compromise (ROADMAP: extract a shared public amounts.py).
from stepscale import _NUM, _SCALE_UNIT, _UNI, _to_value, _normalize_unicode, _canon_amount

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
# ONE EXCEPTION to that guard: a parenthetical whose WHOLE content is a delimited list of MEASURES
# ("16 Tbsp; 226g", "8 tablespoons/113 grams", "about 1½ cups/227 grams") is a single quantity written
# several ways, so the gram inside it IS the line's weight and the volume word beside it is not a
# sub-measure. The test is the ABSENCE OF PROSE, not the presence of a gram: any leftover word fails
# this anchored match and declines exactly as before —
#   "(from 1⅔ cups/300g uncooked)"                 an UNCOOKED weight on a cooked-rice line
#   "(you may need up to 1/2 cup / 60g for kneading)"  extra flour, not the line's 440 g
#   "(or 250g/8oz dried)"                          an ALTERNATIVE form of the ingredient
#   "(24 x 6cm/2.5\" long, 1/2 cup (15g) …"         nested paren + prose
# "each" is deliberately NOT an accepted tail: "(~250g/8oz each)" is a PER-UNIT weight on a 4-piece
# line, and this column holds LINE weights — accepting it stored 250 g for 1 kg of chicken.
_MEAS_NUM = (r"(?:\d+(?:\.\d+)?(?:\s*/\s*\d+)?|\d+\s+\d+/\d+|\d+\s*[" + _UNI + r"]|["
             + _UNI + r"])")
_MEAS_UNIT = (r"(?:grams?|g|kilograms?|kg|ounces?|oz|pounds?|lbs?|lb|cups?|tablespoons?|tbsp"
              r"|teaspoons?|tsp|millilit(?:re|er)s?|ml|lit(?:re|er)s?|l|sticks?)")
_MEAS = _MEAS_NUM + r"\s*" + _MEAS_UNIT
_HEDGE = r"(?:about|around|approx\.?|approximately|~)"
_MEAS_DELIM = r"(?:\s*[;/,]\s*|\s+or\s+)"
_MEASURE_LIST = re.compile(
    r"^\s*" + _HEDGE + r"?\s*" + _MEAS
    + r"(?:" + _MEAS_DELIM + _HEDGE + r"?\s*" + _MEAS + r")+"
    + r"(?:\s+total)?\s*$", re.IGNORECASE)

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
# --------------------------------------------------------------------------- #
# Source-text cleanup: repair publisher artifacts BEFORE parsing
# --------------------------------------------------------------------------- #
# A TABLE, not a chain of if-statements, because the point is ACCUMULATION. The sites this app will
# actually be fed — Allrecipes, ATK, Bon Appétit, Serious Eats — are large custom platforms that will
# emit their OWN artifacts, not the ones we happen to have sampled. Adding a rule is one tuple here
# plus one test; nothing else in the pipeline changes.
#
# THE BAR FOR ADMITTING A RULE — deliberately high, because a wrong rule silently rewrites the user's
# ingredients:
#   1. UNAMBIGUOUS. No human writes the shape deliberately, so there is no intent to misread.
#   2. CORPUS-NEUTRAL. It must match ZERO stored Paprika rows, or it changes recipes already imported.
#      Check before adding:  SELECT raw_text FROM recipe_ingredients WHERE raw_text LIKE '%<shape>%'
#   3. FLAGGED. Every application records an import_flags row, so the tidying is visible, never silent.
# Shapes that need INTERPRETATION stay out — "1/2 cup - 1 cup" (range or compound measure?) and
# "Fresh green chilis - Serranos" (note or hyphenated name?) are for the import editor, not a regex.
#
# ⚠️ ONLY the parsed NAME is cleaned. `raw` is untouched and becomes recipe_ingredients.raw_text, so the
# publisher's original text is always recoverable — the cleanup is a display/parse improvement, not an
# edit to the source record.
CLEANUP_RULES = (
    # (flag, pattern, replacement, reason recorded on the flag row)
    #
    # Both rules repair the SAME template defect from opposite ends: recipetineats joins an empty
    # ingredient-name field to a note. When the note opens with a comma you get "(, vegetable";
    # when the note already carries its own brackets you get "((Note 4))".
    ("cleaned_paren_comma", re.compile(r"\(\s*,\s*"), "(",
     "removed a stray comma after '(' — publisher artifact"),

    # MATCHES THE PAIR, NEVER THE PREFIX. The pattern requires the doubled OPEN, content with no
    # parens of its own, AND the doubled CLOSE — so it fires only on a complete redundant wrapper and
    # rewrites both ends together. Collapsing on "((" alone would turn "((Note 4))" into "(Note 4))"
    # and strand a bracket.
    #
    # Three things it therefore declines, by construction rather than by special case:
    #   "((Note 4)"        unbalanced — one ')' — left exactly as found, not half-fixed
    #   "(Note 4))"        unbalanced the other way — likewise untouched
    #   "(or rice wine (mijiu) if you can find it (Note 5))"
    #                      LEGITIMATE nesting: the inner paren doesn't span the whole content, so
    #                      [^()]* fails and the line is left alone. This one is real recipetineats
    #                      text — collapsing it would merge two different brackets into one.
    # "( (" is the same shape with a stray space and is handled by the same pattern (\s* after the
    # first paren), so it needs no rule of its own.
    ("cleaned_double_paren", re.compile(r"\(\s*\(([^()]*)\)\s*\)"), r"(\1)",
     "collapsed a doubled parenthesis — publisher artifact"),
)

# flag -> reason, for the writer's flag-row builder (import_write._line_flag_rows).
CLEANUP_REASONS = {flag: reason for flag, _rx, _repl, reason in CLEANUP_RULES}


def clean_source_text(text):
    """Apply every cleanup rule. Returns (cleaned_text, [flags applied]).

    Order-independent by construction: each rule is applied once to the running result, and a rule
    that changes nothing contributes no flag. A line matching two rules carries two flags."""
    applied = []
    for flag, rx, repl, _reason in CLEANUP_RULES:
        new = rx.sub(repl, text)
        if new != text:
            applied.append(flag)
            text = new
    return text, applied


def is_section(text):
    """Reliable section header: colon-terminated OR all-caps (with letters). Callers only
    ask this for NO-amount lines, so a quantity line is never mistaken for a section."""
    t = text.strip()
    if not t:
        return False
    if t.endswith(":"):
        return True
    return any(c.isalpha() for c in t) and t == t.upper()


# Markdown emphasis wrapping a WHOLE line ("**Other Ingredients:**", "_Vanilla Icing_"): a matched
# pair of leading+trailing markers around the entire line. Stripped so a bold/italic colon-heading
# is DETECTED and STORED clean. Only a WRAPPING pair matches — a trailing-only footnote ("salt*") or
# mid-line emphasis ("2 cups **sifted** flour") has no matched leading+trailing wrap, so it is left
# untouched. Backreference \1 requires the SAME marker on both ends.
_EMPHASIS_WRAP = re.compile(r"^(\*\*|__|\*|_)(.+?)\1$")


def strip_emphasis(text):
    """Strip a matched pair of leading+trailing emphasis markers (** __ * _) wrapping the ENTIRE
    line and return the inner text; no wrapping pair -> the (whitespace-stripped) text unchanged."""
    t = (text or "").strip()
    m = _EMPHASIS_WRAP.match(t)
    return m.group(2).strip() if m else t


# --- Extra amount-less section signals (section_signal, below) ---------------------------------- #
# Four corpus-verified heading patterns beyond the colon/ALL-CAPS is_section. ALL are SAFE because
# section_signal is only ever called on NO-AMOUNT lines (classify_line block 2 returns amount-bearing
# lines as ingredients FIRST), so an amount-bearing "egg wash"/"filling"/etc. can never reach here —
# the asymmetric-bad error (promoting a real ingredient so it vanishes from the list) is structurally
# prevented. Each was checked false-positive-free across the whole corpus.
_INGREDIENTS_WORD = re.compile(r"\bingredients?\b", re.I)   # Rule 1: a meta-word naming the list
_DAY_N = re.compile(r"^\W*day\s+\d", re.I)                  # Rule 3: stage label ("Day 1", "**Day 3+**")
# Rule 2: exact whole-line measurement-system labels (a units-variant block header).
_UNIT_SYSTEM_LABELS = frozenset({
    "metric", "imperial", "us", "us customary", "metric units", "imperial units", "us units",
})
# Rule 4: preparations MADE FROM the ingredients below and NEVER themselves an ingredient — so an
# amount-less line that is/ends-in one is always a header, false-positive-free by construction.
# Deliberately the PURELY-PREP core only: words that ALSO live in block 3b's _COMMON_SECTION_WORDS
# (filling/glaze/topping/marinade/streusel) are left to _is_section_candidate, which has a ≤3-word
# guard this guard-less ends-in match lacks ("spread the filling evenly" must not promote). Food words
# ("sauce"/"potatoes"/"salsa"), count-nouns ("loaves"), and untested words (batter/roux/coating) excluded.
_PREP_COMPONENTS = frozenset({"egg wash", "dredge", "sponge", "brine"})


def section_signal(text):
    """Is this (already emphasis-stripped, amount-less) line a section heading? True if the existing
    is_section logic OR one of four corpus-verified patterns matches. Used by classify_line (block 3)
    and the heading backfill; is_section itself is left pure (colon / ALL-CAPS only)."""
    if is_section(text):                                   # colon-terminated / ALL-CAPS (short-circuit)
        return True
    t = text.strip()
    if not t:
        return False
    if _INGREDIENTS_WORD.search(t):                        # Rule 1 — "X Ingredients" (meta-word)
        return True
    if t.lower() in _UNIT_SYSTEM_LABELS:                   # Rule 2 — unit-system label (exact line)
        return True
    if _DAY_N.match(t):                                    # Rule 3 — "Day N" stage label
        return True
    norm = t.lower().rstrip(":").strip()                   # Rule 4 — prep-component allowlist
    if norm in _PREP_COMPONENTS or any(norm.endswith(" " + w) for w in _PREP_COMPONENTS):
        return True                                        # whole-word end match ("Flour Dredge"); no mid-word hit
    return False


def parse_amount(line):
    """Leading amount/unit/name split. Returns (amount_text, value, unit, name, range).
    range is (lo, hi) for "N–M"/"N to M", else None; value is None for a range."""
    m = _LEAD_RE.match(line)
    if not m:
        return "", None, "", line.strip(), None
    # _canon_amount collapses a connective spelling ("1 and 1/2") to the canonical mixed number
    # ("1 1/2"). It must run HERE, before both the range branch and _to_value, because everything
    # downstream — the value, the stored quantity, the client scaler — reads this string. See its
    # docstring for why the source spelling is not kept.
    amount = _canon_amount(m.group("amount"))
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


# A count-noun / size descriptor left after a leading number ("cloves", "large", "medium head",
# "large handfuls"): letters + spaces/hyphens only, no digits/operators/slashes. Distinguishes a
# real count unit from irreducible trailing junk ("/ 1 kg", "+ 2 tbsp").
_COUNTNOUN_RE = re.compile(r"^[A-Za-z][A-Za-z .\-]*$")


def _norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def split_qty(qty):
    """Split a stored free-text `qty` into (quantity_expression, unit) for the additive qty/unit
    columns — reusing parse_amount, so the DB backfill and the seed-load path split IDENTICALLY.

      "2 tablespoons" -> ("2", "tablespoons")     number + measuring unit
      "1 1/2"         -> ("1 1/2", "")            number only (no unit)
      "2-3 cups"      -> ("2-3", "cups")          range keeps its expression in quantity
      "4 cloves"      -> ("4", "cloves")          count-noun becomes the unit
      "pinch"         -> ("pinch", "")            no leading number -> whole string, no unit
      "2 lb / 1 kg"   -> ("2 lb / 1 kg", "")      slash-dual: irreducible -> whole string
      "3 + 2 tbsp"    -> ("3 + 2 tbsp", "")       compound: irreducible -> whole string
      ""              -> ("", "")                 empty

    LOSSLESS BY CONSTRUCTION: quantity + " " + unit always recombines (whitespace-normalized) to
    the original qty; any split that wouldn't reconstruct it falls back to the whole string with
    unit="" rather than mis-structure. The original `qty` column is never touched by the caller."""
    s = (qty or "").strip()
    if not s:
        return "", ""
    amount, _value, unit, name, _rng = parse_amount(s)
    name = (name or "").strip()
    if not amount:
        q, u = s, ""                                   # no leading number (pinch, to taste, …)
    elif not name:
        q, u = amount, unit                            # clean "number [unit]" or number-only
    elif not unit and _COUNTNOUN_RE.match(name):
        q, u = amount, name                            # count-noun -> unit ("4 cloves")
    else:
        q, u = s, ""                                   # trailing junk (dual/compound) -> keep whole
    if _norm_ws(f"{q} {u}") != _norm_ws(s):            # safety: never mis-structure — recombine must hold
        return s, ""
    return q, u


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
    and no other numbers — so "1/2 cup (15g) once soaked" declines instead of mis-harvesting.
    ONE EXCEPTION, checked first: a _MEASURE_LIST paren ("16 Tbsp; 226g") restates one quantity,
    so its gram IS the line's weight — see the note above _MEASURE_LIST for what still declines.
    That path returns gram_paren=None, leaving the NAME untouched (moving the volume out of the
    name is a later stage; stripping only the gram would leave a malformed "(16 Tbsp;)")."""
    saw_gram = False
    for grp in _PAREN_GROUP.finditer(text or ""):
        content = grp.group(1)
        m = _GRAMS_IN.search(content)
        if not m:
            continue
        saw_gram = True
        if _MEASURE_LIST.match(content):
            # A restatement list: the gram IS the line's weight. Sibling oz/lb tokens are ignored —
            # this column stores GRAMS, so the metric token needs no conversion and no rounding
            # ("6 ounces/170 grams" -> 170.0). Two DIFFERENT gram values would be genuinely
            # ambiguous, so decline rather than guess (0 such rows in the corpus today).
            if len(set(_GRAMS_IN.findall(content))) == 1:
                try:
                    return float(m.group(1)), False, None
                except ValueError:
                    pass
            continue
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
    # Publisher artifacts are repaired BEFORE anything reads the line, so every downstream rule
    # (amount parse, gram harvest, section detection) sees well-formed text rather than each having
    # to tolerate the malformation. `raw` keeps the original for raw_text — see CLEANUP_RULES.
    line, cleanup_flags = clean_source_text(raw.strip())
    grams, grams_declined, gram_paren = harvest_grams(line)
    res = {
        "raw": raw, "kind": "ingredient", "amount": "", "value": None, "unit": "",
        "name": line, "range": None, "grams_harvested": grams,
        "has_alternative": False, "has_prep_note": False, "secondary_measure": None,
        # grams_declined: a gram value was present but the guard didn't trust it — flag what we
        # decline, never silently drop it. Soft signal: doesn't by itself flag the line.
        "flags": (["grams_declined"] if grams_declined else []) + cleanup_flags,
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

    # 3. No amount, but a reliable section header — section_signal: colon-terminated / ALL-CAPS
    #    (is_section) OR one of the 4 corpus-verified amount-less patterns ("X Ingredients", unit-system
    #    label, "Day N", prep-component allowlist). Possibly wrapped in whole-line emphasis
    #    ("**Other Ingredients:**", "**Day 1**"): strip the wrapper for BOTH the test and the stored
    #    text (res["name"]), so the heading is detected AND stored clean — reading renders the heading's
    #    raw_text and keys sections on it. The amount-less guard is free (block 2 already returned any
    #    amount-bearing line as an ingredient).
    stripped = strip_emphasis(line)
    if section_signal(stripped):
        res["kind"] = "section"
        res["name"] = stripped
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
    # Already a list of non-empty, stripped step lines — the reader owns that split, exactly as it
    # already owns ingredient_lines'. Copied so the cleaned result never aliases the reader's list.
    directions = list(norm["directions"] or [])
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


# Shared display helper — collapse whitespace and ellipsis-truncate. It lives in the CORE rather than
# with the preview that used to own it because import_write's dry-run printer calls it in nine places;
# it is pure, three lines, and carries no source-specific coupling, so it costs the app nothing.
def trunc(s, n=66):
    s = " ".join(str(s if s is not None else "").split())
    return s if len(s) <= n else s[:n - 1] + "…"
