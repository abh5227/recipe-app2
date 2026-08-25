#!/usr/bin/env python3
"""reviewed.py: the hand-read verdicts behind every threshold in ingredient_cuts.py.

⚠️ THIS IS THE ONE FILE THAT CANNOT BE REGENERATED AT ANY PRICE. Everything else in the
pipeline is code plus a cached fetch. This is 433 entries opened one at a time, every
member row and every gloss read, across seven samples and the extraction readings. The
⚠️ EXTRACTION READINGS ARE MODEL-READ AND THE SEVEN SAMPLES ARE HAND-READ, which is a
real difference and is marked on every entry. The count is reviewed.counts(),
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
    "peppercorn, a Piper. Two unrelated plants under one spelling.\n\n"
    "⚠️ RULED 2026-08-25, AND THE RULING GOES AGAINST THE NEXT LINE RATHER THAN WITH IT. "
    "What is read below is right. AGROVOC, Open Food Facts, Wikidata and Wiktionary all "
    "call the peppercorn pepper and none of them is wrong. The authored 'pepper' row "
    "exists precisely because the bare word resolving to whichever of the two wins the "
    "lookup is the problem, so resolving to the general row is what it was authored for. "
    "build_library rule 4 takes 'pepper' and 'Pepper' off peppercorn over 10 recipe "
    "lines, and all ten are the bare word with nothing more specific to lose. Without "
    "this note the reading reads as unresolved."),
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


# ─────────────────────────────────────────────────────────────────────────────────────
# EXTRACTION. Category rows opened one at a time, every English name on the row grouped
# into concepts, and each concept judged an ingredient or not.
#
# ⚠️ THE POINT IS THAT A CATEGORY IS NOT RE-EXAMINED. 2,639 rows carry at least one
#    signal of holding members and 1,317 of them hold nothing, so most of this reading
#    ends in "nothing here". A verdict of nothing is worth exactly as much as a verdict
#    of five rows, and only one of the two gets recorded anywhere else.
#
# ⚠️ EXTRACTION IS TWO STEPS AND THE GROUPING IS THE FIRST. A name is not a member. On
#    'fortified wine' 15 candidate names cover 5 concepts, and on 'cream' 28 English
#    names cover 11, so roughly two to three names per concept both times. One row per
#    NAME would be worse than not extracting, since it would put Port and Porto and
#    Vinho do Porto in the library as three different drinks.
#
# ⚠️ THESE READINGS ARE MODEL-READ, NOT HAND-READ, AND THAT IS THE DIFFERENCE THAT
#    MATTERS IN THIS FILE. Every other sample here is Andy at the source rows. These are
#    a model laying out the names and grouping them, and the grouping is where the
#    judgement sits. They are recorded so the work is not repeated and so the calls are
#    visible to disagree with, not as settled. Each carries who read it.
# ─────────────────────────────────────────────────────────────────────────────────────
EXTRACTION_READ = {
 # ─────────────────────────────────────────────────────────────────────────────────────
 # THE 10-TO-19 ENGLISH-NAME SAMPLE, drawn at random with seed 20260825 from the 570
 # unread holders in that band, and read the way the 83 above were read.
 #
 # ⚠️ IT REFUTES THE 20-NAME NEGATIVE FILTER. The filter came from 43 holders below 20
 # names, none of which yielded, and was carried as "0 of 43". This second sample of 20
 # yields 4 to 8 rows, so the floor is not zero. What the sample also shows is WHY the
 # first one read as zero. The families down here are already mostly extracted. green
 # sauce names five members and two of them, salsa verde and chimichurri, already have
 # their own rows. nước mắm carries the whole Asian fish-sauce family and four of them,
 # nam pla, Shottsuru, garum and Budu, already have rows. That is the tamari shape at
 # scale, and it means the band is LOW YIELD rather than NO YIELD.
 # ─────────────────────────────────────────────────────────────────────────────────────
 "Riesling": ("0 rows, model-read 2026-08-25",
    "⚠️ MARKED AS A FAMILY FROM THE SCAN SHEET AND IT IS NOT ONE. 148 names, 116 of them "
    "English, 0 recipe lines, and every English name is the same grape. Rhine Riesling, "
    "Weisser Riesling, Johannisberg Riesling, Rajnski Rizling, Ryzlink Rynsky, "
    "Klingelberger, Petracine, Rossling and about a hundred more are the Vitis "
    "International Variety Catalogue synonym list for Vitis vinifera Riesling, carried "
    "in as wikidata aliases. Only 4 names are stated as a primary anywhere, and all four "
    "are spellings of Riesling in another language.\n"
    "  ⚠️ THIS IS THE COUNTER-SHAPE TO sausage AND dumpling, and it is what a large "
    "English-name count looks like when it is NOT a family. A culinary family holds "
    "different THINGS under one head. A cultivar register holds one thing under "
    "different NAMES. Both present as a big holder and the member count cannot tell "
    "them apart.\n"
    "  WHAT WOULD HAVE BEEN A FAMILY AND IS ABSENT: the Prädikatswein ripeness levels. "
    "Kabinett, Spätlese, Auslese, Beerenauslese, Trockenbeerenauslese and Eiswein are "
    "real, distinct, buyable products, and NONE of them is on this row or on any other "
    "row. Eiswein and ice wine sit on dessert wine. So the Riesling gap is a MISSING "
    "SET rather than a buried one, and extraction cannot reach it.\n"
    "  Welschriesling is a different grape entirely and already has its own row."),
 "Avena sativa": ("0 rows, model-read 2026-08-25",
    "222 names, 19 English, 0 lines. Spellings of oat plus parts and processes. Avenin "
    "is the storage protein, Oat fiber and Oatstraw are parts, Oat milling is a process "
    "and Pc98 (gene) is a crown-rust resistance gene. None is an ingredient."),
 "free-range eggs": ("0 rows, model-read 2026-08-25",
    "45 names, 12 English, 0 lines. ⚠️ Cage free and Cage-free egg are a DIFFERENT "
    "production standard from free-range in US labeling, not a spelling, so they are "
    "flagged rather than dismissed. Neither is an ingredient a recipe line asks for. "
    "Free-range management is farm practice and is contamination."),
 "food additive": ("0 rows, model-read 2026-08-25",
    "169 names, 11 English, 0 lines, 64 subclasses. A category rather than an "
    "ingredient. Its members are already in the subclass tree, and the hidden English "
    "names (adjuncts, E numbers, Chemical additives, Specialty Food Ingredients) are "
    "restatements of the head."),
 "dried apricot": ("0 rows, model-read 2026-08-25",
    "45 names, 11 English, 0 lines. ⚠️ ONE POSSIBLE MEMBER, recorded and not taken. "
    "kuraga and uryuk are both Central Asian and in a market they are different goods, "
    "kuraga pitted and halved, uryuk whole with the pit in. No source on the row states "
    "the distinction, so taking it would be a world-judgement the row does not support. "
    "Gheysi is Persian and Turkish apricot is an origin."),
 "green sauce": ("⚠️ 2 ROWS AVAILABLE, NOT TAKEN, model-read 2026-08-25",
    "48 names, 17 English, 0 lines. ⚠️ A FAMILY, AND WIKIDATA SAYS SO IN WORDS. Its own "
    "description reads 'family of cold, uncooked sauces based on herbs, including the "
    "Spanish and Italian salsa verde, the French sauce verte, the German Grüne Soße or "
    "Frankfurter Grie Soß, and the Argentinian chimichurri'. That is five members named "
    "by the source.\n"
    "  ⚠️ THE TAMARI CHECK CUTS THE YIELD FROM FIVE TO TWO. salsa verde already has a "
    "row (Q20747642) and so does chimichurri (Q1073142). Only sauce verte and Grüne Soße "
    "with its Frankfurter Grie Soß name have no home. Frankfurter Grüne Soße is a "
    "protected designation over seven named herbs, so it is a real distinct product.\n"
    "  ⚠️ HELD FOR ANDY. This is one of the two hits that refute the 20-name filter."),
 "Lancashire cheese": ("0 to 3 rows, model-read 2026-08-25",
    "37 names, 14 English, 0 lines. ⚠️ BORDERLINE AND FLAGGED. Creamy Lancashire, "
    "Crumbly Lancashire and Tasty Lancashire are the three named styles of the cheese "
    "and a shop sells them as three things. Beacon Fell Traditional Lancashire is the "
    "protected one. Whether a style of one cheese is a row or an attribute of a row is "
    "the same question the tomato three-axis case asked, and it is not settled here."),
 "soybean sprout": ("0 rows, model-read 2026-08-25",
    "41 names, 12 English, 0 lines. Kongnamul and Congnamul are romanizations of the "
    "same Korean word. ⚠️ Beansprouts is CONTAMINATION and worth naming, since mung bean "
    "sprouts are a different product from soybean sprouts and a recipe line reading "
    "'bean sprouts' would land here wrongly."),
 "poppy seed": ("0 rows, model-read 2026-08-25",
    "110 names, 18 English, 0 lines. Khas khas, Posto, Postu and mohn are the seed in "
    "Hindi, Bengali and German. Poppy seed grinder is equipment and Poppyseed filling is "
    "a preparation, both contamination. ⚠️ The real distinction, blue against white "
    "poppy seed, is on NEITHER this row nor any other, so it is a missing set."),
 "pea": ("0 rows, model-read 2026-08-25",
    "248 names, 13 English, 0 lines, 23 merged entries. ⚠️ MOSTLY CONTAMINATION. Olivier "
    "salad, Russian salad, American salad, Party Salad and vegetable salad are one DISH "
    "merged onto the pea row. field pea and garden pea are a real agronomic distinction "
    "from AGROVOC, and neither is what a recipe line means by peas."),
 "Olallieberry": ("0 rows, model-read 2026-08-25",
    "15 names, 14 English, 0 lines, and 6 of them are misspellings of the same berry. "
    "olallaberry, olalliberry, ollalaberry, ollaliberry, ollalieberry, Olallie berry. "
    "⚠️ THE PUREST SPELLING-VARIANT CASE IN THE SAMPLE, and useful as a negative "
    "example, since 14 English names on a 15-name row looks exactly like a holder."),
 "peach": ("0 rows, model-read 2026-08-25",
    "148 names, 11 English, 0 lines. ⚠️ TWO CONTAMINATIONS, both cross-language. Momo "
    "and Mo:mo are the Nepali and Tibetan DUMPLING, reached because momo is also "
    "Japanese for peach. fishing and catching fish come from AGROVOC. Neither has "
    "anything to do with the fruit."),
 "Kanpei": ("0 rows, model-read 2026-08-25",
    "13 names, 10 English, 0 lines. One Japanese citrus cultivar with its parentage "
    "written out eight ways. Dekopon x nishinokaori, Dekopon × nishinokaori, "
    "Nishinokaori x dekopon, Shiranui × nishinokaori and so on. Cross notation, not "
    "members."),
 "Nephelium lappaceum": ("0 rows, model-read 2026-08-25",
    "86 names, 15 English, 0 lines. Rambutin, Ramutan, Ramutans and ramboostan are "
    "spellings. Ang Mo Dan and Mamon chino are the fruit in Singapore and Central "
    "America. Wild rambutan is the uncultivated form and no source states it as a "
    "separate product."),
 "Gruyère": ("0 to 1 rows, model-read 2026-08-25",
    "55 names, 12 English, 0 lines. ⚠️ ONE BORDERLINE MEMBER. French Gruyère and Swiss "
    "Gruyère are two protected cheeses that share a name and differ in holes, age and "
    "rind. A cook told to use Gruyère is told one thing, so this is a note on the row "
    "rather than a second row, and it is flagged rather than decided."),
 "chocolate liquor": ("0 rows, model-read 2026-08-25",
    "96 names, 13 English, 0 lines. cocoa mass, cacao mass, cacao paste, cocoa liquor "
    "and Pure cocoa are one thing under five names. ⚠️ chocolate liqueur is flagged as a "
    "member and IS NOT ONE. It is an alcoholic drink, and liquor against liqueur is a "
    "one-letter homograph that the store cannot see. This is the clearest single-letter "
    "case found so far."),
 "whitebait": ("1 to 3 rows available, NOT TAKEN, model-read 2026-08-25",
    "40 names, 11 English, 0 lines. ⚠️ A REAL FAMILY IN THE LOW BAND. shirasu (Japanese, "
    "boiled and dried), Gianchetti (Ligurian) and Chirimen jako are named products, and "
    "New Zealand whitebait is a DIFFERENT ANIMAL, a galaxiid rather than a clupeid, "
    "sharing the English word. None of the four has a row. Whitebait fritter is a dish "
    "and Whitebaiting is the activity, both contamination."),
 "white rice": ("0 rows, model-read 2026-08-25",
    "75 names, 11 English, 3 recipe lines. polished rice and milled rice are the same "
    "thing. ⚠️ TWO FILIPINO CONTAMINATIONS. Pinais is fish wrapped in banana leaf and "
    "carries its own article title onto this row, and Sinaing is a cooking method. "
    "Neither is white rice, and Pinais being an article_title means it reads as a "
    "primary name."),
 "nước mắm": ("⚠️ 1 TO 2 ROWS AVAILABLE, NOT TAKEN, model-read 2026-08-25",
    "28 names, 15 English, 0 lines. ⚠️ THE SECOND FAMILY IN THE SAMPLE. The row is "
    "Vietnamese fish sauce and it carries the whole Asian family through the Fish sauce "
    "article. Cambodian, Chinese, Japanese and Korean fish sauce, plus Teuk trey and Nam "
    "pa.\n"
    "  ⚠️ THE TAMARI CHECK AGAIN, and it takes most of it. nam pla, Shottsuru, garum and "
    "Budu already have rows. patis sits on the general fish sauce row, which carries 24 "
    "recipe lines. aekjeot sits on jeotgal. Only Teuk trey (Cambodia) and arguably Nam "
    "pa (Laos) have no home anywhere.\n"
    "  ⚠️ HELD FOR ANDY, with green sauce."),
 "cranberry": ("0 rows, model-read 2026-08-25",
    "158 names, 15 English, 0 lines. V. oxycoccos, V. microcarpum, Oxycoccos, Fenberry "
    "and Common cranberry are species-level botany rather than things a cook buys "
    "separately. Cranberry bog is a place and Cranberries extract is an industrial "
    "input, both contamination."),
 "sardine": ("0 to 1 rows, model-read 2026-08-25",
    "39 names, 17 English, 0 lines. Grilled sardines, Sardinha assada and Tinned "
    "sardines are preparations. ⚠️ ONE BORDERLINE MEMBER. pilchard is a real British "
    "distinction, the same fish over about 15 centimeters sold under a different name "
    "and usually canned, and pilchard has NO row. It sits on Clupea, the genus, which is "
    "an animal rather than a food."),
 "cream": ("1 row extracted, model-read 2026-08-25",
    "413 variations, 28 of them English, grouping to 11 concepts and 4 further names for "
    "cream itself. ONE concept is an ingredient carrying recipe lines: heavy cream, at 7 "
    "lines, which landed on this row until it was extracted.\n"
    "  THE GROUPS. (1) heavy cream, alone, the US 36 percent product, Open Food Facts "
    "states it as a canonical_name and files it under cream. (2) butterfat, milkfat, "
    "milk fat, one concept, the fat fraction rather than the cream. Read and DECLINED: "
    "it is a label term and a measurement, no recipe line reaches it, and what a cook "
    "buys is the cream. (3) caffe crema, caffè crema, one coffee drink, two spellings, "
    "reached through Italian crema, the same cross-language name match as latte for milk "
    "and gula for sugar. (4) Krema, Kréma, one Greek dessert, two spellings. (5) pastel "
    "de nata, pastéis de nata, pastel de Belém, pastéis de Belém, one Portuguese tart, "
    "singular, plural and its Belém name. (6) panera (dessert), held apart from group 5 "
    "and ⚠️ THE ONE I AM UNSURE OF, since it may be the same tart under a Spanish name "
    "and no source on the row says either way. (7) cream soup, puréed soup, one dish. "
    "(8) rum, rhum, one spirit, reached because Dutch room means cream and the bucket "
    "collides. (9) Panax, ginseng, one plant genus from AGROVOC, and ginseng already has "
    "its own row. (10) key, keyseat, keyway, Wiktionary engineering senses. (11) panne, "
    "⚠️ ALSO UNSURE, a Wiktionary word that is French for both a fabric and pork fat.\n"
    "  WHAT STAYS ON CREAM: dairy cream, milk cream, sweet cream and room are further "
    "names for the holder, not members, so they stay.\n"
    "  ⚠️ THE OFF SUBTREE IS A SEPARATE JOB AND IS NOT DONE. Open Food Facts files 34 "
    "children under cream and 13 have no row, including single cream, whipping cream and "
    "eight graded by milk fat percentage. None of them is a NAME on this row, so reading "
    "the row cannot reach them. They are an admission question rather than an extraction "
    "one."),
 "flour": ("nothing to extract, model-read 2026-08-25",
    "453 variations and 6 English orphan primaries, none of them a member. Three are "
    "merge contamination that belongs on the reading pile instead: Turkish coffee, Koba "
    "and UN, the last being AGROVOC's United Nations arriving through a Chinese name "
    "bucket. The other three are cereal flour, cereal flours and flours, which are "
    "further names for flour itself. The real members already have their own rows: "
    "all-purpose flour and bread flour both moved off this row during resolution, and 18 "
    "of the 24 children Open Food Facts files under flour resolve to rows that exist.\n"
    "  ⚠️ MEASURED WRONG ONCE. An earlier sweep put flour at 16 orphan members by "
    "counting any name carried by a field named label, prefLabel, canonical_name, name, "
    "article_title or word. Ten of those 16 were Middle English spellings of flour from "
    "Wiktionary: fflour, fflowr, fleur, floure, flowr, flowre, flowyr, flor, flur, floor. "
    "Reading the field set the pipeline actually uses, build_library.PRIMARY_CLAIM, gives "
    "6. See docs/measuring-the-premise.md."),
 "white sugar": ("nothing to extract, model-read 2026-08-25",
    "3 candidate names, 1 concept, 0 rows. granulated sugar (35 lines), refined sugar, "
    "regular sugar, table sugar, white granulated sugar and white refined sugar are ONE "
    "concept and it is white sugar itself. ⚠️ 'sand' is AGROVOC's mineral and is "
    "contamination, not a member."),
 "baking powder": ("nothing to extract, model-read 2026-08-25",
    "1 candidate, 0 concepts. bakery additives and flour improvers are AGROVOC BROADER "
    "terms that merged downward. A parent is not a member."),
 "peppercorn": ("nothing to extract, model-read 2026-08-25",
    "2 candidates, 2 concepts, 0 rows. Piper nigrum is the same plant under its botanical "
    "name. grey pepper and gray pepper are one concept, a French grind of black pepper, "
    "DECLINED as a grade rather than an ingredient. Pebre and pebre are a Chilean "
    "condiment and are contamination.\n"
    "  ⚠️ THE REAL PROBLEM ON THIS ROW IS NOT A MEMBER. It also holds 'black pepper' at 13 "
    "recipe lines and 'white pepper' at 9, and BOTH ALREADY HAVE THEIR OWN ROWS. No "
    "resolution rule reaches the pair, so 22 recipe lines land on a row that holds two "
    "other rows' canonicals. That is the 668-pair class, and it is Andy's to read."),
 "vegetable oil": ("nothing to extract, model-read 2026-08-25",
    "3 candidates, 1 concept, 0 rows. plant oil, plant oils, vegetable oils, vegetal oil, "
    "vegetal oils, vegetable oil and fat and vegetable fat and oil are ONE concept and it "
    "is the holder. ⚠️ 'Brunsli' is a Swiss Christmas biscuit and is contamination."),
 "soy sauce": ("read, one concept blocked on a merge, model-read 2026-08-25",
    "2 candidates, and the interesting one is tamari.\n"
    "  ⚠️ TAMARI WAS EXTRACTED AND THE ROW WAS REVERTED THE SAME DAY. tamari, tamari "
    "sauce and tamari soy sauce are one concept and a genuinely different product, "
    "wheat-free and brewed from what separates off miso. But a row for it ALREADY EXISTS "
    "under the canonical 'tamari shoyu' (Wikidata Q3514675, one source, 5 names), and the "
    "authored row seeded that same item and split it in two. So this is a RENAME and a "
    "merge, not an extraction, and both are Andy's call.\n"
    "  ⚠️ AND IT EXPOSED A LIMIT OF THE MEMBER MEASURE. member_names asks whether another "
    "row owns the name as its CANONICAL. 'tamari shoyu' does not own 'tamari', so tamari "
    "read as an orphan when its concept already had a row. Every extraction has to check "
    "the concept, not just the name.\n"
    "  Toyo and toyo are Filipino for soy sauce, the same concept. ganjang, shoyu and "
    "jiangyou are the Korean, Japanese and Chinese national products, left alone."),
 "egg as food": ("nothing to extract, model-read 2026-08-25",
    "1 candidate and it is not a member. 'eggs' carries 20 recipe lines and is the PLURAL "
    "of the authored 'egg' row. norm_name does not stem, so the name meets no owner and "
    "no rule moves it. ⚠️ 20 LINES ON A PLURAL IS A STEMMING PROBLEM, NOT AN EXTRACTION "
    "ONE, and it is the second time this exact shape has surfaced. 'Pu'er tea' on this "
    "row is contamination."),
 "turmeric": ("nothing to extract, model-read 2026-08-25",
    "2 candidates, 2 concepts, 0 rows. Curcuma and curcuma are the genus, the same thing. "
    "turmeric powder (3 lines), ground turmeric and powdered turmeric are ONE concept and "
    "it is the STRENGTH shape rather than a member, the same class as tamarind paste: "
    "fresh root against ground, where the reader gets a plausible answer at the wrong "
    "ratio. Left for the strength decision rather than extracted."),
 "sesame oil": ("nothing to extract, model-read 2026-08-25",
    "1 candidate, 0 concepts that are food. ⚠️ Myanmar, Burma, Union of Myanmar, "
    "Socialist Republic of Burma and Republic of the Union of Myanmar are ONE concept and "
    "it is a COUNTRY, arriving from AGROVOC, which is a major sesame producer. Five names "
    "of a nation state on a bottle of oil. sesame seed oil is the holder.\n"
    "  ⚠️ THE DISTINCTION A COOK NEEDS IS NOT ON THIS ROW AT ALL. Toasted sesame oil has "
    "its own row at 2 lines, and plain against toasted is the choice that matters."),
 "bay leaf": ("nothing to extract, model-read 2026-08-25",
    "2 candidates, 2 concepts. bay laurel, laurel, laurel leaves, sweet bay, bay, bay "
    "leaves and bayleaf are ONE concept, the plant and its leaf. ⚠️ lager and lagers are "
    "the beer and are contamination. Turkish against Californian bay is the distinction "
    "worth having and no source on this row carries it."),
 "Allium sativum": ("1 row extracted, model-read 2026-08-25",
    "2 candidates and one of them is a different species. ⚠️ WILD GARLIC IS Allium "
    "ursinum, NOT A VARIETY OF Allium sativum. A woodland plant with broad leaves and no "
    "bulb worth using. About 200 names for it were sitting on the garlic row in 115 "
    "languages: wild garlic, ramsons, ransoms, buckrams, bear leek, bear's garlic, "
    "broad-leaved garlic, wood garlic, Bärlauch, ail des ours, черемша. EXTRACTED.\n"
    "  fresh garlic is a FORM of the holder, not a member, and is left.\n"
    "  ⚠️ THIS ROW'S OWN CANONICAL IS A BINOMIAL and 'garlic' is a separate row. That is a "
    "merge question and is not touched here."),

 # ── holders 11 to 30 of the extraction list, model-read 2026-08-25 ──────────────────
 "Coriandrum sativum": ("nothing to extract, model-read 2026-08-25",
    "2 names, 1 concept, and BOTH ITS PRODUCTS ALREADY HAVE ROWS. Coriander and coriander "
    "sit here while 'coriander seed' and 'cilantro' are rows of their own. ⚠️ THE BARE "
    "WORD NEEDS THE AMERICAN READING, which makes it the seed and the leaf 'cilantro'. "
    "That is a rename plus a merge and it is Andy's. The canonical is a binomial too."),
 "icing sugar": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept, and it is the holder. powdered sugar (4 lines), confectioner's "
    "sugar in seven spellings, powder sugar, pulverized white sugar and snow powder are "
    "all one thing. ⚠️ RENAME CANDIDATE under the American reading: the US name is "
    "powdered sugar and it carries the lines."),
 "milk": ("nothing to extract, model-read 2026-08-25",
    "6 names, 4 concepts, NONE of them milk. latte, latte macchiato and about twenty "
    "spellings of caffè latte are ONE concept and it is a coffee drink, reached through "
    "Italian latte. ⚠️ 'nickel' is the ni homograph, and this is the third time that "
    "cross-language shape has cost something. 'calcium ammonium nitrate' arrives through "
    "the initialism CAN and 'lakes' through LAC, both AGROVOC."),
 "food paste": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts. 'Paste' is already carried by pastry dough. pasty, pastie, "
    "pastey, pasteija and British pasty are ONE concept and it is a Cornish dish."),
 "brown sugar": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. blonde sugar, cassonade, soft brown sugar and brown caster sugar "
    "are the holder under other names. ⚠️ Light against dark brown sugar is the "
    "distinction a cook needs and NO name on this row carries it."),
 "garlic": ("nothing to extract, model-read 2026-08-25",
    "4 names, 4 concepts, zero food. ⚠️ THE HEAD OF THE LIST IS AGROVOC SYMBOLS AND "
    "INITIALISMS. aluminium, aluminum and 'Al (symbol)' are ONE concept and it is a "
    "metal. artificial intelligence and AI are another. 'Allium' is the genus and 'azu' "
    "is a fish already carried by Allium sativum. Same class as the Wiktionary initialism "
    "expansions, arriving from a different source."),
 "tehina": ("1 row extracted, model-read 2026-08-25",
    "3 names, 2 concepts. tahini (9 lines), Tahina, Tahin, T'hina, Techina, Tchina, "
    "Nerigoma, sesame butter and sesame paste are ONE concept and it is the holder. ⚠️ "
    "EXTRACTED halva, a dense sesame confection set with sugar syrup, which had about "
    "fifteen names here: halvah, halava, halawa, haleweh, halvaa, helva, helava, khalva, "
    "aluva. A line saying halva reached the ingredient it is made from.\n"
    "  ⚠️ RENAME CANDIDATE AND IT IS A CLEAR ONE. The canonical is 'tehina' and all 9 "
    "recipe lines say tahini."),
 "coriander seed": ("nothing to extract, model-read 2026-08-25",
    "2 names, 1 concept. coriander seeds (9 lines) is the plural of the canonical and "
    "Coriandrum is the genus."),
 "butter": ("nothing to extract, model-read 2026-08-25",
    "5 names, 5 concepts, zero food that is butter. beryllium with 'Be (symbol)' is a "
    "metal, burdock is already carried by burdock root, compotes is AGROVOC, kibbeh is a "
    "Levantine dish and powidl is a plum spread. ⚠️ Cultured, whey, spreadable and "
    "lightly salted butter are all on the row and none is flagged, because Open Food "
    "Facts states them as synonyms rather than as primary names."),
 "cayenne pepper": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. Capsicum frutescens is the species."),
 "za'atar": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. zaatar and about twelve transliterations are the holder. ⚠️ sumac, "
    "soumak and sumagh are on this row and sumac HAS ITS OWN ROW at 4 recipe lines. A "
    "blend holding one of its ingredients is Andy's to read and is already flagged."),
 "onion": ("nothing to extract, model-read 2026-08-25",
    "6 names, 5 concepts, none of them an onion variety. ⚠️ cep, Boletus edulis and "
    "porcini mushroom are ONE concept and it is a MUSHROOM, through French cèpe. Piyaz is "
    "a Turkish dish, Tipula is the crane fly, fattening is AGROVOC, Allium cepa is the "
    "species and already on scallion, and onions is the plural."),
 "honey": ("nothing to extract, model-read 2026-08-25",
    "4 names, 4 concepts. bee honey is the holder. ⚠️ 'common sole' is a FISH and "
    "'cherry' is already carried by cherry tomato, both from Open Food Facts. copper with "
    "'Cu (symbol)' is the metal, the same AGROVOC symbol shape as garlic and butter.\n"
    "  ⚠️ 43 items subclass this row and heather honey is the only varietal name on it."),
 "cow's milk": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. cow milk, bovine milk, dairy milk, homogenized milk and liquid "
    "milk are the holder. Whole, skim and semi-skimmed are not on the row at all."),
 "cinnamon": ("3 rows extracted, model-read 2026-08-25",
    "7 names, 4 concepts, and THREE OF THEM ARE DIFFERENT SPECIES SOLD UNDER ONE WORD.\n"
    "  EXTRACTED Ceylon cinnamon, from ceylon cinnamon, Cinnamomum verum, Cinnamomum "
    "zeylanicum and Cannelle de Ceylan. Thin brittle bark, milder and sweeter.\n"
    "  EXTRACTED cassia, from cassia, Cinnamomum cassia, Cinnamomum aromaticum and "
    "chinese cinnamon. Thick hard bark, hotter and one-note, and ⚠️ THE THING A US RECIPE "
    "ALMOST CERTAINLY MEANS BY CINNAMON.\n"
    "  EXTRACTED Indonesian cinnamon, from Cinnamomum burmannii and Cinnamomum burmanni. "
    "The commonest bark in US ground cinnamon.\n"
    "  Cinnamomum is the genus and kanelstenger is Norwegian for cinnamon sticks.\n"
    "  ⚠️ TWO ENTRIES IN THE cassia BUCKET ARE NOT CASSIA and were left out of the seed. "
    "Wikidata Q7370926 is Rougui tea, a Chinese oolong. AGROVOC c_1363 is the legume "
    "genus Cassia, which its Chinese label gives away as the golden shower tree."),
 "chicken broth": ("nothing to extract, model-read 2026-08-25",
    "4 names, 3 concepts. chicken stock (4 lines) is the same concept as the holder and "
    "⚠️ IT IS ALSO ON 'broth', so 4 lines land on two rows. Chicken soup, chicken soup "
    "and chicken noodle soup are ONE concept and it is a dish. Caldo de pollo is Spanish "
    "for the holder."),
 "cilantro": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. coriander leaf, coriander leaves and Chinese parsley are the "
    "holder, and coriander leaf is already carried by Coriandrum sativum."),
 "garlic powder": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. dried garlic is the holder. Nothing else in English is on the row."),
 "tomato paste": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. tomato concentrate and Kunserva are the holder. ⚠️ 'tomato purée' "
    "is on this row and HAS ITS OWN ROW, which is the US and UK split already named: the "
    "US sense is a thinner sauce and the UK sense is this. Sun-dried tomato paste is "
    "arguably a fourth thing and no source states it as a primary name."),
 "egg yolk": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts, neither an egg. ⚠️ 'Amanita caesarea' is a MUSHROOM, named for "
    "being the color of a yolk, and 'Yema' is a Spanish and Filipino confection."),

 # ── holders 31 to 51 of the extraction list, model-read 2026-08-25 ──────────────────
 "lime juice": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept, and it is a BRAND. Rose's lime juice is a sweetened cordial, and "
    "the pipeline cuts brands by kind everywhere else."),
 "cereal": ("1 row extracted, model-read 2026-08-25",
    "6 names, 6 concepts. ⚠️ EXTRACTED bread, see the bread entry. Gurnard and Red gurnard "
    "are ONE concept and a FISH, 'rock snail' is a mollusc, 'Pan' is Spanish for bread and "
    "already on roti, cereals is the plural and grain crops is an AGROVOC broader term."),
 "paprika": ("nothing to extract, model-read 2026-08-25",
    "2 names, 1 concept. paprika powder (1 line) is the form and 'paprika or bell pepper' "
    "is Open Food Facts declining to choose, which is honest of it and not a member."),
 "basil": ("1 row extracted, model-read 2026-08-25",
    "1 name, 1 concept, and it is a different herb. ⚠️ EXTRACTED spearmint, Mentha spicata, "
    "which Open Food Facts states as a primary name on basil.\n"
    "  ⚠️ Falooda seed, Sabja, Hột é and Kasa kasa are on this row and are BASIL SEED, a "
    "separate product used in drinks. No source states one as a primary name so none is "
    "flagged, and it is worth a row when someone reads it."),
 "ground pork": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. minced pork is the same thing and the canonical already uses the "
    "American word."),
 "broth": ("1 row extracted, model-read 2026-08-25",
    "10 names, 6 concepts. ⚠️ EXTRACTED bone broth, simmered from bones long enough to "
    "draw out the gelatin that sets it in the fridge.\n"
    "  ⚠️ 'stock' IS RECORDED AS UNSURE RATHER THAN EXTRACTED, and the reason is the "
    "sources. Stock from bones against broth from meat is a real distinction, but Open "
    "Food Facts entry 6527 states Stocks, bouillon, broth, broths and stock on ONE entry, "
    "and Wikidata Q275068 and Q3075310 each state both. Nothing in the store separates "
    "them, so extracting would be picking rather than reading.\n"
    "  ⚠️ READ TWICE. The first pass on 2026-08-25 recorded it as members found and not "
    "extracted, on the reasoning that no recipe line reached any of them. That was "
    "priority, not a verdict, and the second pass extracted bone broth anyway, because "
    "'nobody in this corpus cooks it yet' is the corpus-as-target error.\n"
    "  fish stock and fish fumet are ONE concept and fish broth already has the row. soup, "
    "clear soup, canned soup, cold soup, condensed soup and dessert soup are one concept "
    "and a dish. Rosół is Polish and already on chicken broth, Yahni and yahni are one "
    "Turkish concept already on ragù, blöta is Swedish."),
 "bread": ("EXTRACTED 2026-08-25, model-read",
    "⚠️ 4 RECIPE LINES SAY BREAD AND THE LIBRARY HAD NO ROW FOR IT. The name sat on "
    "'cereal', the grain crop, and on 'roti', an Indian flatbread, so which one answered "
    "depended on which won the lookup. The commonest food in the corpus with no row of "
    "its own, and the biggest wrong answer found since eggs."),
 "potato": ("nothing to extract, model-read 2026-08-25",
    "7 names, 7 concepts, none a potato variety. ⚠️ 'Canada' is the country and "
    "'Dioscorea alata' is a YAM. Irish potato candy is a confection with no potato in it, "
    "potato cake is a dish, Solanum tuberosum is the species, potatoes is the plural, and "
    "tuber is already carried by truffle."),
 "cannabis": ("nothing to extract, model-read 2026-08-25",
    "6 names, 6 concepts. ⚠️ 'Kinder' and 'Kinder Chocolate' are a confectionery brand. "
    "buds, pots, herb and dagga are the holder under other words."),
 "Foeniculum vulgare": ("2 rows extracted, model-read 2026-08-25",
    "6 names, 6 concepts, and ⚠️ THREE OF THEM ARE DIFFERENT PLANTS ON A FENNEL ROW.\n"
    "  EXTRACTED dill, Anethum graveolens. Fennel was once filed as Anethum foeniculum, so "
    "the genus name collided and dill arrived.\n"
    "  EXTRACTED fenugreek, Trigonella foenum-graecum, which reached this row through the "
    "shared Latin foenum rather than any resemblance.\n"
    "  'Cuminum cyminum' is CUMIN and 'Lens' is the lentil genus, and both already have "
    "rows, so neither is extracted. Foeniculum is the genus and fennel is already on "
    "fennel fruit.\n"
    "  ⚠️ RENAME CANDIDATE. The canonical is a binomial and the row is fennel."),
 "vanilla": ("nothing to extract, model-read 2026-08-25",
    "6 names, 5 concepts. Bourbon vanilla is already on Madagascar vanilla, which is the "
    "same thing. Vanilla (genus), Vanilla planifolia and vanilla (spice) are the plant and "
    "the spice, herbaceous plants is an AGROVOC broader term.\n"
    "  ⚠️ 'vanilla flavouring' IS RECORDED AS UNSURE. With Artificial vanilla, Vanilla "
    "substitute and Vanilla flavor it could be one concept, imitation vanilla, which is a "
    "real product distinct from the extract at 37 recipe lines. Or it could be flavoring "
    "in general. No source on the row separates the two."),
 "bell pepper": ("nothing to extract, model-read 2026-08-25",
    "4 names, 3 concepts. Capsicum annuum is the species and covers chilies too, sweet "
    "peppers is the plural, yellow bell pepper is a color and Open Food Facts has the "
    "other three as well. ⚠️ 'Paprika' and 'Red paprika' are on this row and paprika has "
    "its own."),
 "pine nut": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. pine nuts (4 lines) is the plural, Pinus edulis is one pine "
    "among several that give edible nuts, Pignolo is Italian."),
 "roti": ("nothing to extract, model-read 2026-08-25",
    "3 names, 2 concepts. ⚠️ 'bread' at 4 lines left this row when bread was extracted. "
    "chapati with twelve spellings and Indian Bread are the holder, since chapati is a "
    "roti rather than a different thing."),
 "mozzarella": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept, AND ITS ROW ALREADY EXISTS. buffalo mozzarella is carried by "
    "'Mozzarella di Bufala Campana PDO'. ⚠️ THE TAMARI SHAPE: the concept has a row under "
    "a name nobody writes, so this is a rename rather than an extraction.\n"
    "  Fiordilatte and Fior-di-latte are cow's milk mozzarella and are arguably a third "
    "thing. No source states either as a primary name."),
 "sumac": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. Rhus is the genus. sumach, sumaq and Sicilian sumac are spellings."),
 "table salt": ("nothing to extract, model-read 2026-08-25",
    "8 names, 6 concepts, and only one is salt. common salt, sodium chloride and NaCl are "
    "the holder. ⚠️ 'Shorea robusta seed oil', 'Sal oil' and 'Sal tree oil' are ONE "
    "concept and an INDIAN TREE OIL, reached through sal. 'jumping', 'soil' and 'sun' are "
    "AGROVOC concepts that the symbol cut does not reach, because their entries state no "
    "symbol. 'viand' is a Wikipedia label."),
 "spinach": ("nothing to extract, model-read 2026-08-25",
    "3 names, 2 concepts. Spinacia is the genus, spinach leaves is the form, and 'spinach "
    "or amaranth' is Open Food Facts declining to choose."),
 "cumin": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts. Cuminum is cumin's genus. ⚠️ 'Carum' IS CARAWAY'S GENUS and is "
    "already flagged for Andy. Both are genera rather than members."),
 "Parmesan": ("nothing to extract, model-read 2026-08-25",
    "2 names, 1 concept. Parmigiano-Reggiano and parmigiano reggiano are the holder under "
    "its protected name. ⚠️ 'Grana Padano' is on this row and is a DIFFERENT CHEESE, made "
    "under different rules. No source states it as a primary name here so it is not "
    "flagged, and it is worth a row."),
 "tomato": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts. Solanum is the genus and tomatoes (3 lines) is the plural."),
 "crushed red pepper": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept, and it is ⚠️ MILITARY RATIONS. field ration, Combat Ration Pack, "
    "combat ration, ration and One-One are one concept reached through the initialism CRP. "
    "The same shape as the Wiktionary and AGROVOC initialisms, from Wikipedia this time."),
 "distilled vinegar": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. spirit vinegar, white vinegar and virgin vinegar are the holder. "
    "⚠️ spirit vinegar is ALSO on 'malt vinegar', which is the right-row-wrong-traffic case "
    "Andy raised, seen from the other side."),

 # ── holders 52 to 72, model-read 2026-08-25. ZERO extractions, and that is the finding ──
 "ground cinnamon": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. cinnamon powder is the old canonical. The three species came off "
    "the general 'cinnamon' row, not this one."),
 "cornstarch": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. corn starch, Maize starch, Maizena and Corn-starch are the holder."),
 "ground ginger": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. ginger powder is the old canonical, and Open Food Facts is the "
    "only source on the row."),
 "sesame seed": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts, none extractable. Sesamum indicum is the species, sesame seeds "
    "is the plural, gingelly and til are Indian names for the same. ⚠️ 'sesame' has no row "
    "and carries no line, so the plant against the seed is a distinction nothing needs yet."),
 "fennel seeds": ("nothing to extract, model-read 2026-08-25",
    "3 names, 1 concept. fennel fruit is the old canonical and fennel seed the singular. "
    "⚠️ 'fennel' the BULB is a different vegetable from this spice and has no row of its "
    "own. Its concept IS the row called 'Foeniculum vulgare', so that is a rename."),
 "buttermilk": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. Mattha is an Indian drink made from it. ⚠️ 'Cultured buttermilk' "
    "and 'sweet cream buttermilk' are on the row and are genuinely different products, "
    "fermented against the liquid left from churning. Neither is stated as a primary name "
    "so neither is flagged, and it is worth a reading."),
 "ginger": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. Zingiber is the genus. ⚠️ 'hing' is on this row and hing is "
    "ASAFOETIDA, which has its own row at 1 recipe line. A spice on the wrong spice."),
 "sea salt flakes": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. flake sea salt is the same words reordered."),
 "white vinegar": ("nothing to extract, model-read 2026-08-25",
    "1 name, 1 concept. table vinegar is the holder."),
 "green bean": ("nothing to extract, model-read 2026-08-25",
    "6 names, 5 concepts. ⚠️ Cornetto and cornetto are ONE concept and an ICE CREAM, "
    "already carried by pain au chocolat. Vigna unguiculata sesquipedalis is the YARDLONG "
    "BEAN, a different species with no row and no recipe line. flageolets is another bean "
    "again, and its own bucket resolves to Wikidata 'Pochas' at seven names, which is too "
    "thin to build on. RECORDED AS UNSURE rather than extracted. fine bean and green beans "
    "are the holder."),
 "meatball": ("nothing to extract, model-read 2026-08-25",
    "4 names, 4 concepts, all DISHES. Swedish meatballs, Tefteli, frikadeller and "
    "pârjoale are national meatball dishes, and frikadeller is already on frikandel."),
 "avocado": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. Persea is the genus, Persea americana the species, avocados the "
    "plural. Machilus and Persea gratissima are synonymy."),
 "carrot": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. Daucus is the genus, carrots the plural, and 'karas' is a "
    "Wikipedia label that is not a carrot."),
 "chili powder": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. ⚠️ 'chilli con carne' is a DISH. 'chili' is already on chili "
    "pepper. chilli powder is a spelling.\n"
    "  ⚠️ GOCHUGARU IS ON THIS ROW UNDER TEN SPELLINGS and is not flagged, because no "
    "source states one as a primary name. It is a distinct product and its concept "
    "already has TWO rows, 'Korean chili pepper' and 'Korean chili powder', so it is a "
    "rename plus a merge rather than an extraction."),
 "semolina": ("nothing to extract, model-read 2026-08-25",
    "3 names, 2 concepts. semolina flour and wheat semolina are the holder. ⚠️ 'Suji ka "
    "halwa' is a DISH made from it."),
 "strained yogurt": ("nothing to extract, model-read 2026-08-25",
    "3 names, 2 concepts. greek yogurt at 2 lines and eight spellings of it are the "
    "holder, and ⚠️ THAT IS A RENAME CANDIDATE since the canonical carries no line.\n"
    "  ⚠️ Labneh under nine spellings is on this row and is RECORDED AS UNSURE. It is "
    "either the same thing under an Arabic name or a thicker product strained further, "
    "and no source on the row separates them. suzma is Central Asian."),
 "walnut": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. Juglans the genus, Juglans regia the species, walnuts the plural."),
 "white wine": ("nothing to extract, model-read 2026-08-25",
    "3 names, 3 concepts. shirozake is a Japanese sweet sake, white vermouth is already on "
    "dry vermouth, white wines is the plural."),
 "clove": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts. cloves is the plural. ⚠️ 'Dianthus' is the CARNATION genus, on "
    "the spice row because the flower is also called a clove pink."),
 "five-spice powder": ("nothing to extract, model-read 2026-08-25",
    "2 names, 1 concept, and it is not a spice. ⚠️ Ngo hiang, Ngohiong, Kikiam, Loh bak "
    "and Lumpiang ngohiong are ONE concept and a Hokkien and Filipino DISH, a spring roll "
    "seasoned with this blend. Thirteen spellings of a dish on a spice row."),
 "Sichuan peppercorns": ("nothing to extract, model-read 2026-08-25",
    "2 names, 2 concepts. Sichuan pepper is the old canonical. ⚠️ 'Zanthoxylum piperitum' "
    "is a DIFFERENT SPECIES, the Japanese sansho, and already has its own row."),

 # ── the four big merged holders, read out of order at Andy's direction, 2026-08-25 ──
 "dumpling": ("8 rows extracted, model-read 2026-08-25",
    "187 English names, ⚠️ NINE en.wikipedia ARTICLES, THE MOST IN THE LIBRARY, and about "
    "fourteen concepts. EXTRACTED gnocchi, wonton, spätzle, knödel, halušky, mandu, "
    "maultasche and matzah ball. pierogi and knedle already had rows.\n"
    "  THE GROUPS. knödel is 18 spellings across German and the Slavic languages. wonton is "
    "7 transliterations. halušky is 6, mandu 7, gnocchi 12, spätzle 6, matzah ball 6 "
    "including knaidel and knaidelach.\n"
    "  ⚠️ FOUR SEEDS HAD A TRAP. gnocchi and maultasche both share their bucket with "
    "Q1854639, which IS the dumpling row. mandu shares its bucket with AGROVOC c_3190, "
    "GARCINIA, a fruit genus. knödel shares its bucket with Q5265534, which is the existing "
    "knedle row, and with a Brazilian steamed bread. All four excluded from the seeds.\n"
    "  306 names left the parent, which went from 444 variations to 141."),
 "Sausage": ("9 rows extracted, model-read 2026-08-25",
    "155 English names, SEVEN en.wikipedia articles and about twenty-one concepts. EXTRACTED "
    "hot dog, bratwurst, longaniza, luganega, mettwurst, sobrassada, andouille, lap cheong "
    "and sucuk. chorizo, salami, kielbasa and chipolata already had rows.\n"
    "  ⚠️ EVERY SEED SHARED ITS BUCKET WITH Q131419, WHICH IS THIS ROW, so every one excludes "
    "it. sucuk also shares with Q1477592, CHURCHKHELA, a Georgian walnut and grape-must "
    "sweet.\n"
    "  ⚠️ butifarra IS NOT EXTRACTED. Its concept already has a row called 'Botifarra', so it "
    "is a rename. Q5736147 in that bucket is a PERUVIAN SANDWICH, not the Catalan sausage.\n"
    "  NOT MEMBERS AND NOT ROWS: salume, salumi and 'Italian charcuterie' are charcuterie "
    "rather than a sausage. 'sausage roll' is a pastry. Vegan and vegetarian sausage are a "
    "real product class and nobody has read them.\n"
    "  365 names left the parent, which went from 655 variations to 293."),
 "Crêpe": ("2 rows extracted, model-read 2026-08-25",
    "124 English names, four articles, about six concepts. ⚠️ A CRÊPE IS THIN AND UNLEAVENED "
    "AND A PANCAKE IS THICK AND LEAVENED, and this row was both. EXTRACTED pancake, which was "
    "the biggest group at about fifty-five names and was not the canonical, and "
    "palatschinke.\n"
    "  naleśniki, pannenkoek and Boûkète are national names left on the parent. ⚠️ 'Pancake "
    "race', 'Pancake Mix' and 'Pancake restaurant chain' are on it and are not foods.\n"
    "  191 names left the parent, which went from 322 variations to 132."),
 "biscuit": ("renamed to cookie, model-read 2026-08-25",
    "46 English names, two articles, three concepts: cookie, biscuit and cracker.\n"
    "  ⚠️ RENAMED Q13270 TO cookie UNDER THE AMERICAN READING. That row is the British "
    "biscuit, which is the American cookie, and cookie had no row at all.\n"
    "  ⚠️ AND I AUTHORED A biscuit ROW FOR THE AMERICAN QUICK BREAD AND HAD TO REVERT IT THE "
    "SAME DAY. Wikidata Q4917272 ALREADY IS that row, carrying American biscuit, Biscuit "
    "(bread), Biscuit (North America), Buttermilk biscuit, Baking powder biscuit and Cat head "
    "biscuit. THE TAMARI LESSON, AND I WALKED STRAIGHT INTO IT: the concept check printed "
    "'biscuit' as a holder and I read that as the row being renamed, when 'biscuit' was TWO "
    "rows. Checking a name is not checking a concept when the name is duplicated.\n"
    "  ⚠️ cracker is kept OUT of both. Saltines are a third thing and they are not cookies. It "
    "has no row and Q856330 exists for it when someone wants one.\n"
    "  ⚠️ The cookie row still holds 'biscuit', which is another row's canonical, and no "
    "resolution rule reaches the pair. That is the 668-pair class."),
 "hot dog": ("EXTRACTED 2026-08-25, and 12 names removed from it",
    "⚠️ TWELVE OF ITS NAMES WERE ARTICLE TITLES ABOUT AN ARGUMENT, NOT NAMES FOR A FOOD. 'Are "
    "hotdogs sandwiches?', 'Hot dog is a sandwich', 'Hot dogs are not sandwiches', 'Is a hot "
    "dog a sandwich?', 'Hot dog sandwich debate', 'The great hot dog debate', 'Ketchup on Hot "
    "Dogs' and five more. en.wikipedia redirects them at the Hot dog article and the join "
    "copied them in, so the library offered to answer a recipe line reading 'Are hotdogs "
    "sandwiches?'.\n"
    "  ⚠️ NOTHING IN THE STORE WOULD EVER FLAG THEM. All twelve are wikipedia_redirect with "
    "no language and no other source. They are well formed English, not initialisms, not "
    "symbols, not dead languages and not translations. Every mechanical cut so far keys on a "
    "property these do not have. The clearest case yet of a redirect that is not a name, and "
    "they came out by hand."),
 "nationality forms and descriptors": ("read and DECLINED as a class, 2026-08-25",
    "⚠️ NOT MEMBERS AND THEY SHOULD NOT BECOME ROWS, recorded so nobody proposes them again. "
    "A nationality plus a head noun is a description, not a product: German sausage, French "
    "sausage, Japanese sausage, Russian, Ukrainian, Norwegian, Thai, Turkish, Chilean, "
    "Colombian, Mexican, Finnish and African sausage. Brazilian, Chilean, French, Indian, "
    "Italian, Japanese, Korean, Norwegian and Puerto Rican dumplings. American, Australian, "
    "Austrian, Dutch, English, Greek, Icelandic, Indian, Indonesian, Mexican, Polish, "
    "Scandinavian, Scottish and Swedish pancakes.\n"
    "  The same for a cut or an ingredient plus a head noun: Pork sausage, Beef sausage, Fish "
    "sausage, Fresh sausage, Boiled sausage, Bulk sausage, Cocktail sausage, Link sausage, "
    "Potato dumpling, Bread dumpling, Plum dumplings, Banana pancakes, Blueberry pancakes, "
    "Chocolate chip pancakes, Buttermilk pancake.\n"
    "  ⚠️ THE TEST IS WHETHER A SHOP SELLS IT UNDER THAT NAME. Bratwurst passes and 'German "
    "sausage' does not, even though a source states both."),
}


def _flatten():
    out = {}
    for term, (verdict, why) in HEAD_TERMS.items():
        out[term.casefold()] = f"{verdict}. {why}"
    for holder, (verdict, why) in EXTRACTION_READ.items():
        out[holder.casefold()] = f"read for members: {verdict}. {why.splitlines()[0]}"
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
        "categories read for members": len(EXTRACTION_READ),
    }


if __name__ == "__main__":
    total = counts()
    for k, v in total.items():
        print(f"  {v:4d}  {k}")
    print(f"  {sum(total.values()):4d}  TOTAL, and none of it can be regenerated")
