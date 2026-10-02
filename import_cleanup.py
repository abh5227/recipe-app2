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
import json
import pathlib
import re

# Reuse the EXISTING amount/fraction parser — do not write a third copy. These are
# underscore-private in stepscale today; importing them is an accepted temporary
# compromise (ROADMAP: extract a shared public amounts.py).
from stepscale import _NUM, _SCALE_UNIT, _UNI, _to_value, _normalize_unicode, _canon_amount

from recipe_line_parser import MEASURE_ABBREV, _is_all_modifier

# ⚠️ THE LEADING UNIT IS A WIDER QUESTION THAN WHAT TO SCALE, and conflating the two was the bug.
#    _SCALE_UNIT comes from stepscale and answers "which quantities does the CLIENT SCALE". It is
#    mirrored in static/app.js and held there by tests/js/factor-sync.test.js, so it cannot be
#    widened from this side. Where an ingredient line's NAME BEGINS is a different question.
#    `1 pkg. cream cheese` has a leading unit whether or not anything scales it, and leaving the
#    `pkg.` on the front produced an ingredient called `pkg. cream cheese`.
#
#    ⚠️ SAME FAMILY AS THE PERIOD LEAK that produced `. ground pork`, and it hid for the same
#    reason: the calibration corpus was a Paprika export that spells units out. Measured on the
#    live catalog, 3 stored rows carry the unit into the label and all three are `tbs`.
#
#    ⚠️ `t` IS DELIBERATELY ABSENT. _LEAD_RE is IGNORECASE, so it cannot tell `t.` (teaspoon) from
#    `T.` (tablespoon), and guessing is a threefold error on a quantity. recipe_line_parser makes
#    the same exclusion for the same reason. Measured over the corpus: 0.1% of lines.
#
#    Longest-first so `pkgs` is never shadowed by `pkg`.
_LEAD_UNIT = (r"(?:" + _SCALE_UNIT + r"|"
              + "|".join(re.escape(u) for u in sorted(MEASURE_ABBREV, key=len, reverse=True))
              + r")")

# --------------------------------------------------------------------------- #
# Regexes (built from the reused stepscale fragments)
# --------------------------------------------------------------------------- #
_RANGE = r"(?:to|[-–—])"

# Leading amount (optionally a range), an OPTIONAL measure unit (\b so bare "g" can't
# swallow the "g" in "garlic"), then the name. _NUM is required at the start, so a
# no-amount line ("Sea Salt") simply doesn't match.
_LEAD_RE = re.compile(
    r"^\s*(?P<amount>" + _NUM + r"(?:\s*" + _RANGE + r"\s*" + _NUM + r")?)"
    # ⚠️ THE PERIOD AFTER AN ABBREVIATED UNIT BELONGS TO THE UNIT, NOT THE NAME. Without the
    #    optional "\.?" the \b matched between "oz" and ".", the period fell to the name, and
    #    "8 oz. ground pork" was stored with the label ". ground pork". A cook saw the period.
    #    It also blocked _SECONDARY_MEASURE below, which needs the name to START with "/", so
    #    "16 oz./500g spinach" kept its dual measure too. recipe_line_parser.py has done the
    #    same strip(".") on its own unit check since it was written.
    r"(?:\s*(?P<unit>" + _LEAD_UNIT + r")\b\.?)?"
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
_SECONDARY_MEASURE = re.compile(r"^/\s*" + _NUM + r"\s*" + _LEAD_UNIT + r"\b\s*", re.IGNORECASE)

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

    # A space in front of a comma or semicolon ("onion , roughly sliced"). recipetineats writes the
    # prep clause as its own field and joins it with a separator that keeps the leading space, so the
    # parsed NAME carries it and the reading view prints "onion , roughly sliced". 77 lines over 24
    # recipes. ⚠️ The source line is untouched: raw_text stores `raw`, and only the text the parser
    # reads comes through here.
    # ⚠️ THE COLLAPSE IS PART OF THE SAME RULE, not a second one. "butter, , melted" is one artifact
    # with a space in the middle of it; repairing only the space leaves "butter,, melted", which is
    # worse than what it started with. Applied to the running result, so the two fire in order.
    ("cleaned_space_before_comma", re.compile(r"[ \t]+([,;])"), r"\1",
     "removed a space before a comma — publisher artifact"),
    ("cleaned_double_comma", re.compile(r"([,;])\s*[,;]+"), r"\1",
     "collapsed a doubled comma — publisher artifact"),
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


# ⚠️ 'clove' IS A UNIT AND ALSO A FOOD, which is the whole difficulty. recipe_line_parser already
#    carries that fact (its FOOD_UNIT set) because the same word broke name extraction there. This
#    is the same problem one layer over: _LEAD_UNIT answers where the NAME begins, and it holds
#    measures only, so "1 clove garlic" kept the unit in the name and stored "clove garlic".
#
#    NOT added to _LEAD_UNIT. That set feeds a regex with an optional unit group, so "10 cloves (or
#    1/4 tsp ground cloves)" would match 'cloves' as the unit and leave "(or ...)" as the name,
#    deleting the ingredient. The decision needs to see what FOLLOWS the word, so it is made here in
#    plain Python where the guard is readable.
#
#    PLURAL BEFORE SINGULAR in the alternation, so "cloves" is never shadowed by "clove" leaving a
#    stray "s". The irregular plurals are spelled out for the same reason a bare +s would be wrong:
#    bunches, boxes, pinches.
#
#    ⚠️ 'dash' IS DELIBERATELY ABSENT. Every corpus line using it is "a dash of X" with no count, so
#    it never reaches this rule, and admitting it only adds a word that is also a cooking verb.
_COUNT_NOUNS = ("cloves", "clove", "sprigs", "sprig", "stalks", "stalk", "slices", "slice",
                "pinches", "pinch", "bunches", "bunch", "sticks", "stick", "pieces", "piece",
                "heads", "head", "jars", "jar", "bags", "bag", "boxes", "box", "ears", "ear",
                "fillets", "fillet", "cans", "can", "bulbs", "bulb",
                # Added with the size-word rule. 'handful' and 'package' each already held live
                # rows in the unit column that no rule here admitted, and 'tin' is the British
                # spelling of 'can', which has been admitted since the rule was written.
                "handfuls", "handful", "packages", "package", "tins", "tin")
_COUNT_ALT = "|".join(_COUNT_NOUNS)

# ⚠️ A SIZE WORD IS PART OF THE MEASUREMENT, NOT THE FOOD. "1 large egg" is one egg of a stated
#    size, and the size is what the count is counting, so it belongs beside the number and never in
#    the name. It combines with a counting noun when both are present ("1 large head of
#    cauliflower" measures in large heads) and stands alone when one is not ("1 large egg").
#    The three words are a closed set. The ingredient library holds 0 rows for any of them, so
#    there is nothing to look up and nothing that can drift.
_SIZE_WORDS = ("small", "medium", "large")
_SIZE_ALT = "|".join(_SIZE_WORDS)

# An OPTIONAL size word in front of the counting noun, so "small bunch of parsley" reads its whole
# unit in one match instead of leaving 'small' behind at the head of the name.
_COUNT_UNIT_LEAD = re.compile(
    r"^(?P<u>(?:(?:" + _SIZE_ALT + r")\s+)?(?:" + _COUNT_ALT + r"))\b[\s,]+(?:of\s+)?"
    r"(?P<rest>[A-Za-z].*)$", re.I)
# The trailing form carries a prep clause as often as not ("2 garlic cloves, minced"), so the noun
# is allowed a comma tail. `rest` is COMMA-FREE on purpose: without that, "10 cloves (or 1/4 tsp
# ground cloves)" would match its SECOND 'cloves' and leave "cloves (or 1/4 tsp ground" as the name.
_COUNT_UNIT_TRAIL = re.compile(
    r"^(?P<rest>[^,]+?)\s+(?P<u>" + _COUNT_ALT + r")(?P<tail>\s*,.*)?$", re.I)

# The size word on its own, for a line with no counting noun ("1 large egg") and for the trailing
# form, where the noun is lifted first and the size is left at the head of the name:
# "1 medium garlic clove" reaches clove + "medium garlic", then "medium clove" + "garlic".
_SIZE_LEAD_RE = re.compile(r"^(?P<size>" + _SIZE_ALT + r")\b[\s,]+(?P<rest>[A-Za-z].*)$", re.I)

# A count-noun / size descriptor left after a leading number ("cloves", "large", "medium head",
# "large handfuls"). Distinguishes a real count unit both from irreducible trailing junk
# ("/ 1 kg", "+ 2 tbsp") and from an ordinary word that names part of the food.
#
# ⚠️ IT USED TO BE `^[A-Za-z][A-Za-z .\-]*$`, ANY letters-only trailing word. That is a test of
#    SHAPE where the question is one of MEMBERSHIP, so it could not tell a unit from a noun and
#    admitted whatever a line happened to trail with. Restricting it to the two closed sets is the
#    whole rule now. Measured over live data before the change: 89 of the 459 distinct stored qty
#    values reach this branch, and all 89 still match, so no stored split moves.
#
# ⚠️ IT IS DEFINED HERE, NOT BESIDE parse_amount WHERE IT USED TO SIT, because it now reads
#    _SIZE_ALT and _COUNT_ALT and has to follow them.
_COUNTNOUN_RE = re.compile(
    r"^(?:(?:" + _SIZE_ALT + r")|(?:(?:" + _SIZE_ALT + r")\s+)?(?:" + _COUNT_ALT + r"))\.?$",
    re.I)


def _inside_parens(text, pos):
    """Is `pos` inside a parenthetical? A count noun there is an ASIDE, not the count.

    ⚠️ MEASURED, NOT PRECAUTIONARY. "3 scallions (cut into 2-inch long pieces, with the white and
    green parts separated)" otherwise read its trailing 'pieces' as the unit, deleting the word from
    a prep note and leaving "cut into 2-inch long,". The ingredient is scallions and the count is 3.
    It is the only line in the corpus that does this, and the mechanical all-improvement check
    passed it, because the name did shrink and does still name a food. Reading the 61 changed lines
    is what caught it.
    """
    return text.count("(", 0, pos) > text.count(")", 0, pos)


# ⚠️ THE COUNTING WORD IS PART OF THE FOOD HERE, not a measurement of it. A cinnamon stick is
# whole bark that you fish out of the pot; 'cinnamon' standing alone reads as the ground spice,
# which is a different ingredient used a different way. The shipped library agrees and holds them
# as separate rows, 'cinnamon stick' (Q30038886) and 'cinnamon' (Q28165).
#
# 'fennel bulb' is here for the same reason. The bulb is the vegetable and 'fennel' standing alone
# is as likely to mean the seed, which is a spice. The library holds all three: 'Fennel',
# 'fennel bulb', 'fennel seeds'.
#
# Measured over the 229 live lines where a counting word is lifted, these are the only two phrases
# whose lift changes WHICH FOOD the line names. Two more were read and deliberately LEFT as
# measurements: 'salmon fillet' (a fillet is a cut, and "2 fillets" is how you buy them) and
# 'lemongrass stalk' (no competing form exists, so a stalk is the measure). Everything else the
# scan turned up is a genuine measurement: a clove of garlic, a stalk of celery, a stick of butter,
# a slice of ginger, a head of cauliflower.
_IDENTITY_COMPOUNDS = ("cinnamon stick", "fennel bulb")
_IDENTITY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in _IDENTITY_COMPOUNDS) + r")s?\b", re.I)


