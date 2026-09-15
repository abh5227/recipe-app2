#!/usr/bin/env python3
"""dish_facets.py - the eight dish facets, resolved from a title in one pass.

⚠️ SEVEN FACETS ARE SAFE BY CONSTRUCTION. form, method, diet, structural and appliance return a
word from a vocabulary this repo authored and Andy reviewed. base and accompaniment return
library_ids. A brand is never in a vocabulary and a catalog row is never a mark, so boundary (g)
holds without a filter. The eighth, the specific dish, keeps corpus words and is the one deliberate
exception, which is why it is CLEANED here rather than trusted.

⚠️ THE VOCABULARIES ARE READ FROM THE REVIEWED CSVs, never retyped. previews/*-vocab-proposed.csv
carry a `keep` column Andy edited, and this reads that column. Retyping them into this file would
let the two drift apart silently, which is the whole reason the review files exist.
"""
import csv, hashlib, os, re, sys, unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from dish_reduce import singular, fold, CUT, TAIL_NOISE  # noqa: E402

SOURCE_SLUG = "recipenlg-2020"

# ⚠️ THE VOCABULARIES LIVE IN vocab/ AND ARE COMMITTED, and an earlier draft read them from
#    previews/, which is gitignored. That made this module unimportable on a clone and made the
#    whole dish extraction unreproducible from the repository alone. The corpus is allowed to be
#    absent, since it is 2.29 GB and licensed derive-only. The DECISIONS about it are not.
#
#    These six carry a `keep` column the owner edited by hand. They cannot be regenerated, which
#    is the same test vocab/README.md already applies to everything else in that directory.
VOCAB = os.path.join(BASE_DIR, "vocab")


def _kept(fname, col="word"):
    with open(os.path.join(VOCAB, fname), newline="", encoding="utf-8") as fh:
        return {r[col] for r in csv.DictReader(fh) if r.get("keep") == "y"}


def _flagged(fname, flag):
    with open(os.path.join(VOCAB, fname), newline="", encoding="utf-8") as fh:
        return {r["word"] for r in csv.DictReader(fh) if flag in (r.get("flags") or "")}


# ── FORM ──────────────────────────────────────────────────────────────────────────────────────
# ⚠️ THE STYLE-NOT-FORM GROUP IS REJECTED. `Chicken Marsala` gets form None and is still fully
#    captured as base chicken plus dish `chicken marsala`. Measured: rejecting the group changes
#    only the form value and leaves base and specific dish identical. The five fragments the
#    examples turned up, mein, cotta, suey, leche and fraiche, are all inside that group, so
#    rejecting it drops them too.
FORM = _kept("dish-vocab.csv") - _flagged("dish-vocab.csv", "style-not-form")

# ── BASE ──────────────────────────────────────────────────────────────────────────────────────
BASE_SEED = set("""chicken beef pork turkey ham lamb veal bacon sausage steak brisket meatball
fish salmon tuna shrimp crab lobster cod halibut tilapia scallop clam oyster mussel trout catfish
snapper swordfish prawn squid calamari anchovy sardine egg tofu tempeh bean lentil chickpea pea
pasta spaghetti macaroni noodle lasagna penne linguine fettuccine ziti rigatoni orzo gnocchi
ravioli tortellini couscous quinoa rice barley oat grits polenta potato yam bread cheese chocolate
apple banana pumpkin peach cherry blueberry strawberry raspberry lemon lime orange pear plum
pineapple coconut carrot corn broccoli spinach cabbage mushroom onion zucchini squash eggplant
asparagus cauliflower tomato avocado pecan walnut almond peanut vanilla caramel coffee""".split())
_B = os.path.join(VOCAB, "base-vocab.csv")
with open(_B, newline="", encoding="utf-8") as fh:
    _rows = list(csv.DictReader(fh))
BASE = (BASE_SEED | {r["word"] for r in _rows if r.get("keep") == "y"}) \
       - {r["word"] for r in _rows if r["proposed"] == "EXCLUDE"}
# ⚠️ the singularizer holds these plural on purpose, which hides the base word sitting in plain
#    sight in `green beans` and `black beans`. 3,931 recipes for green beans alone.
UNBLOCK = {"beans": "bean", "noodles": "noodle", "oats": "oat", "sprouts": "sprout"}

# ── METHOD, DIET, STRUCTURAL, APPLIANCE ───────────────────────────────────────────────────────
METHOD = _kept("method-vocab.csv")
DIET = _kept("diet-vocab.csv")
STRUCTURAL = _kept("structural-vocab.csv") - {"dump"}
APPLIANCE = _kept("appliance-vocab.csv") - {"skillet", "broiler", "grill"}

