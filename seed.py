# seed.py
# This       is your content — the part you edit. build_db.py turns it into recipes.db.
#
# The field-guide blurbs below are starter text written from general knowledge;
# treat seasons/regions as a first draft to tweak to your taste and region.
#
# Ingredient line shapes (used in each recipe's "ingredients" list):
#   {"heading": "Marinade"}                              -> a sub-heading
#   {"qty": "2 tbsp", "text": "olive oil"}               -> plain, non-clickable
#   {"qty": "4 cloves", "item": "garlic",
#    "label": "garlic", "note": ", crushed"}             -> clickable (item = a key below)
#
#   Units in "qty": write liquids measured in ounces as "fl oz" (e.g. "4 fl oz"), NOT
#   bare "oz". The grams converter treats "fl oz" as volume (-> mL -> grams via density)
#   but bare "oz" as weight (28.35 g/oz), so a bare "oz" on a liquid would convert wrongly.
#
# Step shapes (used in each recipe's "steps" list):
#   "Plain sentence with a [[garlic]] link or [[red_onion|red onions]] link."
#   {"heading": "Grill the chicken"}                     -> a sub-heading

# The people who can keep their own version of a recipe. Each gets a display colour
# (any CSS colour value). The original cookbook recipe always shows in the default
# ink; a person's edits and additions show in their colour. Add or rename people here
# and rerun build_db.py — their saved changes are keyed by id, so keep ids stable.
PEOPLE = [
    {"id": "andy",   "name": "Andy",   "color": "#A32D2D"},   # red
    {"id": "vedant", "name": "Vedant", "color": "#534AB7"},   # purple
]

