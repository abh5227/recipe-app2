#!/usr/bin/env python3
"""dish_reduce.py - a title reduced to a generic dish type, or to nothing.

⚠️ IT DECLINES RATHER THAN GUESSES. docs/mining-decision.md boundary (d): the generic dish type is
a fact, the creative title is expression. A title whose trailing noun is not in the authored
vocabulary records nothing. A missing vocabulary word costs coverage. A wrong one costs
correctness, which is why the vocabulary is authored and reviewed rather than mined.

⚠️ NO TITLE SURVIVES THE REDUCTION. The function returns a dish type or None. The string it read
goes out of scope, the same discipline substitution_run.py follows.

⚠️ THE BRAND IS DISCARDED BY CONSTRUCTION, not by a filter. English puts the mark in the modifier
slot and the generic noun in the head slot, so taking the head drops it. Measured over 40,000
titles: 222 carried a known mark, 0 of the extracted types were a mark. `Oreo Dessert` declines,
`Fritos Chili Pie` gives pie, `Uncle Ben's Chicken Casserole` gives casserole.
"""
import re
import unicodedata

# ⚠️ CUT THE TITLE AT THE PREPOSITION BEFORE TAKING THE HEAD. A trailing phrase names the
#    accompaniment, and the head of the whole title is then the wrong noun. `Cube Steaks With
#    Gravy` is a steak, `Pot Roast In Foil` is a roast, `Devil's Food Cake With Chocolate
#    Frosting` is a cake. Measured: 13.7% of titles carry such a phrase and the cut changes the
#    stored type for 8.5% of ALL titles, which is about one stored row in seven.
#
#    ⚠️ IT BARELY MOVES COVERAGE, 60.0% to 60.9%, WHICH IS THE TRAP. A coverage-driven comparison
#    scores the two rules as equal and ships the wrong one. Correctness and coverage are different
#    measurements here.
#
#    ⚠️ `by` IS DELIBERATELY ABSENT even though it looks symmetrical with the rest. It turns
#    `"Death By Chocolate" Trifle` into a decline.
CUT = re.compile(r"\s+(?:with|w/|for|over|on|in|from|and served|topped with|served with)\s+", re.I)

# trailing noise that is not part of the dish name
TAIL_NOISE = re.compile(r"\s*\b(recipes?|i{1,3}|deluxe|supreme|style|from\s+scratch)\s*$", re.I)

# ── singularization ───────────────────────────────────────────────────────────────────────────
#
# ⚠️ `cookies` AND `puppies` ARE THE SAME SURFACE FORM AND TAKE DIFFERENT SINGULARS. cookie ends
#    in -ie and takes -s. puppy ends in consonant-y and takes -ies. Nothing in the plural says
#    which, so a rule cannot decide it and a LOOKUP has to. The first version of this used
#    `ies -> y` throughout and produced `cooky` and `browny`, the two most common dessert types in
#    the corpus. A plural rule that mangles the highest-frequency words it will ever see is not a
#    rule.
#
#    The list is short because the dish vocabulary is bounded at a few hundred words in the first
#    place. That boundedness is the whole reason a controlled vocabulary was chosen.
ENDS_IN_IE = {
    "cookies": "cookie", "brownies": "brownie", "smoothies": "smoothie", "veggies": "veggie",
    "pasties": "pastie", "bowties": "bowtie", "hoagies": "hoagie", "kelpies": "kelpie",
    "gooies": "gooie", "blondies": "blondie", "whoopies": "whoopie", "sammies": "sammie",
    "toasties": "toastie", "butties": "buttie", "piroshkies": "piroshki",
}

# f and fe words. ⚠️ `olives` ALSO ENDS IN -ves AND IS NOT ONE OF THEM. A blanket `ves -> f`
# rule turns olives into `olif`, so these are listed rather than derived.
VES = {"loaves": "loaf", "leaves": "leaf", "knives": "knife", "halves": "half",
       "shelves": "shelf", "calves": "calf", "wolves": "wolf", "hooves": "hoof",
       "thieves": "thief", "elves": "elf"}