def _lift_count_unit(unit, name):
    """No unit matched and the name carries a counting noun -> move it to the unit.

    Both word orders occur and both are in the live corpus: "2 cloves garlic" (the URL sources) and
    "2 garlic cloves" (Paprika). Returns (unit, name) unchanged whenever the guard does not hold.

    ⚠️ THE GUARD IS THE POINT. 'cloves' standing alone IS the spice, so it only becomes a unit when
    a real ingredient word sits beside it:
      "1 clove garlic (minced)"              -> clove  + "garlic (minced)"
      "2 garlic cloves, minced"              -> cloves + "garlic, minced"
      "10 cloves (or 1/4 tsp ground cloves)" -> unchanged, a paren is not an ingredient word
      "5 whole cloves"                       -> unchanged, 'whole' is a modifier and names nothing
      "2 Cloves"                             -> unchanged, nothing sits beside it
    The trailing case leans on recipe_line_parser._is_all_modifier rather than a second word list,
    so 'whole', 'ground' and 'large' are judged by the vocabulary that already proved itself there.

    ⚠️ A SIZE WORD IS LIFTED TOO, AND IT IS LIFTED LAST, so it can join a noun the trailing branch
    has already taken. "1 medium garlic clove" reaches clove + "medium garlic" and then becomes
    "medium clove" + "garlic". The leading branch needs no second step, because there the size word
    sits in front of the noun where _COUNT_UNIT_LEAD already reads it.
    """
    if unit or not name:
        return unit, name
    # ⚠️ THE FOOD KEEPS ITS COUNTING WORD when the two together name something the bare food does
    #    not. See _IDENTITY_COMPOUNDS. This runs before BOTH branches and before the size lift, so
    #    "2 inch cinnamon stick" and "1 Chinese cinnamon stick" are held whole as well.
    if _IDENTITY_RE.search(name):
        return unit, name
    lead = _COUNT_UNIT_LEAD.match(name)
    if lead:
        rest = lead.group("rest").strip()
        # The same modifier test the trailing branch runs, and it earns its place: "3 cloves, whole"
        # otherwise became clove-the-unit with "whole" as the ingredient. No live line has that shape,
        # so only an invented case caught it.
        if rest and not _is_all_modifier(rest.lower()):
            return lead.group("u"), rest
    trail = _COUNT_UNIT_TRAIL.match(name)
    if trail and not _inside_parens(name, trail.start("u")):
        rest = trail.group("rest").strip(" ,")
        if rest and not _is_all_modifier(rest.lower()):
            return _lift_size_word(trail.group("u"),
                                   (rest + (trail.group("tail") or "")).strip())
    return _lift_size_word(unit, name)


def _lift_size_word(unit, name):
    """A size word at the head of the name joins the unit, in front of any counting noun.

    ⚠️ THE SAME GUARD AS THE COUNTING NOUN, FOR THE SAME REASON. 'large' with nothing but modifier
    words after it names no food, so "1 large, chopped" keeps its name rather than being read as a
    measurement of nothing. The guard is what stops the rule emptying a name it cannot replace.

    ⚠️ NEVER RUNS WHEN A MEASURE IS ALREADY PRESENT. Its only caller returns early on a non-empty
    unit, so "1 cup large diced onion" keeps 'cup' and can never become 'large cup'.
    """
    m = _SIZE_LEAD_RE.match(name or "")
    if not m:
        return unit, name
    rest = m.group("rest").strip()
    if not rest or _is_all_modifier(rest.lower()):
        return unit, name
    return f"{m.group('size')} {unit}".strip(), rest


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


# --------------------------------------------------------------------------- #
# Times
# --------------------------------------------------------------------------- #
# The unit words a publisher actually writes, mapped to the two the app shows. Measured over the
# 218 stored times: min 102, mins 56, minutes 44, hr 16, hour 7, hours 3, hrs 1. Bare 'm' and 'h'
# are not in the live data and are admitted because a publisher who writes them means the same
# thing and there is no competing reading in a time column.
_TIME_UNITS = {"min": "min", "mins": "min", "minute": "min", "minutes": "min", "m": "min",
               "hr": "hr", "hrs": "hr", "hour": "hr", "hours": "hr", "h": "hr"}
# One "N unit" segment, with an optional range on the number. The unit is captured LOOSELY as any
# word, so a non-time word ("1 cup" in a time column) is read and then REFUSED rather than being
# skipped past to find a time later in the string.
_TIME_SEG_RE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)"
    r"(?:\s*(?:to|[-–—])\s*(?P<hi>\d+(?:\.\d+)?))?"
    r"\s*(?P<unit>[A-Za-z]+)\.?", re.I)
# What may sit between two segments of one duration: whitespace, a comma, an "and".
_TIME_JOIN_RE = re.compile(r"[\s,]*(?:and\s+)?", re.I)
_TIME_NOTE_LEAD_RE = re.compile(r"^[\s,;:—–-]+")


def _time_seg(m, unit):
    """One matched segment as the app writes it. A range keeps BOTH ends and an en dash."""
    hi = m.group("hi")
    return f"{m.group('lo')}\u2013{hi} {unit}" if hi else f"{m.group('lo')} {unit}"