# ⚠️ `skinny dip` IS A PUN, and it is 7 of the 214 `skinny` titles. Every one is that exact two
#    word string, so a special case is enough and no context rule is needed.
DIET_PUN = re.compile(r"\bskinny\s+dip\b", re.I)

# multi-word vocabulary entries have to match on the STRING, since a token set cannot hold them.
_PHRASE = {"gluten-free": r"gluten[- ]?free", "dairy-free": r"dairy[- ]?free",
           "sugar-free": r"sugar[- ]?free", "low-fat": r"low[- ]?fat", "fat-free": r"fat[- ]?free",
           "low-carb": r"low[- ]?carb", "low-calorie": r"low[- ]?calorie",
           "low-sodium": r"low[- ]?sodium", "reduced-fat": r"reduced[- ]?fat",
           "guilt-free": r"guilt[- ]?free", "grain-free": r"grain[- ]?free",
           "egg-free": r"egg[- ]?free", "nut-free": r"nut[- ]?free",
           "plant-based": r"plant[- ]?based", "weight-watchers": r"weight watchers",
           "whole30": r"whole ?30",
           "no-bake": r"no[- ]?bake", "no-cook": r"no[- ]?cook", "make-ahead": r"(?:make|do)[- ]?ahead",
           "one-pot": r"one[- ]?pots?", "one-pan": r"one[- ]?pans?", "one-dish": r"one[- ]?dish",
           "one-bowl": r"one[- ]?bowls?", "sheet-pan": r"sheet[- ]?pans?",
           "crock-pot": r"crock[- ]?pots?", "crockpot": r"crockpots?",
           "slow-cooker": r"slow[- ]?cook(?:er|ers|ed)", "instant-pot": r"instant[- ]?pots?",
           "pressure-cooker": r"pressure[- ]?cook(?:er|ers|ed)", "bread-machine": r"bread[- ]?machines?",
           "air-fryer": r"air[- ]?fry(?:er|ers)", "dutch-oven": r"dutch[- ]?ovens?",
           "cast-iron": r"cast[- ]?irons?", "clay-pot": r"clay[- ]?pots?", "sous-vide": r"sous[- ]?vide",
           "food-processor": r"food[- ]?processors?", "ice-cream-maker": r"ice[- ]?cream[- ]?makers?",
           "waffle-iron": r"waffle[- ]?irons?", "double-boiler": r"double[- ]?boilers?",
           "stir-fried": r"stir[- ]fried", "pan-fried": r"pan[- ]fried", "oven-baked": r"oven[- ]baked",
           "deep-fried": r"deep[- ]fried", "fire-roasted": r"fire[- ]roasted"}


_MULTI_RX = None


def _multi_brand_rx(brands):
    """⚠️ ONE COMPILED ALTERNATION, NOT 104 SEARCHES PER CALL. The loop this replaces ran a
    separate re.search for every multi-word surface form, twice per title, which took pass two
    from 261 seconds to 1,283. Longest-first ordering keeps `cracker jack` from being shadowed by
    a shorter form that is a prefix of it."""
    global _MULTI_RX
    if _MULTI_RX is None or _MULTI_RX[0] is not brands:
        multi = sorted((x for x in brands if " " in x), key=len, reverse=True)
        rx = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in multi) + r")\b",
                        re.I) if multi else None
        _MULTI_RX = (brands, rx)
    return _MULTI_RX[1]


def _vocab_rx(vocab):
    """One regex per vocabulary. A multi-word entry matches the string, a single word the token."""
    parts = []
    for w in sorted(vocab, key=len, reverse=True):
        parts.append(_PHRASE.get(w, re.escape(w)))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I)


_RX = {"method": _vocab_rx(METHOD), "diet": _vocab_rx(DIET),
       "structural": _vocab_rx(STRUCTURAL), "appliance": _vocab_rx(APPLIANCE)}
_CANON = {}
for _v, _name in ((METHOD, "method"), (DIET, "diet"), (STRUCTURAL, "structural"),
                  (APPLIANCE, "appliance")):
    for _w in _v:
        _CANON[(_name, re.sub(r"[- ]", "", _w).lower())] = _w

