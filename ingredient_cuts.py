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

The cuts miss the overrides ONLY BY LUCK, not by design:

    CULTIVAR_REGISTER  needs a Wikidata cultivar parent, and Shaoxing wine is
                       Wiktionary-anchored
    OFF_FLAVOURING     needs an OFF flavouring parent
    OFF_ONLY           needed an OFF anchor, and Shaoxing wine has none.
                       ⚠️ REVERSED. See DECLINED at the foot of this file.

Every one of those is an ANCHOR CLAUSE. It is what saved them.

⚠️ THE RULE: a cut MUST name the anchor it applies to. Never write a cut whose predicate
is only about corroboration (source count, variation count, language coverage). Add the
anchor clause, and re-run OVERRIDES through any new cut before shipping it.

═══════════════════════════════════════════════════════════════════════════════════════
⚠️ THE CLEANUP PARADOX. READ THIS BEFORE SCORING A NEW DETECTOR.
═══════════════════════════════════════════════════════════════════════════════════════

A DETECTOR BUILT AFTER A CLEANUP HAS NO POSITIVES LEFT TO SCORE AGAINST, AND THE CLEANER
THE LIBRARY GETS THE WORSE THIS BECOMES.

Measured on 25 August 2026, building a detector for cross-language homographs. Eight had
been found by reading, one at a time, over several passes:

    ni / nickel          gula / sugar         granada / pomegranate
    moka / flour         costo / hashish      kava / coffee
    Kapuziner / birch bolete                  polo / Tabasco pepper

⚠️ SEVEN OF THE EIGHT WERE ALREADY FIXED BY THE TIME THE DETECTOR RAN. Each was removed
or resolved in the same pass that found it, which is correct behavior and destroys the
label set. The detector scored against ONE live positive over 5,076 candidate pairs. A
precision figure on one example is not a precision figure.

This is not specific to homographs. Every class in this project is found by reading, and
reading is followed immediately by a removal, so the evidence is always consumed before
anything mechanical can be measured on it.

⚠️ THE RULE: when a class is worth a detector, SNAPSHOT THE POSITIVES BEFORE FIXING THEM.
A list of (name, row A, row B) triples in a scratch file costs nothing at the time and is
the only thing that makes a later precision number mean anything. Failing that, score the
detector against a build from before the cleanup, and say in the report which build.

⚠️ WHAT THIS DID NOT AFFECT, so nobody over-reads it: the article-title rules shipped the
same day scored fine, because their twelve positives were recorded verbatim in
hand_removals.csv with their reasons rather than only deleted. The hand-removal file was
the snapshot. That is the pattern to copy.

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
# ⚠️ THE GLOSS IS THE VOCABULARY'S OWN LABEL, not a description written from memory.
#    Four of these disagreed with vocab/wikidata-class-labels.json and one of the four,
#    Q958314, fires on real rows while carrying the wrong name. Behavior never changed,
#    the cut reads the key set. The comment was wrong about what the key was.
#    The count is how many of the 32,146 vocabulary items name the class as a superclass.
CULTIVAR_CLASSES = {
    "Q15731356": "apple cultivar",       # 2,068 subclasses
    "Q3395987": "cooking apple",         #   450
    "Q3395974": "table apple",           # 1,339
    "Q12179886": "olive cultivar",       #   175
    "Q4886": "cultivar",                 #   237
    "Q4150646": "Group",                 #    28   was 'cultivar group'. The taxonomic
                                         #         rank is named Group in Wikidata.
    "Q958314": "grape variety",          #    24   ⚠️ was 'landrace', and this one FIRES,
                                         #         on 2 of the 602. Kärnfria vindruvor
                                         #         (Q19978855) is one of them, which is
                                         #         Swedish for seedless grapes.
    "Q23501": "⚠️ unverified",           #     0   absent from the class-label file, so
    "Q13094937": "⚠️ unverified",        #     0   the gloss cannot be checked against
                                         #         anything committed. Both fire on zero
                                         #         rows. Left in place rather than
                                         #         deleted, and NOT re-glossed by guess.
}
OFF_FLAVOURING_PARENTS = {"en:natural-flavouring", "en:flavouring"}