def _time_in_note(note):
    """Normalize any duration INSIDE a trailing note, leaving every other word alone."""
    def rep(m):
        unit = _TIME_UNITS.get(m.group("unit").lower())
        return _time_seg(m, unit) if unit else m.group(0)
    return _TIME_SEG_RE.sub(rep, note)


def normalize_time(raw):
    """A stored or imported time string -> the one form the app writes. NEVER a guess.

    The canonical form is what url_jsonld.duration_text already produces from ISO-8601, so an
    imported page and a hand-typed value finally read the same: "20 min", "1 hr 15 min".

      "10 mins" / "10 minutes" / "15mins"     -> "10 min" / "10 min" / "15 min"
      "1 hour" / "2 hrs" / "1 hr, 30 min"     -> "1 hr" / "2 hr" / "1 hr 30 min"
      "15-20 minutes"                         -> "15–20 min"
      "35 min (plus 1–3 hr marinating)"       -> "35 min (plus 1–3 hr marinating)"
      "30 mins, plus 1 hour soaking"          -> "30 min (plus 1 hr soaking)"
      "20 minutes additional time"            -> "20 min (additional time)"

    ⚠️ A RANGE STAYS A RANGE. Collapsing "15-20 minutes" to its upper end is what duration_text
    does to an ISO Duration range, and that is a different case: there the publisher gave two
    machine values for ONE column and one had to be chosen. Here the author wrote a range in words
    and it is the answer, so narrowing it would be inventing precision.

    ⚠️ THE NOTE IS KEPT, NEVER DROPPED. "plus 1 hr soaking" is the difference between a dish you
    can start at six and one you cannot. Only the number is normalized, and the note keeps its own
    words.

    ⚠️ THE NOTE IS PARENTHESIZED, AND THE MIDDLE DOT IS NOT USED HERE. The reading view joins Prep,
    Cook and Total with " · ", so a note carrying the same divider made a four-part line out of two
    facts: "Prep 30 min · plus 1 hr soaking · Cook 2 hr 25 min · plus cooling". Parentheses say
    subordinate where the dot said sibling, and they leave the dot meaning one thing.

    Parenthesizing is idempotent. A note that ARRIVES wrapped has its parens stripped and put back,
    so running this over its own output changes nothing.

    ⚠️ ANYTHING UNREADABLE COMES BACK EXACTLY AS STORED. A time column holding "1 cup" is returned
    as "1 cup" rather than blanked or guessed at, so a wrong value stays visible and fixable
    instead of disappearing. Measured: 2 of the 218 stored times are not times, and both are fixed
    by hand rather than by this function.

    ⚠️ IT DOES NOT REWRITE STORED TEXT. The import path runs it on the way in, the reading view
    runs its JS mirror on the way out (static/timefmt.js, held to this one by
    tests/js/timefmt-sync.test.js over a shared case table), and the editor shows the raw stored
    value so a save can never normalize behind the cook's back.
    """
    s = (raw or "").strip()
    if not s:
        return s
    parts, pos = [], 0
    while pos < len(s):
        probe = _TIME_JOIN_RE.match(s, pos).end() if parts else pos
        m = _TIME_SEG_RE.match(s, probe)
        if not m:
            break
        unit = _TIME_UNITS.get(m.group("unit").lower())
        if not unit:
            break
        parts.append(_time_seg(m, unit))
        pos = m.end()
    if not parts:
        return s
    note = _TIME_NOTE_LEAD_RE.sub("", s[pos:].strip())
    if note.startswith("(") and note.endswith(")"):
        note = note[1:-1].strip()
    duration = " ".join(parts)
    return f"{duration} ({_time_in_note(note)})" if note else duration


def classify_step(text):
    """A direction line -> (is_heading, clean_text). Heading if colon-terminated / ALL-CAPS
    (is_section) OR ending in a trailing dash ("prepare your pan -"); the trailing dash is
    stripped. STEPS only — never applied to ingredient lines.

    This answers "is this whole line a heading". plan_step_rows below is the full rule set, and it
    calls this first."""
    t = (text or "").strip()
    if _TRAILING_DASH.search(t):
        return True, _TRAILING_DASH.sub("", t).strip()
    return is_section(t), t


# ================================================================================================ #
# STEP STRUCTURE — the rules a new import applies, and the SAME rules the repair pass applies.
#
# ⚠️ ONE DEFINITION, IMPORTED BY BOTH, AND THAT IS THE WHOLE POINT OF PUTTING THEM HERE.
#    scripts/convert_step_headings.py repaired 300 already-imported recipes with these rules written
#    out inside it. A second copy in the importer would mean the next recipe someone imports is
#    structured differently from the corpus that was just repaired to match it, and nothing would
#    say so. The script imports these names now.
#
# ⚠️ THEY EXIST BECAUSE OTHER PEOPLE'S RECIPES CARRY BOTH SHAPES. A publisher who writes section
#    titles and a publisher who writes "Deseed - trim the stems" are both common, and no rule turns
#    one into the other. The levels let a recipe keep the structure its author wrote.
# ================================================================================================ #

# The two heading levels (migration 059).
SECTION, SUBHEADING = 1, 2

# What the review queue is told, per conversion. Every one of these is a structural change the
# importer made on its own, so every one is surfaced where the import flags already show and can be
# undone with the step row menu's Convert to step / Make section heading.
STEP_STRUCTURE_REASONS = {
    "step_heading_unwrapped":
        "a whole step wrapped in bold or italics became a section heading",
    "step_label_lifted":
        "a lead-in label was lifted out of its step and became a subheading above it",
    "step_note_moved":
        "a Note or Tip step was moved into the recipe's notes; the step it followed is recorded "
        "so it can be linked in one click, and no link is made automatically",
    "step_heading_recased":
        "a heading stored in capitals was rewritten in sentence case",
    "note_fragment_removed":
        "a notes paragraph that was only a label, naming nothing, was removed",
    "note_step_mention":
        "a note names a step by number; the number is the author's, counted over their own list, "
        "so the reference is recorded unresolved and a person decides which step it means",
    "step_label_link_lost":
        "a lifted label held an ingredient link with no later mention to move it to",
    "step_alternatives":
        "sibling alternatives were found; check where the shared steps begin",
    "step_label_declined":
        "a lead-in label was found and NOT lifted, because a rule read it as a clause rather than "
        "a title; the step was left whole for a person to decide",
    "step_label_unjudged":
        "a lead-in label was found and NOT lifted, because nothing after it starts a new sentence, "
        "so no rule can tell a title from the first half of one; a person decides",
}

# ⚠️ position MEANS A DIFFERENT THING ON A STEP FLAG THAN ON A LINE FLAG, which is why this set
#    exists. import_flags has ONE nullable `position` column, and _line_flag_rows fills it with the
#    INGREDIENT line's index. A step flag's position is the STEP row's index, so a reporter that
#    reads position as "which ingredient line" would mark an unrelated ingredient. Both reporters in
#    import_write skip these when they interpret a position that way.
STEP_STRUCTURE_FLAGS = frozenset(STEP_STRUCTURE_REASONS)

# ⚠️ A BLANK LINE, MEASURED RATHER THAN CHOSEN. Of the 79 newline runs inside the 92 corpus recipes
#    that have notes, 78 are a single blank line and one is a four-newline gap on one recipe. A moved
#    note joins the convention the corpus already keeps.
NOTE_SEPARATOR = "\n\n"

# ---- note kinds and the notes data rule ---------------------------------------------------------
# ⚠️ ONE TABLE, READ FROM static/note-kinds.json, WHICH THE CLIENT IMPORTS TOO. Vite inlines the same
#    file into the bundle for static/note-blocks.js, so the display grouping and this rule cannot
#    disagree about what "Storing." means. A second copy here is exactly the drift the corpus repair
#    and the importer were just joined to avoid.
NOTE_KINDS = json.loads(
    (pathlib.Path(__file__).resolve().parent / "static" / "note-kinds.json").read_text()
)["kinds"]

