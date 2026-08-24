#!/usr/bin/env python3
"""ingredient_cuts.py: the cut rules and the override list for the ingredient library.

Nothing here deletes. A cut MARKS a row with the rule that removed it, the same way
join_exclusion records an excluded label row, so "what did we drop and why" is a query
and a cut can be reversed by name.

═══════════════════════════════════════════════════════════════════════════════════════
⚠️ THE ANCHOR CLAUSE. READ THIS BEFORE WRITING A NEW CUT.
═══════════════════════════════════════════════════════════════════════════════════════

ANY CUT PHRASED AS "SINGLE SOURCE AND NO VARIATIONS" WITHOUT NAMING AN ANCHOR KILLS
EVERY OVERRIDE AT ONCE.

An override exists precisely because nothing corroborates the term. That is the whole
reason it had to be added by hand. So the shape that identifies a register entry nobody
will ever type is the SAME shape as a term the store genuinely knows only once, and a cut
cannot tell them apart on corroboration alone.

Measured, over the 11,153-row list:

    cut C  zero variations                     removed Shaoxing wine
    cut E  one source and zero variations      removed Shaoxing wine
    cut F  fewer than two sources              removed Shaoxing wine, and part of
                                               speculoos and xawaash

Shaoxing wine is single-source with zero variations. It is the exact shape those cuts
were built to catch.

The three cuts that shipped miss the overrides ONLY BY LUCK, not by design:

    CULTIVAR_REGISTER  needs a Wikidata cultivar parent, and Shaoxing wine is
                       Wiktionary-anchored
    OFF_ONLY           needs an OFF anchor, and Shaoxing wine has none
    OFF_FLAVOURING     needs an OFF flavouring parent

Every one of those is an ANCHOR CLAUSE. It is what saved them.

⚠️ THE RULE: a cut MUST name the anchor it applies to. Never write a cut whose predicate
is only about corroboration (source count, variation count, language coverage). Add the
anchor clause, and re-run OVERRIDES through any new cut before shipping it.

═══════════════════════════════════════════════════════════════════════════════════════
"""

# ─────────────────────────────────────────────────────────────────────────────────────
# THE OVERRIDE LIST. A name and a reason. No reason, no override.
#
# ⚠️ REPORT THE SIZE AFTER EVERY CHANGE. If it passes a few dozen, the anchor rule is
#    drawn in the wrong place and the fix is redrawing it, not adding lines here.
#
# ⚠️ THE FIVE COVER TWO DIFFERENT FAILURES AND ONLY CLASS A IS WHAT THE LIST WAS FOR.
#    A  no source can anchor it. Only Wiktionary has the term, and Wiktionary carries no
#       food classification. Measured, its topics-and-categories signal is 57 to 75%
#       wrong and misses Shaoxing wine outright, so there is nothing better to use.
#    B  Wikidata HAS it and declined to classify it. 7,187 items carry no kind, rule 2
#       reached 487, and 6,700 are still out. A SECOND CLASS-B OVERRIDE IS A SIGNAL TO
#       REDRAW THE ANCHOR RULE, not to add another line.
# ─────────────────────────────────────────────────────────────────────────────────────
OVERRIDES = {
    "shaoxing wine": ("A", "en:Shaoxing wine:noun#0",
        "Chinese cooking wine. Wiktionary is the only source that has it, and its entry "
        "carries no topic and no food category, so the measured signal misses it too. "
        "17 recipe lines in the corpus, and one of the ten terms the store was built for."),
    "active dry yeast": ("A", "en:active dry yeast:noun#0",
        "Wiktionary alone. Wikidata has yeast but not this preparation of it. 11 lines."),
    "cream of tartar": ("A", "en:cream of tartar:noun#0",
        "Wiktionary alone. Potassium bitartrate is in Wikidata as a chemical and was "
        "excluded as one, so the culinary name has nothing to attach to. 2 lines."),
    "guinness": ("A", "en:Guinness:noun#0",
        "⚠️ A TRADEMARK, and 1,148 brands were excluded on purpose. Kept because Andy "
        "named it and it is cooked with, not because the exclusion rule changed. If more "
        "brands arrive this way the rule needs restating rather than extending."),
    "doubanjiang": ("B", "Q3273096",
        "⚠️ NOT a Wiktionary orphan. Wikidata HAS it as Q3273096, with labels in nine "
        "languages and a Wikipedia article, and carries NO classification. Rule 2 would "
        "have admitted it had any OFF entry shared the name, which is the only reason "
        "gochugaru got in."),
}

# ⚠️ serrano pepper was on the agreed list of six and is NOT an override. It is already
#    in the list through the Wikidata chili item, so the override would have rescued
#    nothing. Recorded rather than dropped quietly: an override that changes no row is a
#    false claim about what this list is doing.
NOT_NEEDED = {
    "serrano pepper": "already in the list through the Wikidata chili item.",
}

