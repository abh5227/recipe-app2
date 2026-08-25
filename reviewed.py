#!/usr/bin/env python3
"""reviewed.py: the hand-read verdicts behind every threshold in ingredient_cuts.py.

⚠️ THIS IS THE ONE FILE THAT CANNOT BE REGENERATED AT ANY PRICE. Everything else in the
pipeline is code plus a cached fetch. This is 330 entries opened one at a time, every
member row and every gloss read, across seven samples. The count is reviewed.counts(),
and the prose said 250 for six samples while counts() said 265, so it now reads off the
function rather than off a memory of it. Re-running the samples would draw
different rows, and a model re-reading them would not reach the same calls.

Nothing here is inferred. Each verdict is what was actually seen in the source rows.

HOW TO ADD TO IT. Same shape as ingredient_cuts.OVERRIDES: what was read, what the verdict
was, and the reasoning where it was not obvious. A verdict with no reasoning is only worth
recording when the reading was trivial, and most were not.

WHAT THE SEVEN SAMPLES WERE FOR, and which threshold each one set:

  1  50 recipe head terms          set rule 4 of build_join.py. 11 of 50 contaminated,
                                   22%, against 4.5% on a random 200. Head terms attract
                                   abbreviations and homographs that obscure terms do not.
  2  60 Wiktionary candidates      killed the Wiktionary anchor. 57 to 75% wrong.
  3  50 OFF-only entries           set the off_only cut. Roughly half label vocabulary.
                                   ⚠️ THE CUT IT SET WAS LATER REVERSED. The reading
                                   below stands as read. See ingredient_cuts.DECLINED.
  4  50 from the low group         found the cultivar category, which no cut designed
                                   against the stated impression would have reached.
  5  35 distinct-Wikidata merges   set the apostrophe policy in build_join.py.norm_name.
  6  40 never-met merges           confirmed 82% of punctuation merges are pure cleanup.
  7  65 excluded drinks              set rule 4 of build_library.py. The loose version,
                                     any OFF ingredient entry sharing a name bucket, is
                                     right on 39 of 65. Requiring the two ENGLISH names
                                     to be equal admits 22 and is wrong on none.
"""

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 1. Fifty recipe head terms, by recipe-line count. Every member and gloss read.
# 32 clean, 11 contaminated, 7 thin. This is what set rule 4 to name two wiktextract
# fields rather than every alias-shaped field everywhere.
# ─────────────────────────────────────────────────────────────────────────────────────
HEAD_TERMS = {
 "kosher salt": ("clean", "5 entries, every one kosher salt. OFF appears twice because "
    "the json and txt taxonomies are both loaded, so it is one opinion not two."),
 "salt": ("contaminated", "en:SPG is an initialism for salt, pepper and garlic. Faroese "
    "and Swedish salt adj mean salty, the quality not the substance."),
 "all purpose flour": ("contaminated", "en:AP joins by alt_of and its senses are Advanced "
    "Placement, Audemars Piguet and access point."),
 "olive oil": ("clean", "6 entries agree."),
 "sugar": ("clean", "6 entries agree."),
 "extra virgin olive oil": ("clean", "8 entries agree and EVOO is a correct expansion."),
 "water": ("contaminated", "4 entries and one is Wikidata weak coffee, which carries water "
    "as an alias. Wiktextract water and Wikidata Q283 are both absent, so it is wrong AND thin."),
 "granulated sugar": ("clean", "3 entries agree."),
 "vanilla extract": ("clean", "3 entries agree."),
 "eggs": ("contaminated", "en:MPFE is an initialism for meat, poultry, fish, eggs."),
 "garlic": ("clean", "10 entries agree. Wikidata carries both the culinary ingredient and "
    "Allium sativum the species, and the kinds model records that as Ingredient plus Taxon."),
 "baking powder": ("clean", "5 entries agree."),
 "baking soda": ("thin", "one entry, an AGROVOC altLabel to sodium bicarbonate. Correct, "
    "and Wikidata, OFF and wiktextract all have baking soda without reaching this bucket."),
 "onion": ("clean", "5 entries agree. The Welsh onion entry is an alternative form of "
    "wynwyn, the same vegetable."),
 "ground cinnamon": ("thin", "one entry, a Wikidata alias for cinnamon powder."),
 "vegetable oil": ("contaminated", "en:VO reads voiceover, visiting order, video operator."),
 "cornstarch": ("clean", "4 entries agree."),
 "cumin seeds": ("thin", "2 entries, both OFF, the json and txt copies of one record."),
 "soy sauce": ("clean", "7 entries agree."),
 "lemon juice": ("clean", "5 entries agree."),
 "sesame oil": ("clean", "6 entries agree."),
 "dark soy sauce": ("clean", "4 entries agree."),
 "sea salt": ("clean", "4 entries agree."),
 "garlic clove": ("clean", "3 entries agree, and Wikidata names the clove as the part."),
 "shaoxing wine": ("thin", "one entry, the English Wiktionary sense. Wikidata and OFF have "
    "nothing, and this is one of the ten terms the store was assembled to fix."),
 "egg": ("contaminated", "en:BEC is an initialism whose senses are bacon egg and cheese, "
    "and a slur."),
 "light soy sauce": ("clean", "3 entries agree."),
 "black pepper": ("clean", "6 entries agree. The AGROVOC altLabel is the right parent."),
 "butter": ("contaminated", "en:butter noun 2 is someone who butts, a busybody, and the "
    "verb sense includes a snowboard move."),
 "ground turmeric": ("thin", "one entry, a Wikidata alias."),
 "oyster sauce": ("clean", "4 entries agree."),
 "milk": ("clean", "9 entries agree. Wikidata breast milk and cow's milk both carry milk "
    "as an alias, which is a narrowing rather than an error."),
 "unsalted butter": ("clean", "4 entries agree."),
 "brown sugar": ("clean", "4 entries agree."),
 "cilantro": ("contaminated", "en:culantro joins by alt_of and is Eryngium foetidum, a "
    "different plant from Coriandrum sativum."),
 "oil": ("contaminated", "en:FOG and en:POL are initialisms, fat oil grease and petroleum "
    "oil lubricants."),
 "whole milk": ("clean", "7 entries agree."),
 "fish sauce": ("clean", "7 entries agree."),
 "active dry yeast": ("thin", "one entry, the English Wiktionary sense."),
 "confectioners sugar": ("thin", "two buckets before the punctuation fold, and both held "
    "the same single Wikipedia redirect to Powdered sugar."),
 "ginger": ("contaminated", "15 entries and six are not the spice. Ginger as a color, as a "
    "slur, as a manner of walking, and a verb for what to do to a horse."),
 "honey": ("clean", "5 entries agree."),
 "pepper": ("contaminated", "the bucket holds Wikidata bell pepper, a Capsicum, and "
    "peppercorn, a Piper. Two unrelated plants under one spelling."),
 "tahini": ("clean", "7 entries agree, tahini and tehina."),
 "yellow onion": ("clean", "4 entries agree."),
 "bay leaves": ("clean", "3 entries agree, resting on an AGROVOC altLabel, an OFF synonym "
    "and a redirect. No Wikidata or wiktextract entry reaches it."),
 "cayenne pepper": ("clean", "8 entries agree. Wikidata carries the powdered spice and the "
    "chili separately and the kinds model records the second as Taxon."),
 "coriander seeds": ("clean", "2 entries agree, thin."),
 "white pepper": ("clean", "6 entries agree."),
 "bay leaf": ("clean", "5 entries agree."),
}

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 2. Sixty Wiktionary-only candidates that the topics-and-categories signal
# flagged as food, drawn at random from 4,057, seed 20260824.
#
# ⚠️ THIS IS THE MEASUREMENT THAT KILLED THE WIKTIONARY ANCHOR. 15 ingredients, 11 dishes
# or drinks, 34 not food at all. 57 to 75% wrong. The signal tags the TOPIC A WORD IS USED
# IN, not what the word denotes, so it fires on every cooking verb and adjective. And it
# misses Shaoxing wine, which carries no topic and no food category.
# ─────────────────────────────────────────────────────────────────────────────────────
WIKTIONARY_SAMPLE = {
 "ingredient": ["ambarella", "bhut jolokia", "râble", "spalla", "flageolet bean",
    "dadih darah", "putenmedaillon", "starter dough", "lehsuni", "soopolallie",
    "sorb apple", "domiati", "serrano pepper", "kamkake", "couenne roussie"],
 "a dish, a drink or a bake": ["chicha", "bavaroise", "kiev", "christmas ham",
    "karbonadekake", "kamar bola", "pottost", "melkebolle", "kinnekling", "tulapai",
    "parakari"],
 "not food at all": ["flamejar (to flambé)", "pieczenie (baking)", "precalentar (to preheat)",
    "coddler (a device)", "automatic bread machine", "base leg (aviation)",
    "intermezzo (music)", "guard of honour (military)", "henny (a given name)",
    "white (the color)", "flat", "drinkable", "molecular", "cellarable", "hearties",
    "krudaĵo (raw material)", "all day", "mul:s", "kidolgoz", "sparzyć", "ispuniti",
    "karmelowy", "habillage", "shinny", "liquid courage", "mediterranean",
    "isopropyl acetate", "girlmeat", "salàsi (to fry)", "kokt", "stuva",
    "pengembang (a developer)", "okrasić", "kärryyttää"],
}

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 3. Fifty OFF-only entries, random, seed 20260824. Roughly half are label,
# industrial or additive vocabulary. This is what set the off_only cut AND what priced it:
# the other half are things a cook would recognise, and they go too.
#
# ⚠️ POINTER, NOT A CORRECTION. THE CUT THIS SAMPLE SET WAS REVERSED. Nothing below is
#    edited, because what was read and what was concluded from it are two different
#    records and only the second one was wrong. The reversal, the premise error and the
#    60-row measurement that replaced this reading live in ingredient_cuts.DECLINED
#    under 'off_only'. The question this sample asked, "would a cook recognise this",
#    is also what limited it: 'cumin seeds' passes that test and was cut anyway.
# ─────────────────────────────────────────────────────────────────────────────────────
OFF_ONLY_SAMPLE = {
 "label, industrial or additive": ["chromium picolinate", "magnesium bisglycinate",
    "plant stanol ester", "plant sterol ester", "ammonium molybdate",
    "magnesium salts of citric acid", "pyridoxamine hydrochloride", "natural colours",
    "dextrinated barley flour", "pregelatinized wheat starch", "pork by-product",
    "low sodium fluid milk", "gluten free wheat fiber", "honey from France",
    "aroma natural de genciana", "precooked pasta", "precooked mackerel fillet",
    "squeezed orange juice", "French style mayonnaise", "viande de boeuf en poudre",
    "pasteurised (a process, not a thing)", "no7", "anéthol de badiane"],
 "a cook would recognise": ["casaba", "pomelo juice", "apricot kernel oil",
    "brown flax seeds", "black tea leaf", "seedless raisin", "wholemeal lentil flour",
    "saucisses de Toulouse", "oeufs de lompe rouges", "sang frais de porc", "cacao glaze",
    "whole grain triticale", "dried whole egg", "jambon de porc frais", "English sauce",
    "boyau naturel de porc", "fondan", "raw pear", "raw watermelon", "Raw Atlantic bass",
    "semi-whole thai rice", "onion paster", "graines grillées", "basmati Reis gegart",
    "biologische kokosbloesem siroop", "Riz basmati long grain naturellement parfumé",
    "oeufs de poules élevées en cage"],
 "note": "⚠️ MANY OF THE SECOND GROUP CARRY LABEL PHRASING ON AN ORDINARY THING. 'raw "
    "pear', 'raw watermelon' and 'Raw Atlantic bass' are OFF's convention, not a distinct "
    "ingredient. So the group is not 46% junk, it is 46% junk plus real ingredients "
    "wearing a label phrase.",
}

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 4. Fifty from the low-confidence group, random, seed 20260824.
#
# ⚠️ THIS SAMPLE FOUND THE CULTIVAR CATEGORY, which was in nobody's stated expectation and
# turned out to be the largest single thing in the group: 989 low entries subclass a
# cultivar class, 799 of them apple cultivars. It entered under the STRONGEST rule because
# 'Cultivar or plant variety' matched zero of the 28,630 items.
# ─────────────────────────────────────────────────────────────────────────────────────
LOW_GROUP_SAMPLE = {
 "fruit cultivar or breeder-register name": ["A8812-3 (an accession code)",
    "Hormead Pearmain", "Neild's Drooper", "Willie Sharp", "Holland Pippin", "Metzrenette",
    "Gubener Warraschke", "Taubenapfel von St. Louis", "Blanca de Julio", "Shenandoah",
    "Fazli", "Minerva", "Victoria pineapple", "Ena chestnut", "Pomme a Cotes",
    "Brown Apple", "lambrusco salamino"],
 "appellation or PDO product": ["Schnittkäse Schlanderser leicht PAT", "Callu de cabrettu",
    "citron de Menton", "Grafschafter Goldsaft", "Nera di Oliena", "Tabardilla Antigua",
    "Hatchō Miso"],
 "OFF label or additive vocabulary": ["chromium picolinate", "modified flour",
    "calcium citrate malate", "precooked potato", "unprepared canadian bacon",
    "natural sage flavouring", "inedible crust", "seeded raisin"],
 "thin but genuine": ["veal stock", "monkfish tail", "carp broth",
    "calf's trotters wine broth", "Mutton leg", "primarily waxy potato", "vanilla seeds",
    "broad-leaved endive", "flatfish", "Thaï brown rice", "white seedless grape"],
 "well-attested and low ONLY because it borrows a name": ["Allium sativum (597 variations, "
    "5 sources)", "yam", "cocoa bean", "baby food", "bologna", "salad dressing",
    "Triticum dicoccum", "green sauce"],
 "note": "⚠️ THE LAST GROUP IS WHY CONFIDENCE IS NOT A QUALITY AXIS AND NO CUT USES IT. "
    "614 low entries carry three or more sources.",
}

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 5. All 35 punctuation merges that brought two DISTINCT Wikidata items together,
# read one by one. This set the apostrophe policy in build_join.py.norm_name.
#
# ⚠️ THE VERDICT: apostrophe to a SPACE, not to nothing. Dropping it entirely produced the
# five wrong merges below. Spacing it removes exactly those five and costs nothing.
# ─────────────────────────────────────────────────────────────────────────────────────
MERGE_SAMPLE = {
 "wrong, and caused by DROPPING the apostrophe": [
    "rose's + roses -> Rose's lime juice onto the plant genus Rosa",
    "m'ari + mari -> honey onto berry",
    "bull's-eye + bulls-eye -> a boiled sweet onto a Kraft barbecue sauce",
    "bo'tqa + botqa -> kasha onto porridge",
    "ha'ari + haari -> coconut milk onto milk"],
 "wrong, and survives the space policy": [
    "sweet tart + sweet-tart -> an open pie onto a Sweet-Tart apple cultivar",
    "tuba + tuba' -> sweet potato onto palm wine",
    "קראנץ + קראנץ' -> Nestlé Crunch onto Krantz cake"],
 "correct: a genuine Wikidata duplicate": ["cabécou d'Autan", "fig cake", "miyako manjū",
    "Verdale de l'Hérault"],
 "correct: broader and narrower": ["caviar and beluga caviar",
    "cheesecake and New York-style cheesecake", "jerky and dried meat and carne-seca",
    "navy bean and white bean", "freezie and ice pop"],
 "correct: the same thing in two traditions": ["roscón de reyes and king cake",
    "fried rice and nasi goreng", "yuvalama and Analı kızlı soup",
    "Leibniz-Keks and Petit-Beurre", "blood sausage and kaszanka", "dolma and sarma"],
 "correct: the dual nature": ["basil the species and basil the leaves"],
 "borderline, kept": ["couscous and Fonio jolloff", "Kusa mochi and kuzumochi",
    "T-bone steak and Bistecca alla fiorentina", "Tajima cattle and Kobe beef",
    "Turkish coffee and moka pot brew", "Jin deui and Onde-onde", "joelho and Lanche",
    "Крема and cream cheese", "L'Étivaz the cheese and L'Etivaz the hamlet",
    "Cabernet de Saumur and the Saumur region", "Côtes-de-bergerac and Bergerac",
    "Kinder Chocolate and the Kinder brand", "Caillé doux de Saint Félicien"],
 "verdict": "3 wrong in 3,996 merge groups, 0.075%, to collapse 4,214 duplicate buckets. "
    "None of the three appears in the recipe corpus.",
}

# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 6. Forty never-met merges, random, seed 20260823. Confirmed that 82.0% of
# punctuation merges already shared a source entry and are one thing under two spellings.
# ─────────────────────────────────────────────────────────────────────────────────────
NEVER_MET_SAMPLE = {
 "hyphenation variants of one thing": ["moon cakes / moon-cakes",
    "quarter pounder / quarter-pounder", "pan loaf / pan-loaf", "bog beans / bog-beans",
    "angel food cakes / angel-food cakes", "rice eaters / rice-eaters",
    "bean feasts / bean-feasts", "thai basilikum / thai-basilikum",
    "mimolette extra vieille / extra-vieille"],
 "bracket variants of one thing": ["chicken (food) / chicken food",
    "nova scotia (wine) / nova scotia wine", "napoleon (pastry) / napoleon pastry",
    "valdepenas (do) / valdepenas do", "graves-supérieures (aoc) / graves supérieures aoc",
    "anjou-villages (aoc) / anjou villages aoc"],
 "correct etymological merges": ["minga'u (Tupi) / mingau (Portuguese), both porridge",
    "mani'oka (Tupi) / manioka, both cassava"],
 "verdict": "no wrong merge found in the forty.",
}


# ─────────────────────────────────────────────────────────────────────────────────────
# SAMPLE 7. Every Wikidata item that Wikidata calls a Drink and not an ingredient, and
# that an Open Food Facts ingredient entry shares a name bucket with. 65 items, each one
# opened and its OFF match read. 39 right, 21 wrong, 5 borderline.
#
# ⚠️ THIS IS WHAT SET RULE 4 TO REQUIRE EQUAL ENGLISH NAMES RATHER THAN A SHARED BUCKET.
# The verdicts below are the reading. The rule is drawn through them rather than the
# other way round, and the 60% figure is what the shared-bucket version scores here.
#
# ⚠️ EVERY WRONG ONE IS A CROSS-LANGUAGE HOMOGRAPH OR A DRINK MEETING ITS OWN INGREDIENT.
# That is the third time in this pipeline. 'ni' is nickel and it is milk, 'gula' is sugar
# and it is yolk, 'granada' is a city and it is a pomegranate.
# ─────────────────────────────────────────────────────────────────────────────────────
DRINKS_SAMPLE = {
 "right, and the English names are equal": ["wine", "coffee", "tea", "green tea",
    "black tea", "white tea", "gunpowder tea", "rooibos", "instant coffee",
    "cold brew coffee", "decaffeinated coffee", "sake", "rice wine", "vermouth",
    "kombucha", "coconut water", "milk substitute", "apricot juice", "strawberry juice",
    "lingonberry juice"],
 "borderline, and the English names are equal": ["cider", "sparkling wine"],
 "right, but the OFF match is a PARENT rather than the same thing": ["hot chocolate",
    "horchata", "kvass", "Hibiscus tea", "masala chai", "drip coffee", "robusta coffee",
    "doujiang", "non-dairy creamer", "tibicos", "Federweisser", "instant tea",
    "fermented tea", "Kopi O", "caffe", "coffee drink", "nitro cold brew coffee",
    "mate based soft drink", "Ceylon tea"],
 "borderline, and no name match either": ["apple cider", "effervescent wine",
    "palm wine"],
 "wrong, a cross-language homograph": ["latte", "latte macchiato", "Uva", "Doogh",
    "Posca", "Turkish coffee", "julmust", "perry", "ayran", "lassi", "Tang",
    "Club-Mate", "cola", "Coca-Cola"],
 "wrong, a drink meeting the ingredient it is made from": ["weak coffee",
    "Rose's lime juice", "caffe crema", "coffee milk", "fruit wine", "beady wine",
    "frizzante"],
 "note": "⚠️ 'weak coffee' IS THE ONE THAT MATTERS AND IT IS WHY THE LOOSE VERSION IS "
    "NOT SHIPPABLE. Its OFF match is en:water, on a bucket carrying 33 recipe lines, so "
    "the shared-bucket rule would put a 'weak coffee' row in front of every line that "
    "says water. The equal-names test drops it, along with 'latte' matching milk, 'Uva' "
    "matching grape, 'Doogh' matching dough, 'Posca' matching vinegar and 'Turkish "
    "coffee' matching flour.\n\n"
    "⚠️ THE THIRD GROUP IS OUTSTANDING, NOT A LOSS. Those 19 read as real ingredients, "
    "and rule 4 declines them because the OFF entry names their PARENT. Declining "
    "'masala chai' because OFF says tea, and 'drip coffee' because OFF says coffee, is "
    "correct: the parent already has a row. Four are not covered by a parent row and are "
    "worth a reading when there is an evening for it, in this order: hot chocolate (OFF "
    "says cocoa), horchata (OFF says tigernut milk), kvass (OFF says sourdough), "
    "Hibiscus tea (OFF says roselle flower). None is urgent and none carries a recipe "
    "line today.\n\n"
    "⚠️ APPELLATIONS ARE NOT IN THIS SAMPLE AND THE RULE DOES NOT REACH THEM. Equal "
    "English names over the 1,034 excluded appellations admits six, four of which are "
    "wine regions, so build_library.drinks_rule excludes the appellation kind by name. "
    "It blocks exactly one item here, Cava.",
}