# A leading label: a short phrase, then a colon or a period, then the note itself. The period form
# is real and common ("Flour. This recipe works best with..." on brioche-bread).
# ⚠️ THE SEPARATOR SET MATCHES _NOTE_STEP's, and it did not. _NOTE_STEP accepts a colon, a full
#    stop, an en dash, an em dash or a hyphen, so a "Tip - ..." step moves into the notes with
#    its dash intact and this pattern could not read the label back. Two real corpus paragraphs
#    were affected: "Leftovers – Best to pan fry fresh" (Storage) and "VARIATION - For pita
#    pockets" (Variations), both printing under Notes.
#    Widening is safe because note_kind returns a kind only for a label IN the table, so a
#    non-kind label still returns None and the paragraph stays whole.
#    ⚠️ KEEP IN STEP WITH static/note-blocks.js LEAD. tests/js/note-kinds-sync.test.js pins it.
_NOTE_LEAD = re.compile(r"^\s*([A-Za-z][A-Za-z '\u2019/-]{0,28}?)\s*[:.\u2013\u2014-]\s+(\S[\s\S]*)$")
# A paragraph that is ONLY a label, with nothing under it.
_NOTE_LABEL_ONLY = re.compile(r"^\s*([A-Za-z][A-Za-z '\u2019/-]{0,28}?)\s*[:.]?\s*$")


def _norm_label(s):
    return " ".join(str(s or "").replace("\u2019", "'").split()).lower()


def note_kind(para):
    """A notes paragraph -> the kind its leading label names, or None when it has no listed label.

    Mirrors static/note-blocks.js classifyNote. An UNLISTED label returns None, which is what keeps
    "Blind Bake:" and "Tomato Bouillon:" whole: the display leaves such a paragraph under Notes with
    its text untouched, and this rule leaves it alone too."""
    m = _NOTE_LEAD.match(para or "")
    if not m:
        return None
    want = _norm_label(m.group(1))
    for k in NOTE_KINDS:
        if any(_norm_label(l) == want for l in k["labels"]):
            return k["kind"]
    return None


def clean_notes(text):
    """The notes DATA rule -> (cleaned text, [what was removed]).

    Three things, all of them structural rather than editorial. The words of a real note are never
    rewritten.

      1  A paragraph that is ONLY a label with nothing under it goes. "Note." on its own says
         nothing and renders as a heading over the next person's paragraph.
      2  A label-only FRAGMENT glued to the front of the next note goes with it. "Note. Note: Some
         legumes..." is one paragraph carrying two labels, and the first names nothing.
      3  Paragraphs are rejoined with exactly one blank line, so a moved or imported note always
         starts its own paragraph and a stray multi-newline gap closes up.

    ⚠️ ONLY A LABEL THE TABLE KNOWS IS TREATED AS ONE. "Made with Vedant and Sophia." is a whole
    sentence that happens to be short, and reading it as a label would delete the note."""
    removed = []
    out = []
    for para in re.split(r"\n\s*\n", text or ""):
        p = para.strip()
        if not p:
            continue
        m = _NOTE_LABEL_ONLY.match(p)
        if m and note_kind(f"{m.group(1)}: x") is not None:
            removed.append(("label-only paragraph", p))     # rule 1
            continue
        while True:                                         # rule 2, repeatedly
            m = _NOTE_LEAD.match(p)
            if not m:
                break
            rest = m.group(2).strip()
            if note_kind(p) is None or _NOTE_LEAD.match(rest) is None:
                break
            if note_kind(rest) is None:
                break
            removed.append(("label-only fragment", p[:len(p) - len(rest)].strip()))
            p = rest
        out.append(p)
    # ⚠️ NOTHING REMOVED MEANS NOTHING WRITTEN, AND THAT IS DELIBERATE. Rejoining unconditionally
    #    also trims trailing whitespace, which changed 18 of the corpus's 95 noted recipes and
    #    changed nothing a reader would see: the client already trims for display (proseText), and
    #    this project decided once before not to write cosmetic whitespace back (see the .dek note
    #    in styles.css, where 6 descr and 12 notes values carry it and are left alone). A rule that
    #    rewrites 18 rows to no visible effect is a rule that has to be re-justified every time
    #    someone reads the diff.
    if not removed:
        return text, []
    return NOTE_SEPARATOR.join(out), removed                # rule 3

# A step that is nothing but a note. "Note:", "Tip -", "Notes:" all count.
_NOTE_STEP = re.compile(r"^(?:note|tip)s?\s*[:.\u2013\u2014-]\s*(\S.*)$", re.IGNORECASE | re.DOTALL)

# A lead-in label: a capitalized phrase, then a colon OR a spaced dash, then the step's own words.
# The colon needs no following space (KFC stores "Double fry:(Only double fry what you eat now)").
# The dash DOES, so a hyphenated word ("Slow-cook the beef") is not a label.
#
# ⚠️ A LABEL MAY START WITH A NUMBER WHEN THE NUMBER IS A DURATION. french-fries writes "30 min
#    cool:" and "50 sec fry:", which are labels exactly like "Deseed -" and were missed only because
#    the pattern demanded a capital letter. The number must be followed by a TIME unit, which is what
#    keeps an ingredient amount out: "1 cup:" and "2 tbsp -" name a quantity, not a stage.
_TIME_UNIT = (r"(?:min|mins|minute|minutes|hr|hrs|hour|hours|sec|secs|second|seconds"
              r"|day|days|week|weeks|night|overnight)")
_LEAD_LABEL = re.compile(
    r"^(?:([A-Z][^:.!?\n]{0,60}?)|(\d[\d\s./\u2013\u2014-]*\s*" + _TIME_UNIT +
    r"\b[^:.!?\n]{0,40}?))(?::\s*|\s[\u2013\u2014-]\s)(\S.*)$",
    re.DOTALL | re.IGNORECASE)
# The measure words that make a leading number an AMOUNT rather than a duration. Checked before the
# label pattern, so "1 cup: ..." is never lifted.
_LEAD_AMOUNT = re.compile(
    r"^\s*\d[\d\s./\u2013\u2014-]*\s*"
    r"(?:cup|cups|tbsp|tbsps|tablespoon|tablespoons|tsp|tsps|teaspoon|teaspoons|g|gram|grams"
    r"|kg|oz|ounce|ounces|lb|lbs|pound|pounds|ml|l|litre|litres|liter|liters|clove|cloves"
    r"|can|cans|slice|slices|piece|pieces|pinch|pinches|stick|sticks)\b", re.IGNORECASE)

# ⚠️ A LIFTED LABEL THAT NAMES A SECTION IS A SECTION. "To make the chocolate icing" and "If using
#    dried chickpeas" open a part of the recipe rather than captioning one step, and the words they
#    start with are what says so. Measured on the corpus: exactly 2 lifted labels match, and they are
#    the two Andy picked out of the level-1 candidates list by hand.
_SECTION_LABEL = re.compile(r"^\s*(?:to\s+make\b|for\s+the\b|for\b|if\b)", re.IGNORECASE)

# Sibling headings that are ALTERNATIVES rather than consecutive stages.
_ALTERNATIVE = re.compile(
    r"^\s*(?:option|method|version|variation|way)\s*(?:[0-9]+|[a-z]\b)"
    r"|^\s*for\s+(?:same[-\s]day|next[-\s]day)", re.IGNORECASE)

# ⚠️ A DIGIT ON BOTH SIDES OF THE DASH IS A RANGE, NOT A LABEL. "Bake for 30 - 35 minutes" and
#    "Simmer for 3 - 4 hours" are durations. Measured on the corpus review: 8 of 62 dash candidates
#    were these, and without this guard all 8 would have become headings reading "Bake for 30".
_NUMERIC_RANGE = re.compile(r"\d\s*[\u2013\u2014-]\s*\d")

# ---- the label refusals (review fix 4) ----------------------------------------------------------
# ⚠️ MEASURED AGAINST BOTH SETS, NOT REASONED. The reviewer approved 104 lead-in labels over the 300
#    recipes and declined 12. Run over the same corpus with no decisions in hand, split_lead_label
#    lifted 122, so 18 of its lifts were rows a person had already said no to (7 of them Note and Tip
#    steps, which rule 3 of plan_step_rows takes first and never reaches the label rule).
#
#    Every rule below was checked in both directions: it refuses 0 of the 104 a person approved, and
#    between them they refuse 9 of the 12 declined. The three left over are stated at the bottom.
#
# A LABEL IS AT MOST SIX WORDS, which is the longest a person approved ("Fry the chicken (the first
# time)"). The declined set runs to 7, 10 and 11 words. The ceiling is the corpus maximum rather than
# a round number, and exceeding it FLAGS the candidate rather than discarding it.
MAX_LABEL_WORDS = 6

