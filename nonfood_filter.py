#!/usr/bin/env python3
"""nonfood_filter.py - is this record making a non-food product?

⚠️ THE TARGET IS THE PRODUCT, NOT THE INGREDIENT. RecipeNLG carries lotions, soaps, salves,
play dough, bubble mix and wall cleaner alongside food. Banning an ingredient does not work,
because almost every marker has a real food use, measured across the whole corpus:

    paraffin          1,534 recipes, and they are Buckeye Candy and Martha Washington Candy.
                      Paraffin coats the chocolate. Food.
    lye               'Hominy'. Nixtamalization. Food.
    argan oil         'Moroccan-Style Chopped Salad', 'Amlou'. Moroccan food.
    sweet almond oil  'Salted Almonds'. Food.
    castor oil        "Ruby Bedwell's Castor Oil Cookies". Food.
    shea butter       eaten in West African cooking.
    coconut oil, honey, oatmeal, olive oil, cocoa butter, baking soda
                      all dual-use, and olive oil alone is in 227,383 recipes.

⚠️ SO THE RULE DEFAULTS TO KEEP. A single marker never excludes anything. Exclusion needs either
a cluster of markers that have no food story together, or a title that names a non-food product
backed by at least one marker. what-the-library-is-for.md: over-cutting real food is the failure
to avoid, and a lotion slipping into the pairings is a much smaller harm than a candy recipe
being thrown away.
"""
import re

# markers with no ordinary food use of their own. paraffin, lye, argan oil, sweet almond oil,
# castor oil and mineral oil are DELIBERATELY ABSENT, each for a measured reason above.
MARKERS = {"beeswax", "emu oil", "jojoba oil", "shea butter", "lanolin", "stearic acid",
           "sodium hydroxide", "borax", "witch hazel", "rosehip oil", "apricot kernel oil",
           "vitamin e oil", "glycerine", "carnauba wax", "grapeseed oil"}

# a title that names the PRODUCT being made. `balm` is absent on purpose: lemon balm is a herb
# and it took 'Lemon Balm Punch' and 'Dill And Lemon Balm Muffins' with it.
TITLE = re.compile(
    r"\b(lotion|soap|lip balm|body butter|body cream|hand cream|salve|deodorant|shampoo|"
    r"conditioner|bath bomb|moisturi[sz]er|body wash|face mask|cuticle|ointment|perfume|"
    r"toothpaste|laundry|play ?dough|silly putty|bubble|wall cleaner|scrub|"
    # a second pass added these after reading the beeswax records the first rule kept:
    # furniture polish, petroleum jelly, candles, a fire-starter, sunblock, a bug bar.
    # `jelly` and `glaze` alone stay OUT, since both name food.
    r"furniture polish|wood polish|leather polish|petroleum jelly|candle|fire.?starter|"
    r"sunblock|sunscreen|insect repellent|bug.be.gone|foot balm|skin smoother)\b", re.I)

# a title that is food even though a product word appears in it
FOOD_TITLE = re.compile(r"\b(punch|muffin|cookie|cake|bread|salad|soup|stew|pie|candy|"
                        r"potato|chicken|beef|pork|fish|rice|pasta)\b", re.I)


def classify(title, names):
    """Return (verdict, reason). verdict is 'nonfood' or 'keep'."""
    t = title or ""
    found = {n.lower() for n in names} & MARKERS
    title_hit = bool(TITLE.search(t)) and not FOOD_TITLE.search(t)
    if len(found) >= 2:
        return "nonfood", f"{len(found)} markers with no food story together: {sorted(found)}"
    if title_hit and found:
        return "nonfood", f"title names a product and it carries {sorted(found)}"
    if title_hit and not names:
        return "nonfood", "title names a product and nothing edible was matched"
    return "keep", ""