# ── the specific dish, and its cleaning ───────────────────────────────────────────────────────
PAREN = re.compile(r"\s*[\(\[][^)\]]*[\)\]]\s*")
# ⚠️ THE SPACE IS REAL AND IT IS THE SECOND HALF OF THE APOSTROPHE DEFECT. `Shepherd 'S Pie` is
#    in the corpus verbatim. The old pattern needed the apostrophe adjacent to the word, so this
#    one reached the tokenizer intact and split into `shepherd` and a stray `s`.
POSS = re.compile(r"\b(\w+)\s*'\s*s\b", re.I)
PUNCT = re.compile(r"[!?\"“”*#~]+")
NUMERIC = re.compile(r"\b\d+[- ]?(?:minute|min|hour|hr|ingredient|can|lb|oz|serving|step|way)s?\b", re.I)
STRIP_PHRASES = re.compile(
    r"\b(?:slow[- ]cook(?:er|ed)|crock[- ]?pot|instant pot|pressure cook(?:er|ed)|air[- ]fry(?:er)?|"
    r"sheet[- ]pan|dutch oven|bread machine|food processor|stove[- ]?top|old[- ]fashioned|"
    r"award[- ]winning|blue ribbon|weight watchers|to[- ]die[- ]for|make[- ]?ahead|world[- ]class|"
    r"best[- ]ever|melt[- ]in[- ]your[- ]mouth)\b", re.I)
MOD = set("""easy easiest quick quickest best better good great simple simplest perfect ultimate
amazing delicious yummy tasty fabulous fantastic wonderful incredible awesome favorite favourite
famous winning winner heavenly divine sinful decadent traditional classic authentic original basic
plain simply homemade scratch grandma grandmas grandmother granny gram nana mom moms mother
mothers mama dad dads daddy aunt aunts uncle uncles mrs mr miss chef my our your lite skinny
healthy healthier diabetic vegan vegetarian keto paleo holiday christmas thanksgiving easter
halloween valentine summer winter autumn party company potluck picnic weeknight weekend buffet
brunch never fail foolproof leftover mini little big giant huge jumbo ever real true new
microwave wok griddle blender""".split())

# ⚠️ THE ROLE WORDS, NAMED SEPARATELY FROM MOD because the hyphen rule above needs just these.
#    MOD holds everything a title puts in front of a dish. This holds only the ones that name a
#    person, which is the boundary (d) concern rather than a tidiness one.
ROLE = {"grandma", "grandmas", "grandmother", "granny", "gram", "nana", "mom", "moms", "mother",
        "mothers", "mama", "dad", "dads", "daddy", "aunt", "aunts", "uncle", "uncles", "mrs",
        "mr", "miss", "chef", "papa", "poppa", "pop", "granddad", "grandpa"}

# ⚠️ A PERSONAL NAME REACHES STORAGE THROUGH THIS FACET AND NOTHING ELSE. About 3,400 recipes in
#    the corpus carry one. `Mrs. Field's Oatmeal Cookies` has to become `oatmeal cookie`, and the
#    honorific plus the following word is what does it.
# ⚠️ THE HONORIFIC MUST NOT BE HYPHEN-GLUED TO THE WORD IN FRONT OF IT. This eats the word AFTER
#    the honorific, which is right for `Mrs. Field's Oatmeal Cookies` and wrong for
#    `Great-Grandma Banana Bread`, where it ate the banana. Inside a hyphenated compound the role
#    word belongs to the compound, and the ROLE rule in specific_dish removes the whole thing.
NAME_TITLE = re.compile(r"(?<![\w-])(?:mrs|mr|ms|miss|dr|chef|aunt|uncle|grandma|granny|nana|"
                        r"grandmother|mom|mother|mama|dad|daddy)\.?\s+\w+(?:'s|s')?", re.I)


# ⚠️ fold IS IMPORTED, NOT REDEFINED. This module used to carry its own copy, and when the curly
#    apostrophe fix landed in dish_reduce.fold the copy here would have silently kept the old
#    behavior for every dish string. One definition, one behavior.