# A COMMA JOINS TWO CLAUSES, and a title has one. None of the 104 carries a comma. Two of the
# declined do ("While this cool, pre-heat your oven as hot as it goes", "Taste, and adjust as
# necessary").
# A CONNECTIVE CONTINUES THE PREVIOUS STEP rather than opening a part of the recipe. "Then velvet the
# beef" is step 4 of pepper-steak reading on from step 3. "If" and "To" are deliberately NOT here:
# both open a real section and _SECTION_LABEL above promotes them.
_LABEL_CONNECTIVE = re.compile(
    r"^(?:then|next|now|meanwhile|while|after|afterwards?|once|when|finally|lastly|also|"
    r"first|second|third|before)\b", re.IGNORECASE)

# ⚠️ THE PREFIX IS HOW A CALLER TELLS A REFUSED LABEL FROM NO LABEL AT ALL. split_lead_label returns
#    a reason string for both, and "no lead-in label" is true of most steps in every recipe. Only
#    these reasons mean "something label-shaped was here and a rule declined it", which is the only
#    kind worth putting in front of a person.
LABEL_DECLINED = "a rule refused the label: "
# The second kind of no, and it means something different to a reviewer. LABEL_DECLINED says "this is
# not a title". This one says "this might be a title and nothing here can tell".
LABEL_UNJUDGED = "no rule can judge the label: "


def _starts_a_sentence(rest):
    """Does what follows the label begin a new sentence? A capital letter says yes.

    ⚠️ MEASURED, NOT REASONED, OVER EVERY REVIEWED ROW. Of the 104 lead-in labels a person approved,
    99 are followed by a capital. All three of the rows a person declined as instructions or as a
    sentence are followed by a lowercase word or by a digit:

        "Salt lightly"              -> "this is mainly to draw excess liquid out..."
        "Do a window pane test"     -> "take a small walnut sized piece of dough..."
        "Set up three mixing bowls" -> "1) one with the remaining 1 cup flour, 2) one with..."

    A lowercase continuation means the author wrote ONE sentence with a colon in the middle, not a
    title over a sentence. That is the difference, and it is the only one the corpus shows: by every
    other measure "Salt lightly" is "Keep warm" and "Set up three mixing bowls" is "Make the toasted
    rice powder".

    ⚠️ IT IS A FLAG, NOT A REFUSAL, AND THE DIFFERENCE IS THE WHOLE RULING. 5 of the 104 approved
    labels are also followed by a lowercase word (bulgogi-bowls' three, "Optional blitz", "Flip"), so
    this cannot decide. It can only say that nothing here decides, which is what the review queue is
    for."""
    m = re.search(r"[A-Za-z0-9]", rest or "")
    return bool(m) and rest[m.start()].isupper()


def label_refusal(label, caps_titled=False):
    """A reason string when `label` is not a title, else None. ONE function for both callers.

    ⚠️ IT RUNS FOR THE REVIEWED LABEL TOO, and that is deliberate. The corpus pass passes the label a
    person approved and the importer reads one off the line, but "is this a title or a clause" is the
    same question either way. A decision CSV that has gone stale against a rule should lose to the
    rule, not override it. Verified: none of the 104 approved labels trips any of these.

    ⚠️ THREE DECLINED ROWS ARE NOT HERE AND CANNOT BE. "Salt lightly" (smashed-cucumber-salad),
    "Set up three mixing bowls" (country-ham-croquettes) and "Do a window pane test" (bagel) are
    shape-identical to labels a person approved: "Keep warm" is also two words of verb plus
    modifier, and "Make the toasted rice powder" is also five words of imperative plus object. The
    bagel and croquettes rows were declined as instructions and the cucumber row because the heading
    "would sit over 7 unrelated steps", which is a fact about the steps BELOW it, not about its
    words. No rule over the label can see any of that, so all three still lift and still carry
    step_label_lifted into the review queue, which is where a person reads them.

    ⚠️ AND A RULE THAT WOULD HAVE CAUGHT TWO MORE IS DELIBERATELY ABSENT. french-fries' "50 sec fry"
    and "30 min cool" are lifted by the duration alternative of _LEAD_LABEL, and neither is in the
    reviewed set, because the candidate list that was reviewed predates that alternative. Refusing a
    label that leads with a figure would catch both and trips none of the 104 — and it would also
    reverse the decision that ADDED the alternative on the stated ground that "30 min cool: is a
    stage like any other". Reversing that is a judgement about french-fries, not a defect, so it is
    a question for a person rather than a rule added here."""
    l = " ".join((label or "").split())
    if not l:
        return None                                   # the caller's own emptiness checks own this
    for opener, closer in (("(", ")"), ("[", "]")):
        if l.count(opener) != l.count(closer):
            # brownies: "Pour the batter into the prepared pan (it'll be thick" + "that's ok) and..."
            return f"a {opener}{closer} bracket is left open, so the label is half a sentence"
    # ⚠️ AN ALL-CAPS LEAD-IN ENDING IN A COLON IS A TITLE, WHATEVER ITS SHAPE. The three refusals
    #    below all read a label as prose, and prose is not written in capitals with a colon after
    #    it. An author who typed "WHILE THE DOUGH IS RESTING, MAKE THE FILLING:" was writing a
    #    heading and said so twice over, in the case and in the colon.
    #    MEASURED BEFORE IT WAS WRITTEN, over all 300 recipes and after the author numbers come off:
    #    exactly 2 labels take this door, 'WHILE THE DOUGH IS RESTING, MAKE THE FILLING'
    #    (aloo-potato-parathas) and 'MEANWHILE, MAKE THE KACHUMBER TOPPING' (kachumber-tilapia), and
    #    the 8 other currently-refused lead-ins are all mixed case and stay refused. The exemption
    #    is narrow because the measurement said it could be.
    #    ⚠️ IT DOES NOT REACH THE BRACKET REFUSAL ABOVE. A half-open bracket means the label is half
    #    a sentence whatever its case, and lifting it would still cut the sentence in two.
    if caps_titled:
        return None
    if "," in l:
        return "a comma joins two clauses, and a title has one"
    if _LABEL_CONNECTIVE.match(l):
        return f"it opens with {l.split()[0]!r}, which continues the step before it"
    if len(l.split()) > MAX_LABEL_WORDS:
        return (f"{len(l.split())} words is a clause, not a title "
                f"(the longest label a person approved is {MAX_LABEL_WORDS})")
    return None

# An ingredient link as it is STORED in a step. A heading is escaped and never linkified
# (app.js renderStepRow), so a label carrying one cannot be lifted without showing the markup.


def is_caps(text):
    """Letters, and not one of them lowercase. "FRY #1" yes, "Finish with COLD butter" no."""
    t = (text or "").strip()
    return bool(t) and any(c.isalpha() for c in t) and t == t.upper()


def sentence_case(text):
    """ALL CAPS -> sentence case, keeping the punctuation and any digits.

    ⚠️ IT LOWERCASES PROPER NOUNS TOO, and that is accepted rather than solved. "MAKE CRISPY CHEESY
    BIRRIA TACOS!" becomes "Make crispy cheesy birria tacos!". Guessing which words are names is the
    kind of rule that gets one wrong quietly, so every change this makes is surfaced in the review
    queue for a person to read."""
    t = (text or "").strip()
    if not t:
        return t
    lowered = t.lower()
    for i, ch in enumerate(lowered):
        if ch.isalpha():
            return lowered[:i] + ch.upper() + lowered[i + 1:]
    return lowered


def _raw_cut_for_rendered_label(flat, label):
    """Where `label` ends in the RAW text, when the label was read from the rendered form.

    Walks the raw string and the rendered string together, so a [[key|shown]] run consumes its
    display words. Returns the raw index just past the label, or None when the rendered text does
    not start with it."""
    raw_i = rendered = 0
    want = label
    while raw_i < len(flat) and rendered < len(want):
        m = _LINK_PARTS.match(flat, raw_i)
        if m:
            shown = (m.group(2) or m.group(1))
            if not want[rendered:].startswith(shown):
                return None
            raw_i, rendered = m.end(), rendered + len(shown)
            continue
        if flat[raw_i] != want[rendered]:
            return None
        raw_i += 1
        rendered += 1
    return raw_i if rendered == len(want) else None