# ─────────────────────────────────────────────────────────────────────────────────────
# THE CUTS. Applied as marks, never as deletions.
# Each carries the anchor clause that makes it safe, and the false positives it is known
# to take, because a cut is judged on what it removes that should have stayed.
# ─────────────────────────────────────────────────────────────────────────────────────
CULTIVAR_CLASSES = {
    "Q15731356": "apple cultivar", "Q3395987": "cooking apple", "Q3395974": "table apple",
    "Q12179886": "olive cultivar", "Q4886": "cultivar", "Q23501": "variety",
    "Q4150646": "cultivar group", "Q958314": "landrace", "Q13094937": "grape variety",
}
OFF_FLAVOURING_PARENTS = {"en:natural-flavouring", "en:flavouring"}

CUTS = {
    "cultivar_register": dict(
        anchor="wikidata",
        rule="the entry subclasses a Wikidata cultivar or variety class, AND one source "
             "carries it, AND it has no variations at all",
        takes=602,
        why="Breeder-register names. A8812-3 is an accession code. Hormead Pearmain, "
            "Neild's Drooper, Stobo Castle, Orange Goff, Taubenapfel von St. Louis are "
            "register entries nobody types into a recipe. The cultivar exclusion the "
            "grouping was supposed to make never fired: 'Cultivar or plant variety' "
            "matched zero of the 28,630 items, so 1,176 of these came in under the "
            "STRONGEST rule as ordinary ingredients.",
        threshold_note="⚠️ THE VARIATION CEILING IS ZERO AND STAYS ZERO. At one it takes "
             "Altländer Pfannkuchenapfel, a real German apple carrying labels in 74 "
             "languages, plus a run of Catalan olive varieties each labelled in 12. At "
             "two it takes Big Jim pepper. False positives start at one, not two.",
        spares="Carnaroli, Chinese cabbage, Boston lettuce, Big Jim pepper, Bramley "
               "(18 variations, 4 sources), Muscat Blanc à Petits Grains (95, 3), "
               "Fresno pepper, Oliva Ascolana del Piceno PDO, and Allium sativum, which "
               "Wikidata files under a variety class.",
        known_false_positives="255 of the 602 still carry a name in more than one "
             "language. They go because nothing but Wikidata knows them, not because "
             "they are unnamed.",
    ),
    "off_only": dict(
        anchor="off_taxonomy",
        rule="the entry reaches no Wikidata item, AND Open Food Facts is the only source",
        takes=3549,
        why="Product-label and manufacturing vocabulary. Read 74 at random across two "
            "passes: roughly half are additives, industrial forms and label phrases. "
            "plant sterol ester, pregelatinized wheat starch, magnesium salts of citric "
            "acid, natural colours, precooked pasta, 'pasteurised' (a process, not a "
            "thing), 'no7'.",
        threshold_note="The bluntest of the three and knowingly so.",
        spares="everything any second source corroborates.",
        known_false_positives="⚠️ ACCEPTED BY ANDY WITH THE COST NAMED. It takes casaba, "
             "saucisses de Toulouse, brown flax seeds (17 variations), oeufs de lompe "
             "rouges, dried whole egg, seedless raisin, cacao glaze, English sauce, "
             "boyau naturel de porc. About half of what it removes should have stayed.",
    ),
    "off_flavouring": dict(
        anchor="off_taxonomy",
        rule="the entry's Open Food Facts parent is en:natural-flavouring or en:flavouring",
        takes=203,
        why="The clearest non-ingredient class in Open Food Facts. natural vanilla "
            "flavouring, barbecue flavouring, chicken flavouring, natural onion "
            "flavouring. A cook never reaches for one.",
        threshold_note="⚠️ 201 of the 203 are already inside off_only. It is kept as its "
             "own named rule so that reversing off_only does not silently bring the "
             "flavourings back with everything else. It adds exactly two rows on its own, "
             "'flavouring preparation' and 'lemon flavouring', both two-source.",
        spares="anything Wikidata also carries.",
        known_false_positives="none found on reading.",
    ),
}

# ⚠️ DROPPED AFTER MEASUREMENT, recorded so it is not re-proposed.
#    no_english_anywhere: single source and no English name anywhere, 1,448 rows.
#    840 of them, 58%, were already inside off_only, and the 608 it added beyond that
#    were ordinary ingredients named in French, German, Dutch, Basque and Finnish.
#    barde de porc is pork fatback. Federkohl is kale. Sal de gusano is a Mexican worm
#    salt. The cut finds non-English rather than junk.
DECLINED = {
    "no_english_anywhere": "finds non-English rather than junk. 58% redundant with "
                           "off_only and the remainder are ordinary ingredients named "
                           "locally.",
}