# ⚠️ ALREADY SINGULAR, OR PLURAL-ONLY. A dish English never says in the singular stays as it is.
#    Nobody orders a fry, a nacho or a grit. `molasses` is the other kind: it ends in -sses and a
#    strip-the-es rule turns it into `molass`.
INVARIANT = {
    "fries", "nachos", "grits", "greens", "ribs", "wings", "oats", "noodles", "leftovers",
    "molasses", "hummus", "couscous", "asparagus", "swiss", "bass", "watercress", "cress",
    "haggis", "chips", "beans", "sprouts", "collards", "brussels", "s'mores", "smores",
    "pierogies", "pierogi", "perogies", "gyros", "hash", "succotash", "goulash", "squash",
    "biscotti", "gnocchi", "ravioli", "spaghetti", "linguine", "ziti", "rigatoni", "macaroni",
    "cannoli", "tortellini", "fusilli", "penne", "orzo", "risotto", "focaccia",
}

# ⚠️ `-oes` IS AMBIGUOUS THE SAME WAY `-ies` IS. potatoes is potato plus es, joes is joe plus s,
#    and the surface form does not say which. Measured over 120,000 titles the whole population is
#    14 distinct words and 1,607 occurrences, so listing the -oe ones is cheaper than a rule.
#    `joes` matters (96 sightings, sloppy joes). The rest decline anyway.
ENDS_IN_OE = {"joes": "joe", "toes": "toe", "foes": "foe", "woes": "woe"}

# ⚠️ `-ches` IS AMBIGUOUS TOO. sandwiches is sandwich plus es, quiches is quiche plus s. Strip-the-es
#    is right for sandwiches, peaches, radishes, dishes, blintzes, knishes and boxes, and wrong for
#    the handful of food words that already end in -e. 22 sightings of `quiches` in 120,000 titles
#    became `quich` before this list existed.
ENDS_IN_CHE = {"quiches": "quiche", "kolaches": "kolache", "brioches": "brioche",
               "ganaches": "ganache", "creches": "creche", "panaches": "panache"}

IRREGULAR = {"potatoes": "potato", "tomatoes": "tomato", "mangoes": "mango", "heroes": "hero",
             "echoes": "echo", "buffaloes": "buffalo", "children": "child", "geese": "goose",
             "feet": "foot", "teeth": "tooth", "mice": "mouse", "men": "man", "women": "woman"}


# ⚠️ SPELLING VARIANTS, NOT PLURALS, AND THE DIFFERENCE IS WHY THEY NEED THEIR OWN MAP.
#    `brussel` is a misspelling of `brussels`, which INVARIANT holds plural on purpose, so the
#    singularizer can never reach it. Measured: `brussels sprouts` at 848 recipes against
#    `brussel sprouts` at 105, and nothing else collapses them.
#
#    ⚠️ `rib`, `wing` and `sprout` WERE CANDIDATES AND ARE DELIBERATELY ABSENT. A frequency ratio
#    said to collapse all three, and the ratio was wrong on every one. `rib` at 1,449 is prime
#    rib and rib roast and rib eye, `wing` at 408 is chicken wing. Both are real singulars, and
#    collapsing them produces `prime ribs` and `ribs eye`. The same lesson as the method facet:
#    an aggregate test cannot answer a per-word question. Only unambiguous misspellings and
#    back-formations are listed here.
VARIANT = {"brussel": "brussels", "couscou": "couscous", "frie": "fries",
           "perogie": "perogies", "pierogie": "pierogies", "smore": "smores"}