# ---- the author's own step numbers ---------------------------------------------------------------
# ⚠️ TWO FORMS, AND THE SECOND IS THE RISKY ONE. A separator after the number ("1.", "1)", "Step 1:",
#    "1 - ") is unambiguous. A BARE number followed by a space is not: "30 minutes before you start
#    cooking throw your butter into the freezer" opens exactly that way and is a real instruction.
#    The bare form is therefore admitted only when the number EQUALS the step's own ordinal and a
#    capital letter follows it. Measured over all 300 recipes: that pair admits 7 steps, every one of
#    them the author's numbering (oven-baked-ribs 1 to 5, potato-scallion-cakes 3,
#    white-bean-stuffed-poblanos 2), and refuses the 3 real ones ("30 minutes...", "180 degrees...",
#    "24 pieces..."), each of which is excluded by the ordinal clause alone.
_AUTHOR_NUM_SEP = re.compile(r"^\s*(?:step\s*)?(\d+)\s*[.):\u2013\u2014-]\s+", re.IGNORECASE)
_AUTHOR_NUM_BARE = re.compile(r"^\s*(\d+)\s+([A-Z\u00c0-\u00dd])")


def author_step_number(text, ordinal):
    """The author's own number at the front of a step -> (number, the text without it), else None.

    `ordinal` is the step's position in the recipe, counting ordinary steps only. A number that does
    not match it is not this step's number and is left alone."""
    flat = text or ""
    m = _AUTHOR_NUM_SEP.match(flat)
    if m and int(m.group(1)) == ordinal:
        return int(m.group(1)), flat[m.end():].lstrip()
    m = _AUTHOR_NUM_BARE.match(flat)
    if m and int(m.group(1)) == ordinal:
        return int(m.group(1)), flat[m.start(2):]
    return None


def strip_author_numbers(step_texts):
    """[step text] -> [step text], with the author's own numbering removed, or the list UNCHANGED.

    ⚠️ ALL OR NOTHING, OVER THE WHOLE RECIPE. A number is removed only when the recipe's steps carry
    a consecutive run starting at 1 that agrees with their own ordinals. One step beginning "2 cups
    flour" in a recipe that is not numbered therefore cannot be touched, which is the whole point:
    the evidence that a leading number is the AUTHOR'S is that the rest of the recipe is numbered
    too. Headings are not passed in and so never interrupt the count.

    A gap is allowed (a step the author left unnumbered) as long as every number present matches its
    ordinal, because that is still one sequence with a hole rather than two different things."""
    found = [author_step_number(t, i) for i, t in enumerate(step_texts, 1)]
    numbered = [i for i, f in enumerate(found) if f is not None]
    if len(numbered) < 2 or 0 not in numbered:
        return list(step_texts)                 # not numbered, or not numbered from the start
    return [found[i][1] if found[i] is not None else t for i, t in enumerate(step_texts)]


def split_lead_label(text, label=None):
    """A step line -> (label, rest) when a lead-in label can be lifted, else a REASON STRING.

    A string means refuse and say why; a tuple means go ahead. `label` pins the expected label (the
    repair pass passes the reviewed one); left out, the label is read from the line.

    ⚠️ REFUSING IS A REAL ANSWER HERE, NOT A CAUTIOUS ONE. Each refusal below is a shape where
    lifting would change what the recipe SAYS rather than how it is laid out.
    """
    flat = " ".join((text or "").split())
    reviewed = label            # captured before the branch below rebinds `label` to a raw slice
    if label is not None:
        label = " ".join(label.split())
        if not label:
            return "the decision names no label"
        if not flat.startswith(label):
            # ⚠️ A REVIEWED LABEL COMES FROM THE RENDERED TEXT AND THE ROW HOLDS THE STORED TEXT,
            #    and they differ wherever the label contains an ingredient link: bulgogi-bowls is
            #    stored as "Wilt the [[spinach]]: heat 2 tsp oil..." and was reviewed as "Wilt the
            #    spinach". Matching against the RENDERED form is what lets a reviewed decision reach
            #    a label with a link in it; move_link_out_of_label then carries the link into the
            #    step, so the heading never has to render markup.
            cut = _raw_cut_for_rendered_label(flat, label)
            if cut is None:
                return "the live text does not start with the approved label"
            # ⚠️ THE RAW SLICE, NOT THE REVIEWED STRING. The reviewed label has already had its
            #    markup rendered away, and returning it would DROP the link instead of moving it.
            #    move_link_out_of_label needs the "[[spinach]]" to carry into the step.
            label, rest = flat[:cut], flat[cut:]
        else:
            rest = flat[len(label):]
        m = re.match(r"^(?::\s*|\s*[\u2013\u2014-]\s*)", rest)
        if not m:
            return "no label separator after the approved label"
        rest = rest[m.end():].strip()
        sep = m.group(0)
    else:
        if _LEAD_AMOUNT.match(flat):
            return "an ingredient amount, not a label"       # "1 cup:" names a quantity
        m = _LEAD_LABEL.match(flat)
        if not m:
            return "no lead-in label"
        # Two label alternatives: a capitalized phrase, or a duration ("30 min cool").
        label = (m.group(1) or m.group(2)).strip()
        rest = m.group(3).strip()
        sep = flat[len(label):len(flat) - len(rest)]
    if not rest:
        return "nothing left under the label"                  # the whole line IS the label
    # ⚠️ A LABEL CARRYING A LINK IS NO LONGER REFUSED. It was, because a heading is escaped and never
    #    linkified so the markup would print. move_link_out_of_label is the answer instead: the
    #    heading takes the plain words and the link moves to the next mention of the same word in
    #    the step. Where there is no later mention the caller lifts anyway and flags the lost link,
    #    which is Andy's ruling — a heading he has decided on should not be blocked by a link that
    #    can be put back by hand.
    if _NUMERIC_RANGE.search(f"{label[-1:]}{sep}{rest[:1]}"):
        return "a numeric range, not a label"
    # ⚠️ LAST, AND FOR BOTH CALLERS. See label_refusal: the reviewed label and the detected one get
    #    the same question. The prefix is what lets plan_step_rows tell this from "no lead-in label"
    #    and put the candidate in front of a person instead of dropping it silently.
    # ⚠️ THE CASE AND THE COLON TOGETHER ARE THE EVIDENCE, and the colon has to come from the LINE
    #    rather than from the label. A dash-separated ALL-CAPS lead-in is not this shape, which is
    #    why `sep` is tested rather than just is_caps(label).
    caps_titled = is_caps(label) and sep.strip().startswith(":")
    why = label_refusal(label, caps_titled=caps_titled)
    if why:
        return LABEL_DECLINED + why
    # ⚠️ THE POSITIVE GATE RUNS ONLY WHERE NOBODY HAS JUDGED, which is the auto-detect path. A
    #    reviewed label arrives with a person's decision attached and keeps it: the corpus pass still
    #    lifts all 104, so the corpus result does not move. The importer serves other people's
    #    recipes, where there is no reviewer, and declining to guess is what it is for.
    if reviewed is None and not _starts_a_sentence(rest):
        return LABEL_UNJUDGED + "nothing after it starts a new sentence"
    return label, rest


def label_level(label):
    """A lifted label -> SECTION or SUBHEADING. A label that names a part of the recipe opens a
    group; one that captions a single step sits tight to it. See _SECTION_LABEL."""
    return SECTION if _SECTION_LABEL.match(label or "") else SUBHEADING


