"""recipe_line_parser.py - turn a recipe ingredient line into the ingredient name it holds.

Used by linkage_matcher.py. Six defects found by a coverage pass over the real 3,282 lines are
fixed here, each one measured rather than guessed. That 3,282 is the non-heading recipe lines
carrying no `ingredient_id` yet. The matcher's own scope is all 3,332 non-heading lines, the same
set plus the 50 already linked.

READ-ONLY on live data. This module parses text; it never touches a database.

WHAT CHANGED FROM v2, AND WHY EACH ONE EXISTED
  1. ALTERNATIVE-FIRST took the head of 'X or Y' unconditionally, so 'filtered or soft water' became
     'filtered' and 'holy or Thai basil leaves' became 'holy'. 30 of the 94 'absent' variants came
     from this one rule. Now: if the head is made only of modifier words it is not an ingredient, so
     the TAIL wins instead.
  2. PAREN-CUT cut the line at the first '(', so 'dry (uncooked) basmati rice' became 'dry'. A
     parenthetical in the MIDDLE of a line is an aside, not a terminator. Now it is removed in place
     and the words on both sides are kept.
  3. COMMA-HEAD had the same shape as 1. 'natural, unsweetened cocoa powder' became 'natural'.
  4. TRAILING MODIFIERS were never stripped, so 'garlic minced', 'cumin powder' and 'Thyme Sprigs'
     reached nothing. 29 variants, 38 lines.
  5. NOT-AN-INGREDIENT lines ('14 oz', '150g', '- Soybeans: 3 hours') were treated as names.
  6. OCR/unit junk ('Ib' for lb) was treated as a name.
"""
import re

PREP = {"finely","plus","cut","diced","minced","roughly","crushed","sliced","divided","room","at",
        "peeled","drained","thinly","optional","melted","chopped","halved","chilled","seeded",
        "grated","toasted","rinsed","cubed","sifted","softened","trimmed","shredded","beaten",
        "quartered","julienned","stemmed","deveined","pitted","zested","juiced","warmed","cooled",
        "packed","lightly","coarsely","freshly","well","thawed","separated","reserved","to","for",
        "as","if","low","skinless","boneless","preferably","ideally","about","approx","more"}
STATE = {"freshly","finely","roughly","coarsely","thinly","chopped","sliced","diced","minced",
         "crushed","grated","shredded","packed","spooned","leveled","melted","softened","chilled",
         "warm","lukewarm","hot","cold","room","large","medium","small","ripe","peeled","halved",
         "quartered","cubed","beaten","sifted","drained","rinsed","trimmed","boneless","skinless",
         "cooked","good","quality","squeezed","and","very","thick","thin","best","fine","heaped",
         "heaping","level","scant","approx","approximately","about","plus","optional","frozen",
         "uncooked","dry","mature","loose","natural","filtered","firm","shaved","big","torn",
         # added after the first re-run, from the residual ABSENT list
         "of","each","flaky","sodium","nonstick","firmly","generous","pinch","canned","jarred",
         "bottled","store","bought","homemade","old","fashioned","rolled","boiling","warmed",
         "unwaxed","seedless","stemmed","husked","shelled","blanched","toasted",
         # added after READING the 514 unmatched. Every one is PREP or a quantity word: it
         # describes what was DONE to the ingredient or how much, never which ingredient it is.
         "julienned","crumbled","mashed","torn","deseeded","picked","unsifted","tightly",
         "loosely","evenly","heaping","heaped","generous","healthy","few","plenty","cut",
         "sifted","grated","room","temperature","taste","dusting","garnish","serving",
         "finish","sprinkling","dredging","brushing","needed","divided","note","recipe",
         "indian","persian","imported","homemade","preferred","your","any","following",
         "more","just","ripe","sturdy","stale","runny","thickened","soft"}