def singular(word):
    """One plural, one singular. ⚠️ Lookup first, rule second, and the rule is the fallback."""
    w = (word or "").lower().strip()
    if not w:
        return ""
    if w in VARIANT:
        return VARIANT[w]
    if w in INVARIANT:
        return w
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w in ENDS_IN_IE:
        return ENDS_IN_IE[w]
    if w in VES:
        return VES[w]
    if w in ENDS_IN_OE:
        return ENDS_IN_OE[w]
    if w in ENDS_IN_CHE:
        return ENDS_IN_CHE[w]
    # ⚠️ VES AS A SUFFIX, NOT ONLY AS A WHOLE WORD. `meatloaves` is 15 sightings and became
    #    `meatloave`. The stem guard keeps `preserves`, `olives`, `chives` and `endives` out of
    #    here, since none of them ends in one of those keys.
    for k, v in VES.items():
        if len(k) >= 5 and w.endswith(k) and len(w) > len(k) + 1:
            return w[:-len(k)] + v
    # ⚠️ A HYPHENATED HEAD PLURALIZES ON ITS LAST SEGMENT. `not-joes` is `not-joe`, and a blanket
    #    rule on the whole string gets the segment boundary wrong.
    if "-" in w and not w.endswith("-"):
        stem, _, last = w.rpartition("-")
        if last:
            return f"{stem}-{singular(last)}"
    if not w.endswith("s"):
        return w
    if w.endswith(("ss", "us", "is", "sh", "ch")):      # glass, hummus, haggis, hash, sandwich
        return w
    if len(w) > 4 and w.endswith("ies"):                # not in ENDS_IN_IE, so consonant-y
        return w[:-3] + "y"                             # puppies -> puppy, patties -> patty
    if len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes", "zes")):
        return w[:-2]                                   # dishes -> dish, boxes -> box
    if len(w) > 3 and w.endswith("oes"):
        return w[:-2]                                   # unlisted -oes, e.g. dominoes -> domino
    # ⚠️ THE GUARD IS 2, NOT 3. At 3 it blocked `ups` inside `roll-ups`, which is 109 sightings.
    #    Every 3-letter -s segment in 120,000 titles is `ups`, `pes` or `pts`, and the last two
    #    decline whatever they become.
    if len(w) > 2:
        return w[:-1]                                   # burritos -> burrito, cakes -> cake
    return w


# ⚠️ NFKD DOES NOT FOLD A CURLY APOSTROPHE TO AN ASCII ONE, and that is the whole apostrophe
#    defect. `Shepherd\u2019S Pie` reached the tokenizer with a character the token pattern does not
#    accept, so it split into `shepherd` and a stray `s`.
#
#    ⚠️ THE CORPUS LOOKED CLEAN AND WAS NOT. A scan of the first 400,000 titles found 24,540 ASCII
#    apostrophes and zero curly ones. Measured strided across the whole file instead, 0.25% of
#    titles carry one, and they sit entirely between rows 956,202 and 1,912,404. A head scan of
#    this corpus returns zero for a character that appears 5,000 times in it.
APOSTROPHE = re.compile("[\u2018\u2019\u02bc\u02b9\u0060\u00b4]")


def fold(text):
    """⚠️ ACCENTS ARE FOLDED, NEVER DROPPED. A bare [A-Za-z] match truncates the word at the first
    accented letter, so `Sauté` became `saut` and `Jalapeño` became `jalape`. 221 of 120,000 titles
    carry a non-ASCII letter in the final word. docs/measuring-the-premise.md records the same
    mistake once already, where an ASCII slug erased Cyrillic. Decomposing and dropping the
    combining marks keeps the whole word and lands on the spelling the corpus uses elsewhere."""
    t = APOSTROPHE.sub("'", text or "")
    return "".join(c for c in unicodedata.normalize("NFKD", t)
                   if not unicodedata.combining(c))


def head(title, cut=True):
    """The trailing noun of a title, singularized. Empty when there is no word to take."""
    t = fold(title or "")
    if cut:
        t = CUT.split(t)[0]
    t = re.sub(r'["\u201c\u201d()\[\]]', " ", t)
    t = TAIL_NOISE.sub("", t.strip())
    w = re.findall(r"[A-Za-z][A-Za-z'\-]*", t)
    return singular(w[-1]) if w else ""


def dish_type(title, vocab):
    """The generic dish type, or None. ⚠️ None is the ordinary answer, not a failure."""
    h = head(title)
    return h if h in vocab else None