# ⚠️ LINKS RESOLVE BY THE ID INSIDE [[...]], NOT BY THE WORDS. app.js openPanel fetches
#    /api/ingredients/<key> with the key exactly as stored, so changing a letter inside the markup
#    breaks the link silently. Everything below that rewrites step text works around the markup.
_LINK_PARTS = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def move_link_out_of_label(label, rest):
    """A label carrying link markup -> (plain label, rest with the link moved into it).

    ⚠️ A HEADING IS ESCAPED AND NEVER LINKIFIED (app.js renderStepRow), so a lifted label holding
    "[[spinach]]" would print the brackets. The heading takes the plain words and the link moves to
    the NEXT mention of the same word in the step, which is where a reader would reach for it
    anyway. bulgogi-bowls is the corpus case: "Wilt the [[spinach]]: heat 2 tsp oil... Add half the
    spinach, toss with tongs..." — the link lands on "spinach" in the step.

    Returns (plain_label, new_rest, moved) where `moved` is False when no later mention exists. The
    caller lifts anyway and flags the lost link for re-linking rather than refusing a heading Andy
    has already decided on.
    """
    links = list(_LINK_PARTS.finditer(label or ""))
    if not links:
        return label, rest, True
    plain = _LINK_PARTS.sub(lambda m: (m.group(2) or m.group(1)), label).strip()
    plain = " ".join(plain.split())
    moved_any = False
    out = rest
    for m in links:
        key, shown = m.group(1), (m.group(2) or m.group(1))
        word = shown.strip()
        if not word:
            continue
        # the first LATER mention of the same word, outside any existing markup
        spans = [(x.start(), x.end()) for x in _LINK_PARTS.finditer(out)]
        for hit in re.finditer(rf"\b{re.escape(word)}\b", out, re.IGNORECASE):
            if any(a <= hit.start() < b for a, b in spans):
                continue
            out = out[:hit.start()] + f"[[{key}|{hit.group(0)}]]" + out[hit.end():]
            moved_any = True
            break
    return plain, out, moved_any


def capitalize_first_visible(text):
    """Capitalize the first letter a READER sees, leaving link ids alone.

    ⚠️ IT NEVER TOUCHES A LETTER INSIDE [[...]] WITHOUT GIVING THE LINK A LABEL. The id is what
    resolves the link, so upper-casing it would break it. A link with a label gets the label
    capitalized; one without gains a label that is the capitalized form of its key, which renders
    the same and keeps the id byte-identical.
    """
    t = text or ""
    m = _LINK_PARTS.match(t.lstrip())
    if m and m.start() == 0 and t.lstrip() == t:
        key, shown = m.group(1), m.group(2)
        word = shown if shown is not None else key
        if not word or not word[0].isalpha() or word[0].isupper():
            return t
        return f"[[{key}|{word[0].upper() + word[1:]}]]" + t[m.end():]
    for i, ch in enumerate(t):
        if ch.isalpha():
            return t if ch.isupper() else t[:i] + ch.upper() + t[i + 1:]
        if not ch.isspace() and ch not in "([\u201c\"'":
            return t                                        # starts with a digit or a symbol
    return t


def group_alternatives(rows):
    """Sibling alternative headings directly under a section become SUBHEADINGS of it.

    ⚠️ "DIRECTLY UNDER" IS THE WHOLE CONDITION, and it is what tells the two corpus cases apart.
    brioche-bread writes "Shaping options" and then "Option 1:" and "Option 2:" with no step in
    between, so the two options are ways of doing the one thing the section names and belong under
    it. the-best-new-york-style-bagel writes "For Same Day Baking" and "For Next Day Baking" SEVEN
    steps after the heading above them: they are their own phases, not two ways of mixing the dough,
    and demoting them would say the opposite. That case is flagged instead.

    ⚠️ WHERE THE SHARED STEPS RESUME IS NOT DECIDABLE HERE, which is why nothing after the last
    alternative is touched. A heading for them is a judgement about the recipe, and the one place to
    get it right is the author's own source text.

    Returns (rows, conversions).
    """
    out = [dict(r) for r in rows]
    notes_out = []
    i = 0
    while i < len(out):
        r = out[i]
        if not (r["is_heading"] and r["heading_level"] == SECTION):
            i += 1
            continue
        # ⚠️ "DIRECTLY UNDER" MEANS THE FIRST ALTERNATIVE, NOT ALL OF THEM. Each alternative owns
        #    its own steps, so they are siblings WITHIN the section rather than a consecutive run of
        #    headings: brioche reads section, Option 1, a step, Option 2, a step. The condition is
        #    that the section is immediately followed by an alternative, which is what separates
        #    brioche from bagel, where seven steps sit between the heading and the alternatives.
        if not (i + 1 < len(out) and out[i + 1]["is_heading"]
                and _ALTERNATIVE.match(out[i + 1]["text"] or "")):
            i += 1
            continue
        # every heading from here to the next SECTION belongs to this section
        j, alts = i + 1, []
        while j < len(out):
            if out[j]["is_heading"]:
                if out[j]["heading_level"] == SECTION and not _ALTERNATIVE.match(out[j]["text"] or ""):
                    break
                alts.append(j)
            j += 1
        hits = [k for k in alts if _ALTERNATIVE.match(out[k]["text"] or "")]
        if len(hits) >= 2:
            for k in hits:
                out[k]["heading_level"] = SUBHEADING
            notes_out.append({"position": i, "flag": "step_alternatives",
                              "reason": STEP_STRUCTURE_REASONS["step_alternatives"],
                              "detail": f"{out[i]['text']}: "
                                        + ", ".join(out[k]["text"] for k in hits)})
        i += 1
    # alternatives that are NOT directly under a section still get flagged, because a person has to
    # decide where their shared steps begin.
    seen = {k for k in range(len(out)) if out[k]["is_heading"] and out[k]["heading_level"] == SUBHEADING
            and _ALTERNATIVE.match(out[k]["text"] or "")}
    loose = [k for k, r in enumerate(out)
             if r["is_heading"] and _ALTERNATIVE.match(r["text"] or "") and k not in seen]
    if len(loose) >= 2:
        notes_out.append({"position": loose[0], "flag": "step_alternatives",
                          "reason": STEP_STRUCTURE_REASONS["step_alternatives"],
                          "detail": "not under a section: "
                                    + ", ".join(out[k]["text"] for k in loose)})
    return out, notes_out