def _flatten():
    out = {}
    for term, (verdict, why) in HEAD_TERMS.items():
        out[term.casefold()] = f"{verdict}. {why}"
    for group, name in ((WIKTIONARY_SAMPLE, "Wiktionary sample"),
                        (OFF_ONLY_SAMPLE, "OFF-only sample"),
                        (LOW_GROUP_SAMPLE, "low-group sample"),
                        (DRINKS_SAMPLE, "excluded-drinks sample")):
        for verdict, items in group.items():
            if verdict == "note" or not isinstance(items, list):
                continue
            for item in items:
                key = item.split(" (")[0].casefold()
                out.setdefault(key, f"read in the {name}: {verdict}")
    return out


_INDEX = _flatten()


def lookup(name):
    """The recorded verdict for a name, or None. Used by build_library.py to surface a
    hand-read call in the sheet as evidence rather than inference."""
    return _INDEX.get((name or "").casefold())


def counts():
    return {
        "head terms read": len(HEAD_TERMS),
        "Wiktionary candidates read": sum(len(v) for v in WIKTIONARY_SAMPLE.values()
                                          if isinstance(v, list)),
        "OFF-only entries read": sum(len(v) for v in OFF_ONLY_SAMPLE.values()
                                     if isinstance(v, list)),
        "low-group entries read": sum(len(v) for v in LOW_GROUP_SAMPLE.values()
                                      if isinstance(v, list)),
        "distinct-Wikidata merges read": sum(len(v) for v in MERGE_SAMPLE.values()
                                             if isinstance(v, list)),
        "never-met merges read": sum(len(v) for v in NEVER_MET_SAMPLE.values()
                                     if isinstance(v, list)),
        "excluded drinks read": sum(len(v) for v in DRINKS_SAMPLE.values()
                                    if isinstance(v, list)),
    }


if __name__ == "__main__":
    total = counts()
    for k, v in total.items():
        print(f"  {v:4d}  {k}")
    print(f"  {sum(total.values()):4d}  TOTAL, and none of it can be regenerated")