def words(title):
    """The dish-side tokens: parenthetical gone, phrases stripped, cut at the first preposition.

    ⚠️ STRIP_PHRASES IS HERE BECAUSE specific_dish HAS IT, AND THE TWO MUST AGREE. They did not.
    `Melt In Your Mouth Chicken` gave dish `chicken` and form `melt`, since specific_dish stripped
    the phrase and this did not, and CUT then split at ` In ` leaving `Melt` as the trailing noun.
    Measured over a strided 1-in-11 sample: 0.043% of titles get a different form and 0.024% a
    different base. Small, and every one of them was wrong. The commonest corrections are real
    gains rather than removals, `None -> soup` and `None -> bread` and `None -> chili`."""
    t = PAREN.sub(" ", fold(title or ""))
    t = STRIP_PHRASES.sub(" ", t)
    t = CUT.split(t)[0]
    t = re.sub(r'["“”()\[\]]', " ", t)
    t = TAIL_NOISE.sub("", t.strip())
    return [w.lower().strip("'-") for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", t)]


def vocab_hits(title, name):
    """Every word of one vocabulary the title carries, canonicalized to the vocabulary spelling."""
    t = fold(title or "")
    if name == "diet":
        t = DIET_PUN.sub(" ", t)          # ⚠️ `skinny dip`, 7 puns, removed before matching
    out = []
    for m in _RX[name].finditer(t):
        key = re.sub(r"[- ]", "", m.group(0)).lower()
        w = _CANON.get((name, key))
        if w and w not in out:
            out.append(w)
    return out


def form_of(ws):
    tr = singular(ws[-1]) if ws else ""
    return tr if tr in FORM else None


def bases_of(ws):
    """⚠️ A SET. 19.4% of base-carrying titles name more than one."""
    out = []
    for w in ws:
        for cand in (singular(w), UNBLOCK.get(w, ""), w):
            if cand and cand in BASE and cand not in out:
                out.append(cand)
                break
    return out


def specific_dish(title, brands=None, is_cat=None):
    """⚠️ THE ONE FREE-TEXT FACET, AND THE ONLY ONE THAT NEEDS CLEANING. Returns the normalized
    dish with brands and personal names removed, or empty."""
    t = PAREN.sub(" ", fold(title or ""))
    # ⚠️ STRIP_PHRASES RUNS BEFORE CUT, AND THE ORDER IS THE DEFECT IT FIXES. CUT splits on ` for `,
    #    so `To Die For Chocolate Cake` became `to die` before the phrase list could see
    #    `to-die-for` at all. Same ordering class as the brand sweep below. Measured: 112 of
    #    599,981 titles, 0.019%.
    t = STRIP_PHRASES.sub(" ", t)
    t = CUT.split(t)[0]
    t = NAME_TITLE.sub(" ", t)                 # Mrs. Field -> gone, honorific and the name after it
    t = NUMERIC.sub(" ", t)
    t = PUNCT.sub(" ", t)
    t = POSS.sub(r"\1", t)
    t = TAIL_NOISE.sub("", t.strip())
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", t):
        w = w.lower().strip("'-")
        s = singular(w)
        if w in MOD or s in MOD:
            continue
        # ⚠️ A ROLE WORD INSIDE A HYPHENATED COMPOUND. MOD holds bare words and the tokenizer keeps
        #    hyphens, so `mother-in-law`, `great-grandma` and `not-your-mama` walked straight past
        #    it. At a dish floor of 10 that was 7 rows and it was left. At a floor of 2 the loader
        #    refuses over 11, which is what a refusing loader is for.
        #
        #    ⚠️ `doo-dad` IS DELIBERATELY KEPT. It is a snack mix, not somebody's father, and a
        #    rule that drops any compound containing a role word cuts it. The rule below asks
        #    where the role word SITS: leading it, or buried in a three-part compound, or behind a
        #    modifier as in `great-grandma`. `doo-dad` has an ordinary first segment and stays.
        if "-" in w:
            seg = [x for x in w.split("-") if x]
            if seg and (seg[0] in ROLE
                        or (len(seg) >= 3 and any(x in ROLE for x in seg))
                        or (len(seg) == 2 and seg[0] in MOD and seg[1] in ROLE)):
                continue
        if w in ("and", "or", "with", "the", "a", "an", "n", "in", "for", "of", "from", "on", "de"):
            continue
        out.append(w)
    if not out:
        return ""
    # ⚠️ THE BRAND PASS. A mark is removed word by word rather than by dropping the whole title,
    #    so `Bisquick Baked Pancakes` becomes `baked pancake` rather than nothing.
    def _debrand(words):
        """⚠️ THE MULTI-WORD SWEEP RUNS FIRST, AND THE ORDER IS THE WHOLE POINT. Word-at-a-time
        first removed `heath` from `heath bar cake` and left `bar cake`, a dish that does not
        exist. Sweeping the string first removes `heath bar` whole and leaves `cake`, which is a
        real reduction. Same ordering class as the `to die` defect, where CUT split the title
        before STRIP_PHRASES could see the phrase."""
        import brand_guard as BG
        joined = " ".join(words)
        rx = _multi_brand_rx(brands)
        if rx is not None:
            joined = rx.sub(" ", joined)
        return [w for w in joined.split()
                if BG.classify(w, brands=brands, is_catalog_name=is_cat)[0] != "brand"]

    if brands:
        out = _debrand(out)
    # ⚠️ A BARE `s` IS NEVER PART OF A DISH NAME. It is the residue of a possessive the patterns
    #    above did not reach, and dropping it is the backstop rather than the fix.
    out = [w for w in out if w != "s"]
    if not out:
        return ""
    # ⚠️ EVERY WORD IS SINGULARIZED, NOT ONLY THE LAST. The last-word rule left `hash browns
    #    casserole` beside `hash brown casserole` and `chiles rellenos` beside `chile relleno`.
    #    Measured over all 876,132 dishes: 3,398 groups merge, and only 3 have both sides above
    #    50 recipes. All 3 are correct merges. INVARIANT still protects `greens` and `beans`.
    out = [singular(w) for w in out]
    # ⚠️ AND THE BRAND PASS RUNS A SECOND TIME, BECAUSE SINGULARIZING CAN CREATE A MARK. A plural
    #    is rarely a listed surface form, so `Almond Joys` and `Tootsie Rolls` and `Rolos` walked
    #    past the first pass untouched, and singular() then turned them into `almond joy`,
    #    `tootsie roll` and `rolo`. Measured: this was every one of the 24 dish rows that still
    #    classified as a brand, including the 2 above the floor. One mechanism, not three.
    #
    #    ⚠️ IT CANNOT SIMPLY MOVE, because some listed surface forms ARE plural. `rice krispies`
    #    singularizes to `rice krispy`, which is on no list. Running it before AND after is what
    #    holds both ends.
    if brands:
        out = _debrand(out)
    if not out:
        return ""
    return " ".join(out)


def base_id_map(conn):
    """⚠️ base word -> library_id, plus the words the catalog has no row for.

    Returns (mapping, gaps). A gap is NOT a failure and NOT a reason to drop the dish. The dish
    keeps every other facet and simply carries no base row. Measured: 128 of 146 words resolve,
    covering 92.9% of base facet weight, and 15 of the 18 that do not are absent from
    library_names entirely. `turkey`, `mushroom`, `pecan` and `cherry` are not in a catalog of
    10,474 rows. docs/what-the-library-is-for.md governs admitting a row, so this records the
    hole and never fills it.
    """
    import linkage_matcher as LM
    import mining_probe as MP
    from recipe_line_parser import parse
    cat = LM.load_catalog(conn)
    decided, _ = LM.load_decisions(cat)
    out, gaps = {}, {}
    for w in sorted(BASE):
        core, _, _ = parse(w)
        tier, _, rows, _ = LM.match(core or w, cat, decided)
        if tier in MP.MATCHED and len(rows) == 1:
            out[w] = rows[0][0]
        else:
            n = conn.execute("SELECT COUNT(*) FROM library_names WHERE lower(canonical) IN (?,?)",
                             (w, w + "s")).fetchone()[0]
            gaps[w] = "absent from library_names" if not n else f"{tier.lower()}, {len(rows)} candidates"
    return out, gaps


def dish_id(dish):
    """Deterministic surrogate. A re-run reproduces the same ids, so a reload is idempotent."""
    return hashlib.sha256(dish.encode("utf-8")).hexdigest()[:16]


# ⚠️ ROUTING. A FACET WORD IS EITHER PART OF THE DISH NAME OR IT IS NOT, AND THE SAME WORD ANSWERS
#    BOTH WAYS. `stuffed pepper` outnumbers `pepper` twenty to one, so stuffed is the dish.
#    `stuffed chicken` is a hundredth of `chicken`, so stuffed is a method that happened to it.
#    No word-level rule can hold both, so the decision is per pair and needs corpus frequencies,
#    which is why the extraction runs in two passes.
#
#    ⚠️ THE UNDECIDABLE CASE DEFAULTS TO KEEP. When the bare form is never seen, routing would
#    merge two dishes that might differ and keeping only fails to merge two that are the same.
#    The first error destroys a distinction and the second is recoverable, so keep is the
#    conservative direction. Measured at scale: 15.3% keep, 41.0% route, 43.7% undecidable.
FACET_WORDS = METHOD | DIET | STRUCTURAL | APPLIANCE


def route(dish, tally):
    """Return (kept_dish, routed_words). tally is the pass-one count of every unrouted dish."""
    ws = dish.split()
    facets = [w for w in ws if w in FACET_WORDS]
    if not facets:
        return dish, []
    routed = []
    for w in facets:
        rest = " ".join(x for x in ws if x != w)
        if not rest:
            continue
        bare = tally.get(rest, 0)
        if bare and tally.get(dish, 0) < bare:
            routed.append(w)
    kept = " ".join(x for x in ws if x not in routed)
    return kept, routed