# month numbers: 1=Jan ... 12=Dec   (empty list = treat as a year-round staple)
INGREDIENTS = {
    # ---- fresh produce & aromatics ----
    "lemon": {
        "name": "Lemon",
        "descr": "A winter citrus at its juiciest in the colder months. Meyer lemons are sweeter and floral; Eureka and Lisbon are the tart workhorses.",
        "season": [12, 1, 2, 3, 4],
        "regions": ["California", "Sicily", "Spain", "Argentina"],
        "pairs": "Garlic, olive oil, herbs, chicken, and almost any vegetable.",
    },
    "lime": {
        "name": "Lime",
        "descr": "A tropical citrus, more aromatic and less sour than lemon. Persian limes are the common seedless kind; small key limes are sharper.",
        "season": [5, 6, 7, 8, 9],
        "regions": ["Mexico", "Brazil", "India", "Florida"],
        "pairs": "Fish sauce, chili, cilantro, coconut, and tamarind.",
    },
    "garlic": {
        "name": "Garlic",
        "descr": "A pungent allium bulb, mellowing and sweetening as it cooks. Hardneck types are more intense; softneck store longer.",
        "season": [7, 8, 9],
        "regions": ["California", "China", "Spain", "Argentina"],
        "pairs": "Almost everything savory — onion, ginger, chili, lemon, and olive oil.",
    },
    "ginger": {
        "name": "Ginger",
        "descr": "A knobbly rhizome with bright heat. Young ginger is mild and thin-skinned; mature ginger is fibrous and sharper.",
        "season": [],
        "regions": ["India", "China", "Nigeria", "Indonesia"],
        "pairs": "Garlic, soy, lime, scallions, and chili.",
    },
    "red_onion": {
        "name": "Red Onion",
        "descr": "A milder, sweeter onion that holds its color. Good raw in sliced half-moons; turns jammy and soft when slow-roasted.",
        "season": [7, 8, 9],
        "regions": ["United States", "India", "Egypt", "Netherlands"],
        "pairs": "Sumac, lemon, parsley, and roast meats.",
    },
    "onion": {
        "name": "Onion",
        "descr": "The yellow workhorse allium — sharp raw, deeply savory and sweet once cooked down. Stores for months.",
        "season": [7, 8, 9],
        "regions": ["United States", "India", "China", "Netherlands"],
        "pairs": "Garlic, ginger, cumin, and just about any braise or sauce.",
    },
    "cauliflower": {
        "name": "Cauliflower",
        "descr": "A cool-season brassica. Best when the florets are tight and creamy white; takes well to high-heat roasting until browned.",
        "season": [9, 10, 11, 12, 1, 2, 3],
        "regions": ["India", "China", "California", "Spain"],
        "pairs": "Cumin, turmeric, potato, lemon, and tahini.",
    },
    "potato": {
        "name": "Potato",
        "descr": "Starchy russets are the roasting and frying choice — fluffy inside, crisp at the edges. Harvested late summer to fall, stored year-round.",
        "season": [8, 9, 10],
        "regions": ["Idaho", "Washington", "Northern Europe", "China"],
        "pairs": "Cauliflower, cumin, cilantro, and plenty of salt.",
    },
    "cilantro": {
        "name": "Cilantro",
        "descr": "The leaf of the coriander plant — citrusy and fresh. The stems carry the most flavor, so chop and use them too.",
        "season": [3, 4, 5, 9, 10],
        "regions": ["Grown worldwide as a cool-season herb"],
        "pairs": "Lime, chili, cumin, and ginger.",
    },
    "parsley": {
        "name": "Parsley",
        "descr": "A hardy herb, fresh and grassy. Flat-leaf (Italian) has more flavor than curly and is easier to chop finely.",
        "season": [4, 5, 6, 7, 8, 9, 10],
        "regions": ["Grown worldwide"],
        "pairs": "Lemon, garlic, sumac, and olive oil.",
    },
    "lemongrass": {
        "name": "Lemongrass",
        "descr": "A fibrous tropical stalk with a clean lemon-floral perfume. Only the tender pale bottom is used; bruise or pound it to release the oils.",
        "season": [],
        "regions": ["Thailand", "Vietnam", "Sri Lanka", "India"],
        "pairs": "Garlic, fish sauce, lime, coconut, and chili.",
    },
    "shallot": {
        "name": "Shallot",
        "descr": "A small, fine-grained allium — gentler and sweeter than onion, with a hint of garlic. Good raw in dressings and dipping sauces.",
        "season": [7, 8, 9],
        "regions": ["France", "Southeast Asia", "United States"],
        "pairs": "Fish sauce, lime, herbs, and vinegar.",
    },
    "green_onion": {
        "name": "Green Onion",
        "descr": "Also called scallions — mild allium with crisp white bottoms and grassy green tops. Often stirred in at the very end for freshness.",
        "season": [],
        "regions": ["Grown worldwide year-round"],
        "pairs": "Soy, sesame, ginger, and chili.",
    },
    "spinach": {
        "name": "Spinach",
        "descr": "A tender cool-season green that wilts to almost nothing in seconds of heat. Baby leaves need no trimming.",
        "season": [3, 4, 5, 9, 10, 11],
        "regions": ["China", "United States", "Europe"],
        "pairs": "Garlic, sesame, soy, and lemon.",
    },
    "carrot": {
        "name": "Carrot",
        "descr": "A sweet root vegetable, crunchy raw and good julienned into bowls. Stores for weeks and is available all year.",
        "season": [6, 7, 8, 9, 10],
        "regions": ["China", "Uzbekistan", "United States", "Europe"],
        "pairs": "Ginger, sesame, lime, and fresh herbs.",
    },
    "avocado": {
        "name": "Avocado",
        "descr": "A buttery, oil-rich fruit eaten as a vegetable. Ripe when it yields to gentle pressure; browns quickly once cut, so dress with citrus.",
        "season": [4, 5, 6, 7, 8, 9],
        "regions": ["Mexico", "California", "Peru"],
        "pairs": "Lime, chili, sesame, and leafy greens.",
    },
    "asian_pear": {
        "name": "Asian Pear",
        "descr": "A crisp, round, apple-textured pear. Grated into marinades it adds sweetness and a natural enzyme that helps tenderize meat.",
        "season": [8, 9, 10, 11],
        "regions": ["China", "Korea", "Japan", "California"],
        "pairs": "Soy, sesame, ginger, and beef.",
    },
    "pine_nut": {
        "name": "Pine Nut",
        "descr": "The soft, resinous seed of certain pine cones — laborious to harvest, which is why they're pricey. Toast briefly; they burn fast.",
        "season": [],
        "regions": ["Mediterranean", "China", "Korea"],
        "pairs": "Sumac, parsley, olive oil, and roast meats.",
    },
    # ---- spices & pantry (year-round; season left empty) ----
    "sumac": {
        "name": "Sumac",
        "descr": "Dried, ground berries of the sumac shrub — tangy and lemony with a deep red color. A finishing spice as much as a cooking one.",
        "season": [],
        "regions": ["Levant", "Turkey", "Iran"],
        "pairs": "Red onion, lemon, parsley, chicken, and flatbread.",
    },
    "cumin": {
        "name": "Cumin",
        "descr": "A warm, earthy seed used whole or ground. Toasting whole seeds before grinding deepens the flavor noticeably.",
        "season": [],
        "regions": ["India", "Iran", "the Mediterranean"],
        "pairs": "Cauliflower, potato, turmeric, and chili.",
    },
    "allspice": {
        "name": "Allspice",
        "descr": "A single dried berry that tastes like a blend of cinnamon, clove, and nutmeg — hence the name.",
        "season": [],
        "regions": ["Jamaica", "Central America"],
        "pairs": "Cinnamon, cumin, and slow-cooked meats.",
    },
    "cinnamon": {
        "name": "Cinnamon",
        "descr": "The dried inner bark of a tropical tree. Delicate Ceylon ('true' cinnamon) is milder; cassia is the bolder, common supermarket type.",
        "season": [],
        "regions": ["Sri Lanka", "Indonesia", "Vietnam"],
        "pairs": "Allspice, cumin, and both sweet and savory dishes.",
    },
    "turmeric": {
        "name": "Turmeric",
        "descr": "A golden rhizome, almost always sold dried and ground. Earthy and slightly bitter; it stains everything, including you.",
        "season": [],
        "regions": ["India"],
        "pairs": "Cumin, ginger, cauliflower, and onion.",
    },
    "asafetida": {
        "name": "Asafetida (Hing)",
        "descr": "A dried plant resin, sharp and pungent raw but mellowing into a savory, onion-garlic note when cooked in hot oil. A little goes a long way.",
        "season": [],
        "regions": ["Iran", "Afghanistan", "India"],
        "pairs": "Cumin, turmeric, lentils, and vegetables.",
    },
    "chile_powder": {
        "name": "Red Chile Powder",
        "descr": "Ground dried red chilies — heat plus color. Strength varies wildly by type, so add to taste.",
        "season": [],
        "regions": ["India", "Mexico"],
        "pairs": "Cumin, turmeric, lime, and garlic.",
    },
    "white_pepper": {
        "name": "White Peppercorns",
        "descr": "The ripe peppercorn with its dark skin removed — earthier and less sharp than black pepper, common in Thai and Chinese cooking.",
        "season": [],
        "regions": ["India", "Indonesia", "Vietnam"],
        "pairs": "Coriander seed, garlic, and white sauces.",
    },
    "coriander_seed": {
        "name": "Coriander Seed",
        "descr": "The dried seed of the cilantro plant, warm and citrusy — quite different from the fresh leaf. Toast before grinding.",
        "season": [],
        "regions": ["India", "Eastern Europe", "Morocco"],
        "pairs": "White pepper, cumin, lemongrass, and garlic.",
    },
    "soy_sauce": {
        "name": "Soy Sauce",
        "descr": "A fermented soybean-and-wheat sauce — salty and savory (umami). Light is saltier and thinner; dark is thicker, sweeter, and more for color.",
        "season": [],
        "regions": ["China", "Japan", "Korea"],
        "pairs": "Sesame, ginger, garlic, and sugar.",
    },
    "fish_sauce": {
        "name": "Fish Sauce",
        "descr": "Salted, fermented fish pressed into a clear, savory liquid — the backbone of Southeast Asian seasoning. Smells strong, tastes deep.",
        "season": [],
        "regions": ["Thailand", "Vietnam"],
        "pairs": "Lime, palm sugar, chili, and garlic.",
    },
    "tamarind": {
        "name": "Tamarind",
        "descr": "The sour pulp of a tropical pod, usually sold as paste or concentrate. Brings a fruity tartness to sauces and braises.",
        "season": [],
        "regions": ["India", "Thailand", "Mexico"],
        "pairs": "Palm sugar, fish sauce, lime, and chili.",
    },
    "palm_sugar": {
        "name": "Palm Sugar",
        "descr": "Sugar from the sap of palm trees — softer and more caramel-like than white sugar. Chop or shave it finely so it dissolves.",
        "season": [],
        "regions": ["Thailand", "Indonesia", "India"],
        "pairs": "Tamarind, fish sauce, lime, and chili.",
    },
    "sesame_oil": {
        "name": "Sesame Oil",
        "descr": "Toasted sesame oil is a finishing oil — nutty and aromatic, added near the end rather than used for frying.",
        "season": [],
        "regions": ["China", "Korea", "Japan"],
        "pairs": "Soy, ginger, scallion, and sesame seeds.",
    },
    "sesame_seed": {
        "name": "Sesame Seeds",
        "descr": "Tiny oil-rich seeds, nutty once toasted. White seeds are the common garnish; black are earthier.",
        "season": [],
        "regions": ["India", "Sudan", "Myanmar"],
        "pairs": "Sesame oil, soy, scallion, and rice.",
    },
    "mirin": {
        "name": "Mirin",
        "descr": "A sweet Japanese rice wine used for cooking — adds gloss and gentle sweetness to glazes and sauces.",
        "season": [],
        "regions": ["Japan"],
        "pairs": "Soy, sesame, and grilled meats.",
    },
    "yeast": {
        "name": "Yeast",
        "descr": "A living single-celled fungus that ferments the sugars in dough, producing the gas that makes bread rise. 'Instant' needs no proofing.",
        "season": [],
        "regions": ["Cultivated, not grown seasonally"],
        "pairs": "Flour, water, salt, and time.",
    },
    "bread_flour": {
        "name": "Bread Flour",
        "descr": "A high-protein wheat flour. The extra protein builds more gluten, giving bread its chew and structure.",
        "season": [],
        "regions": ["Milled from hard wheat (North America, Europe)"],
        "pairs": "Yeast, water, and salt.",
    },
}

RECIPES = [
    # The 5 original example recipes were converted to editable app recipes and removed here
    # (migration 016) — the DB is now their source of truth. Left EMPTY, not ripped out: build_db's
    # seed_content machinery stays intact so future example recipes can be seeded from here.
]