# WARNING: 'half' is deliberately NOT in STATE. It reads as a quantity word ("Half a bottle") but
# stripping it took 'half-and-half cream' to 'cream', and half-and-half is its OWN product, half
# milk and half cream. One junk line is not worth losing a real ingredient.
FORM  = {"ground","dried","powder","powdered","smoked","roasted","toasted","whole","cracked",
         "flaked","granulated","instant","raw","unsalted","salted","sweetened","unsweetened",
         "light","dark","extra","virgin","low","reduced","semisweet","bittersweet","white","brown",
         "red","green","black","yellow","fresh","sea","kosher","table","self","rising","plain",
         "all","purpose","confectioners","caster","icing","double","single","heavy","full","skim",
         "neutral","wild","baby","sweet","sour","mild","holy","thai",
         # added after READING the 514. WARNING: these are IDENTITY words, not prep. A Kashmiri
         # chili and a serrano are different chilis, sharp cheddar is a grade, Tellicherry is a
         # peppercorn grade. They live here so strip_forms only drops them when nothing else
         # matches, never in preference to a prep word.
         "kashmiri","serrano","ancho","guajillo","tellicherry","colby","sharp","long","hot",
         "shaoxing","sichuan","aleppo","shishito","crimini","cremini","portuguese","korean",
         "turkish","chinese","italian","french","greek","persian2","granny","smith"}
# Words that may TRAIL an ingredient and are not part of its name.
TRAIL = (STATE | {"powder","sprig","sprigs","stalk","stalks","granules","matchsticks","sheets",
                  "cubes","fillets","leaves","leaf","wedges","slices","pieces","strips","halves",
                  "florets","cloves","segments","rounds","batons","julienne"})
# ⚠️ THE ABBREVIATED MEASURING UNITS, NAMED AND EXPORTED, BECAUSE TWO PARSERS NEED THE SAME ONES.
#    This set used to be inlined in UNIT below and nowhere else, so import_cleanup.parse_amount
#    never got it. That parser reads an ingredient line's leading unit, and without `c` it read
#    `2 c. flour` as two of an ingredient called `c. flour`. Measured on the live catalog before
#    the fix: 3 stored rows carried the unit into the label, all three `tbs`.
#
#    ⚠️ IT IS NOT stepscale._SCALE_UNITS AND MUST NOT BE MERGED WITH IT. That list answers a
#    different question, which numbers in method text get SCALED, it is mirrored in static/app.js
#    and held there by tests/js/factor-sync.test.js. Widening it would change what the client
#    scales. This set answers only where an ingredient line's name begins.
#
#    ⚠️ `t` IS DELIBERATELY ABSENT, and the reason is repeated at UNIT below because both readers
#    need it. Both parsers match case-insensitively, `T.` is tablespoon and `t.` is teaspoon, and
#    guessing is a threefold error on a quantity. Measured over the corpus: 0.1% of lines.
MEASURE_ABBREV = {"c", "tbs", "tosp", "tblsp", "pkg", "pkgs", "pt", "pts", "qt", "qts",
                  "doz", "ctn", "env", "sq", "bu", "pk", "pc", "pcs", "lg", "sm", "med"}

UNIT = MEASURE_ABBREV | {"cup","cups","tablespoon","tablespoons","tbsp","teaspoon","teaspoons","tsp","g","kg","gram",
        "grams","oz","ounce","ounces","lb","lbs","ib","pound","pounds","ml","l","litre","liter",
        "clove","cloves","pinch","dash","can","cans","jar","package","packet","stick","sticks",
        "bunch","handful","handfuls","slice","slices","sprig","sprigs","piece","pieces","x","quart",
        "pint","gallon","stalk","block","bag","box","tin","tub","carton","head","bulb",
        # abbreviations and containers the read found parsing as ingredients: 'tbs soy sauce',
        # 'qt chicken', 'tosp white wine', 'pc skin-on'.
        "bunches","handfuls","sprigs","cloves",
        "wedge","wedges","bundle","bundles","glove","gloves","stem","stems","ear","ears","of",
        # ⚠️ THE AMERICAN HOME-RECIPE ABBREVIATIONS. The machinery already handled these: the
        #    unit check below strips a trailing period, so 'tbsp. sugar' and 'oz. cream cheese'
        #    always worked. Only the vocabulary was missing, and it was missing because the
        #    calibration corpus was a Paprika export that never used them. Measured before
        #    adding: 0 of the 3,332 local lines change their parse, so the 2,778 links cannot
        #    move, and not one of these collides with a catalog name. On RecipeNLG's raw
        #    ingredient column they lift occurrence coverage from 43.5% to 72.6%.
        #
        #    ⚠️ `t` IS DELIBERATELY ABSENT. `T.` is tablespoon and `t.` is teaspoon, and this
        #    check lowercases before looking the word up, so it cannot tell them apart. For a
        #    NAME that does not matter, both strip. For a QUANTITY it is a threefold error, and
        #    the raw column is read for quantities. A unit that cannot be read correctly is
        #    worse than a unit that is not read at all.
        }
