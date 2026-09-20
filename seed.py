# seed.py
# This       is your content — the part you edit. build_db.py turns it into recipes.db.
#
# ⚠️ INGREDIENTS IS EMPTY. The 36 field-guide blurbs that used to sit here were an early demo,
# deleted in migration 046. The dict stays so a future seeded ingredient needs no code change.
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

INGREDIENTS = {
    # The 36 hand-authored ingredients were an early DEMO of what an ingredient library would look
    # like, written before one existed. The library that shipped is 10,013 catalog rows drawn from
    # Wikidata, Open Food Facts, AGROVOC and Wiktionary, and the 36 carried model-written prose that
    # was never rewritten. They were deleted in migration 046, in lockstep with emptying this dict.
    #
    # Left EMPTY rather than ripped out, exactly as RECIPES below is. build_db's seed_content still
    # upserts from here, so a future seeded ingredient would work with no code change. The name has
    # to stay defined either way, since tests/test_seed_decoupling.py reads seed.INGREDIENTS.
    #
    # ⚠️ THE KING ARTHUR WEIGHTS ARE A DIFFERENT THING AND THEY STAY. Those 129 rows are real
    #    reference data, loaded by seed_weights from king-arthur-staples-v2.csv, and none of this
    #    touches them.
    #
    # month numbers, for whenever this fills again: 1=Jan ... 12=Dec (empty list = year-round).
}

RECIPES = [
    # The 5 original example recipes were converted to editable app recipes and removed here
    # (migration 016) — the DB is now their source of truth. Left EMPTY, not ripped out: build_db's
    # seed_content machinery stays intact so future example recipes can be seeded from here.
]