CUTS = {
    "cultivar_register": dict(
        anchor="wikidata",
        rule="the entry subclasses a Wikidata cultivar or variety class, AND one source "
             "carries it, AND it has no variations at all",
        # ⚠️ 602 UNTIL THE DEAD-LANGUAGE CUT, 603 AFTER IT, AND THE ONE IS 'Kemp'. That
        #    apple cultivar carried two Middle English words, 'kemp' and 'kempe', and
        #    they were the only thing holding it above this rule's zero-variation
        #    ceiling. Nothing alive said it, and it reaches no recipe line. See
        #    build_library.drop_dead_language_names.
        takes=603,
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
    "off_flavouring": dict(
        anchor="off_taxonomy",
        rule="the entry's Open Food Facts parent is en:natural-flavouring or en:flavouring",
        takes=203,
        why="The clearest non-ingredient class in Open Food Facts. natural vanilla "
            "flavouring, barbecue flavouring, chicken flavouring, natural onion "
            "flavouring. A cook never reaches for one.",
        threshold_note="⚠️ THIS IS THE RULE THAT PAID FOR ITSELF. 201 of the 203 were "
             "also inside off_only, which made it look 99% redundant. It was kept as its "
             "own named rule so that reversing off_only would not silently bring the "
             "flavourings back with everything else, and off_only was then reversed. All "
             "203 still go, on this rule alone. Keep a redundant cut whose anchor differs.",
        spares="anything Wikidata also carries.",
        known_false_positives="⚠️ ONE, FOUND ON READING ALL 203 rather than a sample. "
             "'bitter almond extract' is a baking ingredient and Open Food Facts files it "
             "under en:natural-flavouring, so this rule takes it. Two more are arguable "
             "and cost nothing: 'pizza seasoning' is a blend, not a flavouring, and "
             "'natural smoke flavouring' is liquid smoke, which is separately KEPT with "
             "five sources. ⚠️ The extract is the one that matters, because 'almond "
             "extract' is not in the library under any spelling while 'vanilla extract' "
             "is kept. Reversing off_only does NOT fix it. Only a hand override or an "
             "exception on this rule would.",
    ),
}

# ─────────────────────────────────────────────────────────────────────────────────────
# ⚠️ DROPPED AFTER MEASUREMENT, recorded so none of them is re-proposed. Same shape as
#    CUTS, plus the measurement that killed the rule, because whoever writes the
#    replacement needs to know exactly what the old one claimed and how it failed.
# ─────────────────────────────────────────────────────────────────────────────────────
DECLINED = {
    "off_only": dict(
        anchor="off_taxonomy",
        rule="the entry reaches no Wikidata item, AND Open Food Facts is the only source",
        took=3549,
        why="⚠️ THE PREMISE WAS WRONG, NOT THE THRESHOLD, so no threshold could have "
            "saved it. The rule read 'Open Food Facts is the only source' as 'therefore "
            "this is label vocabulary'. That is a claim about source coverage, not about "
            "what a thing is. Open Food Facts is a food database. Being the only source "
            "that carries a term is not evidence the term is industrial.",
        measurement="A fresh random 60, read one at a time and CLASSIFIED. The earlier "
            "50-row read asked only whether a cook would recognize the thing, and 'cumin "
            "seeds' passes that test and was cut anyway, so the earlier reading could not "
            "surface this.\n"
            "    ordinary ingredient   34 of 60   56.7%   95% CI [44.1%, 68.4%]\n"
            "    label or additive     23 of 60   38.3%   95% CI [27.1%, 51.0%]\n"
            "    obscure regional       2 of 60    3.3%\n"
            "    something else         1 of 60    1.7%\n"
            "  ⚠️ The ordinary half splits about one to one, and the second half is the "
            "part nobody had a box for:\n"
            "    W1  17  the SAME shopping item as a kept entry, wearing a state or label "
            "word. fresh dill, raw balsam-pear pods, plain yogurt, large eggs. Cutting it "
            "loses a phrasing.\n"
            "    W2  17  a DIFFERENT shopping item whose general term is kept. rye malt "
            "flour, tarragon vinegar, dehydrated beef stock, pumpkin seed flour, lamb "
            "kidneys, vanilla powder. Cutting it loses the ingredient.\n"
            "  Projected onto the 3,549: 2,011 ordinary ingredients, 95% CI [1,565, 2,429].",
        cost="⚠️ MEASURED AGAINST THE APP, NOT AGAINST A SAMPLE. recipes.db holds 1,638 "
            "distinct normalized ingredient terms over 2,997 lines. 273 reach any row at "
            "all, and 19 of those, over 53 lines, reached ONLY a row this rule had cut. "
            "All 19 are ordinary ingredients, and all 19 came from this rule. The other "
            "two cuts took none: cumin seeds (20 lines), ground ginger, ground nutmeg, "
            "light brown sugar, sea salt flakes, fresh thyme, long grain white rice, firm "
            "tofu, dried marjoram, brown basmati rice, plain yogurt, brown lentils, "
            "semisweet chocolate chips, dried lentils, dark brown sugar, medium grain "
            "white rice, white basmati rice, mint leaves, white sesame seeds.",
        asymmetry="⚠️ THE TWO ERRORS DO NOT COST THE SAME, which is why the calibration "
            "question never had to be settled. A label row kept costs nothing, because "
            "nobody writes 'pregelatinized wheat starch' in a recipe. A real ingredient "
            "cut costs a match.",
        no_replacement="⚠️ NO REPLACEMENT RULE WAS WRITTEN, ON PURPOSE. Two candidates "
            "were measured against the labeled 60 first. A near-neighbor name rule "
            "(strip seeds, powder, ground, whole, fresh, dried, leaves, oil and match a "
            "kept name) scored 100% precision at 15% recall strict and 29% loose, so it "
            "would have left 1,500 to 1,900 ordinary ingredients cut. Reading the entry's "
            "own Open Food Facts parent instead scored 97% recall at 66% precision, and "
            "dragged a third of the label vocabulary back with it. Neither is the rule. "
            "The label class is about 1,359 rows, which is readable, and "
            "hand_removals.csv is where that reading persists.",
    ),
    "dish_separation": dict(
        anchor="wikidata",
        rule="the entry carries a Wikidata kind of 'Dish or prepared food' or 'Cuisine, "
             "recipe or meal' AND ALSO 'Ingredient or foodstuff'",
        took=653,
        why="⚠️ DECLINED AS A BATCH MOVE, NOT AS AN IDEA. The rows were to move to their "
            "own table rather than be deleted, so that a named dish could be described "
            "when someone imports a recipe for it. That reasoning stands. What does not "
            "stand is that the 653 share the property.",
        measurement="A random 40, read one at a time.\n"
            "    dishes        16 of 40   40%   95% CI [26%, 55%]\n"
            "    ingredients   24 of 40   60%\n"
            "  Projected onto 653: 261 dishes [172, 362], and 392 ORDINARY INGREDIENTS "
            "that a batch move would take with them. The best-corroborated rows in the "
            "class are all five-source: ice cream, honey, jam, ham, chocolate, soy sauce, "
            "shrimp, oyster, peanut butter, hummus, soy milk.",
        cost="Moving all 653 costs 46 recipe lines and drops claimed-name coverage from "
             "26.7% to 25.2%. soy sauce alone is 58 lines.",
        as_food="⚠️ THE 'X as food' ROWS ARE NOT DISHES AND MUST NOT BE READ AS "
            "CANDIDATES. pike as food, squid as food, razor shell as food, gar as food, "
            "dog cockle as food. 52 rows. Wikidata uses that phrasing to separate the "
            "ANIMAL from the FOOD, which is exactly the distinction this library wants.",
        jar_cases="⚠️ 'A PREPARED THING SOLD IN A JAR' IS NOT THE EXCEPTION LIST. It runs "
            "down the middle of the class. IN the 653: kimchi, miso, hummus, fish sauce, "
            "soy sauce. NOT in it: gochujang, doubanjiang, ketchup, mayonnaise, pesto, "
            "mustard, oyster sauce. Not rows at all: harissa, tahini.",
        discriminators="⚠️ SIX WERE MEASURED AGAINST THE READ 40 AND NONE IS USABLE. "
            "Recorded so none is re-proposed from memory. The best is a coin flip.\n"
            "    'Dish' present and 'Cuisine' absent   precision 50%  recall  88%\n"
            "    'Taxon or organism' absent            precision 47%  recall 100%\n"
            "    no Open Food Facts among the sources  precision 44%  recall 100%\n"
            "    fewer than 3 sources                  precision 46%  recall  81%\n"
            "    'Cuisine, recipe or meal' present     precision 17%  recall  12%\n"
            "    name ends ' as food'                  precision  0%  recall   0%\n"
            "  ⚠️ 'fewer than 3 sources' is ALSO forbidden by the anchor clause at the "
            "head of this file, whatever its precision had been.",
        instead="⚠️ OUTSTANDING, NOT DONE. build_library.py marks all 653 with a 'dish' "
            "column so the sheet sorts on it and the separation happens by reading, one "
            "row at a time, into hand_removals.csv. The 653 still need reading. Nothing "
            "was moved and coverage did not drop.",
    ),
    "no_english_anywhere": dict(
        anchor="none, and that was the defect",
        rule="one source and no English name anywhere",
        took=1448,
        why="Finds non-English rather than junk. 840 of the 1,448, 58%, were already "
            "inside off_only, and the 608 it added beyond that were ordinary ingredients "
            "named in French, German, Dutch, Basque and Finnish. barde de porc is pork "
            "fatback. Federkohl is kale. Sal de gusano is a Mexican worm salt.",
    ),
}