QTY = re.compile(r"^[\d\s./¼½¾⅓⅔⅛⅜⅝⅞\-–—]+")
MODWORDS = STATE | FORM | UNIT


def _is_all_modifier(s):
    """True when every word is a modifier, so the fragment names no ingredient."""
    w = s.split()
    return bool(w) and all(x.strip(".,*") in MODWORDS for x in w)


def parse(name):
    """Return (core, rules, flags). core == '' means the line names no ingredient."""
    rules, flags = [], []
    s = (name or "").strip()

    # 6. lines that are not ingredients at all
    if not s or s.startswith(("•", "-", "*")) or ":" in s and re.search(r":\s*\d", s):
        return "", ["not_an_ingredient"], ["NOT_AN_INGREDIENT"]

    # DEFECT 2: a parenthetical is an aside. Remove it IN PLACE, never cut the line at it.
    if "(" in s:
        s2 = re.sub(r"\([^)]*\)", " ", s)
        s2 = re.sub(r"\s+", " ", s2).strip(" ,")
        if s2: s, _ = s2, rules.append("paren_removed")
        else:  s = re.sub(r"[()]", " ", s).strip()

    if QTY.match(s):
        t = QTY.sub("", s).strip()
        if t: s = t; rules.append("qty_stripped")

    # A leading token may fuse a unit with a metric restatement ("Ib./700g", "1lb/450g"). Split it
    # on the slash first, otherwise the whole token survives as a fake ingredient name ("Ib").
    w = s.split()
    if w and "/" in w[0]:
        head = w[0].split("/")[0].strip(".")
        if head.lower() in UNIT or re.fullmatch(r"[\d.]+", head or "x"):
            w[0] = w[0].split("/")[-1]; rules.append("unit_slash_split")
    dropped = False
    while w and (w[0].lower().strip(".") in UNIT or re.fullmatch(r"[\d.,]+[a-z]{0,2}", w[0].lower())):
        w.pop(0); dropped = True
    if dropped: rules.append("unit_stripped")
    s = " ".join(w)

    # DEFECT 1 + 3: an alternative or a comma tail. The head only wins if it names something.
    for pat, rule in ((r"\s+or\s+|\s*/\s*", "alternative"), (r"\s*,\s*", "comma")):
        parts = re.split(pat, s, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            head, tail = parts[0].strip(), parts[1].strip()
            if _is_all_modifier(head):
                s = tail; rules.append(rule + "_tail_kept"); flags.append("HEAD_WAS_MODIFIER_ONLY")
            else:
                s = head
                if rule == "alternative": rules.append("alternative_first"); flags.append("ALTERNATIVE")
                else:
                    first = tail.lower().split()[0].strip(".)") if tail.split() else ""
                    rules.append("prep_stripped" if first in PREP else "comma_stripped")
                    if first not in PREP: flags.append("COMMA_TAIL_UNCLEAR")

    s = s.strip(" .,-*")
    # 6 again: after all stripping, a bare quantity or unit names nothing
    if not s or re.fullmatch(r"[\d\s./¼½¾⅓⅔\-]+", s) or _is_all_modifier(s):
        return "", rules + ["names_nothing"], flags + ["NOT_AN_INGREDIENT"]
    if re.search(r"\band\b", s): flags.append("COMPOUND_AND")
    return s, rules, flags


# Multi-word FAT-CONTENT / STYLE descriptors. These only ever qualify another ingredient, so they
# strip as a PHRASE. Single-word stripping cannot do this: 'whole' and 'plain' are modifiers but
# 'milk' is not, so 'plain whole-milk Greek yogurt' stranded on 'milk greek yogurt' and matched
# nothing at all.
# WARNING: THE PHRASE ONLY STRIPS WHEN SOMETHING IS LEFT. A line that says 'whole milk' IS milk, and
# stripping the phrase there would delete the ingredient rather than qualify it.
LEADING_PHRASES = ("whole milk", "low fat", "lowfat", "full fat", "non fat", "nonfat", "reduced fat",
                   "part skim", "extra virgin")


def strip_leading_phrase(n):
    """Remove one fat-content phrase from the leading run, but never the whole name.

    WARNING: the phrase is not always FIRST. 'plain whole-milk Greek yogurt' puts a modifier in
    front of it, so a plain startswith() check missed it and the line matched nothing. Up to two
    leading modifier words are stepped over before looking for the phrase, and they are handed back
    so the caller can report everything that was dropped."""
    w = n.split()
    for lead in range(0, 3):
        if lead and (lead > len(w) or w[lead - 1] not in (STATE | FORM)):
            break
        rest = " ".join(w[lead:])
        for ph in LEADING_PHRASES:
            if rest.startswith(ph + " ") and rest[len(ph) + 1:].strip():
                return rest[len(ph) + 1:].strip(), " ".join(w[:lead] + [ph])
    return n, None


def strip_forms(n, cat_has, deplural=None):
    """Peel modifiers off BOTH ends and return the FEWEST-WORDS-REMOVED match.

    WARNING: STATE IS TRIED BEFORE FORM, AND THAT ORDER IS THE WHOLE CORRECTNESS ARGUMENT.
    A STATE or TRAIL word is prep and never changes what the ingredient is. A FORM word DOES
    change it: kosher salt is not salt, a serrano is not a chili generally. Searching both bands
    together took 'unsalted cold butter' to 'butter', dropping the IDENTITY word 'unsalted' while
    the PREP word 'cold' was still sitting there, when 'unsalted butter' is a row in its own right.
    Two passes fix it: everything reachable by removing prep alone is found first, and a form word
    is only ever dropped when nothing else matches.

    WARNING: MINIMAL WITHIN EACH PASS, NOT GREEDY. Breadth-first over the number of words removed,
    so every 1-word removal is tested before any 2-word removal and the most specific row wins.
    Greedy stripping took 'white pepper powder' to 'pepper' when 'white pepper' is itself a row.
    """
    # a leading fat-content phrase first: it qualifies, it never names
    stripped_phrase = []
    cut, ph = strip_leading_phrase(n)
    if ph:
        if cat_has(cut):
            return cut, [ph]
        d = deplural(cut) if deplural else None
        if d and cat_has(d):
            return d, [ph]
        n, stripped_phrase = cut, [ph]
    start = tuple(n.split())
    if len(start) < 2:
        return None, []
    for band in (STATE | TRAIL, STATE | TRAIL | FORM):     # prep first, identity only as a fallback
        seen = {start}
        frontier = [(start, [])]
        while frontier:
            nxt = []
            for w, dropped in frontier:
                for cut, word in ((w[1:], w[0]), (w[:-1], w[-1])):
                    if len(cut) < 1 or cut in seen or word not in band:
                        continue
                    seen.add(cut)
                    cand = " ".join(cut)
                    if cat_has(cand):
                        return cand, stripped_phrase + dropped + [word]
                    if deplural:
                        d = deplural(cand)
                        if d and cat_has(d):
                            return d, stripped_phrase + dropped + [word]
                    nxt.append((cut, dropped + [word]))
            frontier = nxt
    return None, []