def plan_step_rows(directions, notes=""):
    """The full step-structure rule set. -> (rows, notes, conversions).

    `rows` are {position, is_heading, heading_level, text}, positions renumbered over the
    heading-INCLUSIVE list exactly as app.write_recipe_rows assigns them. `notes` is the recipe's
    notes with any moved Note steps appended. `conversions` are {position, flag, reason, detail}
    for the review queue.

    THE RULES, in order:
      1  A whole step wrapped in _x_ or **x** -> a SECTION heading, unwrapped.
      2  A colon-terminated or ALL-CAPS line -> a SECTION heading (classify_step, unchanged).
      3  A Note:/Tip: step -> the recipe's notes, blank-line separated.
      4  A lead-in "Label:" or "Label - " -> a SUBHEADING above the step, which keeps the rest.
      5  Heading text in capitals -> sentence case. Runs over the headings rules 1 to 4 just made.

    ⚠️ A SHORT TITLE-LIKE STEP IS NOT CONVERTED, and that is a decision rather than a gap. "Prepare
    the pan" and "Chop everything" are the same shape, one a heading and one an instruction, and no
    length or verb rule told them apart on the corpus without also catching real steps. The corpus
    repair converted 21 of these BY HAND from a reviewed list. An importer has no reviewer, so it
    leaves them as steps, which is the error a person can see and fix rather than the one that
    quietly hides an instruction in a heading.
    """
    rows, conversions = [], []
    notes = notes or ""
    # ⚠️ THE AUTHOR'S OWN NUMBERS COME OFF FIRST, BEFORE ANY RULE READS THE LINE. The app prints its
    #    own step number in a circle, so leaving "1." in the text shows the number twice, and a
    #    lead-in label hiding behind one ("1. MAKE THE DOUGH: ...") cannot be seen by the label rule
    #    at all. Stated over the WHOLE list: the ordinals are the author's own, counted over the
    #    lines as they arrived, which is why this runs before anything becomes a heading or a note.
    directions = strip_author_numbers(list(directions or []))

    def note(flag, detail):
        conversions.append({"position": len(rows), "flag": flag,
                            "reason": STEP_STRUCTURE_REASONS[flag], "detail": detail})

    for text in directions or []:
        raw = (text or "").strip()
        if not raw:
            continue
        # 1 — a whole step wrapped in emphasis is a section title the author styled by hand.
        unwrapped = strip_emphasis(raw)
        if unwrapped != raw and unwrapped:
            note("step_heading_unwrapped", unwrapped)
            rows.append({"is_heading": 1, "heading_level": SECTION, "text": unwrapped})
            continue
        # 3 — a note is not a step. Checked BEFORE the label rule, which would otherwise lift
        #     "Note" into a heading and leave the note's words as an instruction.
        # ⚠️ THE LABEL STAYS ON THE PARAGRAPH, and it is the only thing that says which kind the
        #    note is. This stripped it and kept m.group(1), so a "Tip:" step arrived in the notes as
        #    bare prose, note_kind returned None, and the tip printed under the Notes header instead
        #    of Tips. The corpus pass keeps the label and the two callers disagreed on exactly this
        #    one character class. beans is the live case. The display layer strips the label for
        #    presentation (note-blocks.classifyNote), so keeping it costs nothing a reader sees and
        #    the kind stays recoverable.
        m = _NOTE_STEP.match(raw)
        if m:
            body = " ".join(raw.split())
            # ⚠️ THE NEIGHBOUR IS RECORDED AND THE LINK IS NOT MADE. A Note step sat somewhere in the
            #    method, and the step it sat after is nearly always what it is about — but "nearly
            #    always" is a guess, and a guess here puts a marker on the wrong step with nothing
            #    to say it is wrong. The detail carries the neighbour so the review queue can offer
            #    it as one click, and recipe_notes.step_id stays NULL until a person takes it.
            after = next((r for r in reversed(rows) if not r.get("is_heading")), None)
            neighbour = " ".join(str(after["text"]).split())[:80] if after else ""
            note("step_note_moved",
                 f"{body}\u2003\u2003[after step: {neighbour}]" if neighbour
                 else f"{body}\u2003\u2003[no step before it]")
            notes = body if not notes.strip() else f"{notes.rstrip()}{NOTE_SEPARATOR}{body}"
            continue
        # 2 — the existing whole-line heading rule.
        is_h, clean = classify_step(raw)
        if is_h:
            rows.append({"is_heading": 1, "heading_level": SECTION, "text": clean})
            continue
        # 4 — a lead-in label becomes a heading above the step it names.
        parts = split_lead_label(raw)
        # ⚠️ A REFUSED LABEL IS REPORTED, NOT JUST SKIPPED. Most steps return "no lead-in label" and
        #    saying so 2,000 times is noise. A label a RULE declined is the opposite: something
        #    label-shaped was there, a person may disagree with the rule, and the step is left whole
        #    meanwhile. See label_refusal and LABEL_DECLINED.
        if isinstance(parts, str) and parts.startswith(LABEL_DECLINED):
            note("step_label_declined", f"{raw[:60]} -- {parts[len(LABEL_DECLINED):]}")
        elif isinstance(parts, str) and parts.startswith(LABEL_UNJUDGED):
            note("step_label_unjudged", f"{raw[:60]} -- {parts[len(LABEL_UNJUDGED):]}")
        if not isinstance(parts, str):
            label, rest = parts
            # 5 — a link inside the label moves into the step, because a heading cannot render one.
            label, rest, moved = move_link_out_of_label(label, rest)
            if not moved and _LINK_PARTS.search(raw):
                note("step_label_link_lost", label)
            # 6 — the step now starts mid-sentence, so its first visible letter is capitalized.
            rest = capitalize_first_visible(rest)
            # 7 — a label that names a part of the recipe is a section, not a caption.
            level = label_level(label)
            note("step_label_lifted", f"{label} (level {level})")
            rows.append({"is_heading": 1, "heading_level": level, "text": label})
            rows.append({"is_heading": 0, "heading_level": SECTION, "text": rest})
            continue
        rows.append({"is_heading": 0, "heading_level": SECTION, "text": raw})

    # 8 — sibling ALTERNATIVES directly under a section become subheadings of it.
    rows, alt_notes = group_alternatives(rows)
    conversions.extend(alt_notes)

    # 5 — capitals become sentence case, over every heading including the ones just made.
    for i, row in enumerate(rows):
        if row["is_heading"] and is_caps(row["text"]):
            was = row["text"]
            row["text"] = sentence_case(was)
            conversions.append({"position": i, "flag": "step_heading_recased",
                                "reason": STEP_STRUCTURE_REASONS["step_heading_recased"],
                                "detail": f"{was} -> {row['text']}"})
    # 6 — the notes DATA rule, over whatever the publisher wrote plus whatever moved here.
    # ⚠️ IT RUNS LAST, AFTER THE MOVES, because rule 3 above is what can create the shape rule 2 of
    #    clean_notes removes: a note appended to a blob that already ended in a bare label.
    notes, note_removed = clean_notes(notes)
    for what, text in note_removed:
        conversions.append({"position": None, "flag": "note_fragment_removed",
                            "reason": STEP_STRUCTURE_REASONS["note_fragment_removed"],
                            "detail": f"{what}: {text}"})

    for i, row in enumerate(rows):
        row["position"] = i
    return rows, notes, conversions


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


def classify_line(raw, section_hints=None, has_stored_amount=False):
    """Turn one raw ingredient line into a structured-or-flagged record.

    ⚠️ has_stored_amount IS FOR RE-READING A STORED ROW, never for a fresh import. A row that
    already holds an amount in its qty column is an ingredient whatever its text looks like, so the
    NARROW section guess (block 3b) is skipped for it. Without it, re-reading the amount-less text
    the old save left behind promoted 7 live rows to headings and they would have vanished from the
    list: 'maple syrup', 'oyster sauce', 'light soy sauce', 'dark soy sauce', 'Worcestershire
    sauce'. Block 3 is untouched, so a colon-terminated or ALL-CAPS heading is still a heading
    whatever the row holds, and no stored heading can be demoted because a heading never carries a
    qty (import_write._ingredient_row writes None for one)."""
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
        # ⚠️ LAST, ON THE CLEANED NAME, AND THE ORDER IS LOAD-BEARING. Run before the paren strips,
        # this sees "sticks (226 grams) unsalted butter", finds no ingredient word straight after the
        # noun and correctly declines — and then the paren is removed anyway, leaving the lift
        # missed. 9 live rows were skipped that way. _dual_measure only tests for weight and volume
        # units, and a counting noun is neither, so it reads the same unit either side of this.
        unit, name = _lift_count_unit(unit, name)    # "1 clove garlic" -> clove + garlic
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
    if not has_stored_amount and _is_section_candidate(line, section_hints):
        res["kind"] = "section"
        res["flags"].append("section_suggested")
        res["flag_reason"] = "no amount, matches section pattern — treated as section header, confirm"
        return res

    # 3c. No amount, but the line OPENS with a measurement ("small bunch of flatleaf parsley",
    #     "Pinch of salt"). The unit is there and only the COUNT is missing, which is a different
    #     state from not knowing what the line is, and the flag below exists for the second one.
    #
    #     ⚠️ AFTER THE SECTION BLOCKS, NEVER BEFORE THEM. "Large Bowl:" carries a size word, and the
    #     colon is what settles it. Run first, this would read that heading as an ingredient
    #     measured in large bowls.
    lifted_unit, lifted_name = _lift_count_unit("", line)
    if lifted_unit:
        res.update(unit=lifted_unit, name=lifted_name)
        res["has_alternative"] = bool(_ALT_RE.search(lifted_name))
        res["has_prep_note"] = bool(_PREP.search(lifted_name))
        return res

    # 4. No amount, no measurement, not a clear section -> ambiguous; suggest (never decide).
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
        # Normalized ON THE WAY IN, so a new import stores the one form. Nothing already stored is
        # touched by this, and an unreadable value passes through exactly as the publisher wrote it.
        "times": {"prep": normalize_time(norm["prep_time"]),
                  "cook": normalize_time(norm["cook_time"]),
                  "total": normalize_time(norm["total_time"])},
        "ingredients": ings,
        "directions": directions,
        "images": norm["images"],
        # The publisher's number, carried STRAIGHT THROUGH untouched. ⚠️ It is not cleaned, not
        # rounded and not compared with "rating" above, which stays the cook's own verdict. A reader
        # that does not supply it (Paprika) leaves this None and nothing downstream writes a row.
        "source_rating": norm.get("source_rating"),
        "recipe_flags": flags,
        "review_count": sum(1 for i in ings if i["kind"] == "flagged"),
    }


# Shared display helper — collapse whitespace and ellipsis-truncate. It lives in the CORE rather than
# with the preview that used to own it because import_write's dry-run printer calls it in nine places;
# it is pure, three lines, and carries no source-specific coupling, so it costs the app nothing.
def trunc(s, n=66):
    s = " ".join(str(s if s is not None else "").split())
    return s if len(s) <= n else s[:n - 1] + "…"
