"""Phase 15 — import cleanup core (import_cleanup).

Tests the PARSE-vs-FLAG boundaries, because a wrong STRUCTURE silently corrupts imported
recipes: the failure mode must be "flagged a line," never "structured it wrong." Heaviest
emphasis on the decline points — the grams confidence guard, section ambiguity, the risky
multiplier/each patterns, and the servings traps."""
import json
import pathlib

import pytest

import import_cleanup as ic


def _norm(**over):
    """A normalized recipe (the reader's shape) for clean_recipe tests; override any field."""
    base = dict(
        name="X", uid="u", hash="h", ingredient_lines=[], directions=[],
        servings_raw="", categories=[], source="", source_url="", notes="",
        description="", rating=0, prep_time="", cook_time="", total_time="",
        images=[], primary_photo=None,
    )
    base.update(over)
    return base


# ----------------------------------------------------------------- amount parse
def test_amount_simple():
    d = ic.classify_line("2 tbsp extra virgin olive oil")
    assert (d["value"], d["unit"], d["name"]) == (2.0, "tbsp", "extra virgin olive oil")
    assert d["kind"] == "ingredient"


def test_amount_unicode_and_mixed():
    assert ic.classify_line("½ cup cold water")["value"] == 0.5
    d = ic.classify_line("3 ¼ cups all-purpose flour")
    assert d["value"] == 3.25 and d["unit"] == "cups" and d["name"] == "all-purpose flour"


def test_amount_decimal():
    d = ic.classify_line("0.25 tsp salt")
    assert d["value"] == 0.25 and d["unit"] == "tsp"


def test_empty_amount_keeps_whole_name():
    d = ic.classify_line("Sea Salt")
    assert d["amount"] == "" and d["unit"] == "" and d["name"] == "Sea Salt"


# ⚠️ REVERSES "Confirmation 3", which lived only as the comment on this test: "counts (cloves) are
#    NOT measure units — they stay in the name". Nothing else in the repo recorded that decision and
#    the code had already gone the other way where it could — split_qty's docstring documents
#    `"4 cloves" -> ("4", "cloves")` and 39 live rows already store unit='cloves', written through
#    the Paprika qty field. What stayed broken was the COMBINED line the URL importer reads, where
#    "1 clove garlic" stored an ingredient called "clove garlic". Measured over every live line plus
#    the fixture imports: 99 lines improve, 0 regress.
def test_a_count_noun_beside_an_ingredient_becomes_the_unit():
    d = ic.classify_line("3 Garlic Cloves, peeled")
    assert d["value"] == 3.0 and d["unit"] == "Cloves" and d["name"] == "Garlic, peeled"


def test_the_count_noun_is_lifted_in_either_word_order():
    lead = ic.classify_line("1 clove garlic (minced)")
    assert (lead["value"], lead["unit"], lead["name"]) == (1.0, "clove", "garlic (minced)")
    trail = ic.classify_line("2 garlic cloves, minced")
    assert (trail["value"], trail["unit"], trail["name"]) == (2.0, "cloves", "garlic, minced")


@pytest.mark.parametrize("line,name", [
    ("10 cloves (or 1/4 tsp ground cloves)", "cloves (or 1/4 tsp ground cloves)"),
    ("5 whole cloves", "whole cloves"),          # 'whole' names nothing, so the clove IS the food
    ("3 cloves, whole", "cloves, whole"),        # same, with the modifier behind a comma
    ("2 Cloves", "Cloves"),                      # nothing beside it at all
    ("3 cloves", "cloves"),
])
def test_a_clove_standing_alone_is_the_spice_and_keeps_the_name(line, name):
    """⚠️ THE GUARD THE OLD DECISION WAS RIGHT ABOUT. 'clove' is a unit of garlic and also a spice,
    so it only becomes a unit when a real ingredient word sits beside it."""
    d = ic.classify_line(line)
    assert d["unit"] == "" and d["name"] == name


# --------------------------------------------------------------------------- #
# A size word is part of the MEASUREMENT
# --------------------------------------------------------------------------- #
# ⚠️ ANDY'S CALL, AND IT REVERSES WHAT previews/parser-library-scoping.md PROPOSED. That report read
#    the 180 live rows storing unit='large' / 'small bunch' / 'large cloves' as a defect to undo. They
#    are deliberate. "1 large egg" is one egg of a stated size, so the size is what the count counts
#    and it belongs beside the number. This suite pins the parser to the stored rows, not the reverse.
#    Measured over all 3,349 live lines: 204 change, 120 improve, 84 neutral, 0 worse.
@pytest.mark.parametrize("line,qty_unit,name", [
    ("1 large egg", "large", "egg"),
    ("4 medium Roma tomatoes, seeded", "medium", "Roma tomatoes, seeded"),
    ("1 small red onion (finely chopped)", "small", "red onion (finely chopped)"),
])
def test_a_size_word_with_no_counting_noun_is_the_whole_unit(line, qty_unit, name):
    d = ic.classify_line(line)
    assert d["unit"] == qty_unit and d["name"] == name


@pytest.mark.parametrize("line,unit,name", [
    # The noun TRAILS the food, so the count is lifted first and the size joins it afterwards.
    ("1 medium garlic clove", "medium clove", "garlic"),
    ("5 medium garlic cloves, smashed", "medium cloves", "garlic, smashed"),
    ("1 large lemongrass stalk, white part only", "large stalk", "lemongrass, white part only"),
    # The noun LEADS, so _COUNT_UNIT_LEAD takes size and noun together in one match.
    ("1 large head of cauliflower, cut into steaks", "large head", "cauliflower, cut into steaks"),
    ("2 small bunches parsley", "small bunches", "parsley"),
])
def test_a_size_word_combines_with_a_counting_noun_in_either_word_order(line, unit, name):
    d = ic.classify_line(line)
    assert d["unit"] == unit and d["name"] == name


@pytest.mark.parametrize("line,unit,name", [
    ("2 handfuls baby spinach", "handfuls", "baby spinach"),
    ("4 large handfuls baby spinach", "large handfuls", "baby spinach"),
    ("1 package firm tofu, drained", "package", "firm tofu, drained"),
    ("2 packages frozen spinach", "packages", "frozen spinach"),
    ("1 tin chopped tomatoes", "tin", "chopped tomatoes"),
    ("2 tins coconut milk", "tins", "coconut milk"),
])
def test_the_counting_nouns_added_with_the_size_rule(line, unit, name):
    """handful and package each already held live rows in the unit column that no rule admitted.
    'tin' is the British spelling of 'can', which the rule has always taken."""
    d = ic.classify_line(line)
    assert d["unit"] == unit and d["name"] == name


@pytest.mark.parametrize("line,name", [
    ("2 lemons", "lemons"),              # a plain food noun is not a unit
    ("3 shallots, sliced", "shallots, sliced"),
    ("1 onion chopped", "onion chopped"),
])
def test_an_ordinary_trailing_word_never_becomes_the_unit(line, name):
    """⚠️ THE split_qty HARDENING, FROM THE OTHER SIDE. _COUNTNOUN_RE used to accept ANY letters-only
    word, which is a test of shape where the question is one of membership. Only the two closed sets
    reach the unit column now."""
    d = ic.classify_line(line)
    assert d["unit"] == "" and d["name"] == name
    assert ic.split_qty("2 lemons") == ("2 lemons", "")


def test_a_size_word_is_refused_when_nothing_but_modifiers_follows_it():
    """The same guard the counting noun has. 'large' with no food after it measures nothing."""
    d = ic.classify_line("1 large, chopped")
    assert d["unit"] == "" and d["name"] == "large, chopped"


def test_a_measure_already_present_is_never_prefixed_with_a_size_word():
    d = ic.classify_line("1 cup large diced onion")
    assert d["unit"] == "cup" and d["name"] == "large diced onion"


@pytest.mark.parametrize("line,unit,name", [
    ("small bunch of flatleaf parsley (finely chopped)", "small bunch",
     "flatleaf parsley (finely chopped)"),
    ("Pinch of salt", "Pinch", "salt"),
    ("garlic cloves, minced", "cloves", "garlic, minced"),
])
def test_an_amount_less_line_that_opens_with_a_measurement_reads_it(line, unit, name):
    """A missing COUNT is a different state from an unreadable line, and the flag exists for the
    second one. 46 live lines move out of the review queue this way."""
    d = ic.classify_line(line)
    assert d["kind"] == "ingredient" and d["unit"] == unit and d["name"] == name


def test_a_heading_that_carries_a_size_word_is_still_a_heading():
    """⚠️ WHY THE MEASUREMENT BLOCK RUNS AFTER THE SECTION BLOCKS. The colon settles it."""
    d = ic.classify_line("Large Bowl:")
    assert d["kind"] == "section" and d["unit"] == ""


@pytest.mark.parametrize("line,unit,name", [
    ("3 sprigs cilantro, chopped", "sprigs", "cilantro, chopped"),
    ("3 Thyme Sprigs", "Sprigs", "Thyme"),
    ("2 stalks celery, diced", "stalks", "celery, diced"),
    ("4 celery stalks", "stalks", "celery"),
    ("4 slices ginger", "slices", "ginger"),
    ("1 pinch cayenne pepper", "pinch", "cayenne pepper"),
    ("2 bunches flat-leaf parsley", "bunches", "flat-leaf parsley"),
    ("2 sticks unsalted butter", "sticks", "unsalted butter"),
    ("1 head garlic", "head", "garlic"),
    ("2 salmon fillets", "fillets", "salmon"),
    ("5 Ceylon or English breakfast tea bags", "bags", "Ceylon or English breakfast tea"),
    ("1 Can Whole Peeled Tomatoes", "Can", "Whole Peeled Tomatoes"),
    ("4 - 6 pieces of Parmesan rind (optional)", "pieces", "Parmesan rind (optional)"),
])
def test_the_other_counting_nouns_lift_the_same_way(line, unit, name):
    d = ic.classify_line(line)
    assert (d["unit"], d["name"]) == (unit, name)


def test_a_fennel_bulb_keeps_its_bulb():
    """⚠️ REVERSES "1 fennel bulb" -> bulb + "fennel", which this file asserted until now.

    The bulb is the vegetable. 'fennel' standing alone is as likely to mean the seed, which is a
    spice used a different way, and the library holds all three rows: 'Fennel', 'fennel bulb',
    'fennel seeds'. A line that says bulb has told you which one it means, so the word stays."""
    for line in ("1 fennel bulb, finely chopped", "2 fennel bulbs"):
        d = ic.classify_line(line)
        assert d["unit"] == "", f"{line!r} lifted {d['unit']!r}"
        assert "fennel bulb" in d["name"].lower(), f"{line!r} -> {d['name']!r}"
    # the SEED is untouched: it is not the compound, so its own unit still lifts
    assert ic.classify_line("1 tbsp fennel seeds")["unit"] == "tbsp"


def test_a_doubled_comma_is_collapsed_with_the_space_before_it():
    """⚠️ ONE ARTIFACT, NOT TWO. "butter, , melted" repaired only for the space reads
    "butter,, melted", which is worse than it started. The live row is vanilla-mug-cake[4]."""
    assert ic.clean_source_text("2 tablespoon butter, , melted (28 g)")[0] == \
        "2 tablespoon butter, melted (28 g)"
    assert ic.classify_line("2 tablespoon butter, , melted (28 g)")["name"] == "butter, melted"
    assert ic.clean_source_text("a, b")[1] == []          # nothing to do, no flag


def test_a_cinnamon_stick_keeps_its_stick():
    """⚠️ REVERSES "1 cinnamon stick" -> stick + "cinnamon", which this file asserted until now.

    The counting word is part of the FOOD here, not a measurement of it. A cinnamon stick is whole
    bark you fish out of the pot, and 'cinnamon' standing alone reads as the ground spice, which is
    a different ingredient used a different way. The shipped library agrees and holds them as two
    rows, 'cinnamon stick' (Q30038886) and 'cinnamon' (Q28165), so the lift also moved the line's
    catalog link onto the wrong food.

    All four live shapes are held, including the three whose names are already mangled, because the
    guard tests the text rather than a tidy name."""
    for line in ("1 cinnamon stick", "2 inch cinnamon stick", "1 Chinese cinnamon stick",
                 "One 2-inch piece cinnamon stick", "2 cinnamon sticks"):
        d = ic.classify_line(line)
        assert d["unit"] == "", f"{line!r} lifted {d['unit']!r}"
        assert "cinnamon stick" in d["name"].lower(), f"{line!r} -> {d['name']!r}"


def test_the_compound_guard_is_narrow_and_leaves_real_measurements_alone():
    """The guard names one phrase. Everything the scan read as a genuine measurement still lifts:
    a clove of garlic, a stalk of celery, a stick of BUTTER, a slice of ginger, a head of garlic."""
    for line, unit in (("5 garlic cloves", "cloves"), ("2 stalks celery", "stalks"),
                       ("2 sticks unsalted butter", "sticks"), ("4 slices ginger", "slices"),
                       ("1 head garlic", "head")):
        assert ic.classify_line(line)["unit"] == unit, line


def test_a_counting_noun_inside_a_parenthetical_is_an_aside_not_the_count():
    """⚠️ MEASURED, NOT PRECAUTIONARY. This is the one corpus line where the trailing rule grabbed a
    word out of a prep note, reading 'pieces' as the unit and leaving "cut into 2-inch long,". The
    ingredient is scallions and the count is 3. The mechanical all-improvement check passed it,
    because the name did shrink and does still name a food."""
    line = "3 scallions (cut into 2-inch long pieces, with the white and green parts separated)"
    d = ic.classify_line(line)
    assert d["unit"] == "" and d["name"].startswith("scallions (cut into 2-inch long pieces")


@pytest.mark.parametrize("line", [
    "4 whole sticks", "2 sticks", "1 large head", "3 slices", "2 pinches", "1 can", "2 bunches",
])
def test_a_counting_noun_with_nothing_beside_it_stays_the_ingredient(line):
    """⚠️ AND ROUND B'S STRANDED-UNIT RULE MAKES THE SAME REFUSAL FOR THE SAME REASON. 'sticks' is
    a unit word now, so without that guard "2 sticks" became qty "2 sticks" with no name at all."""
    assert ic.classify_line(line)["unit"] == ""


# ----------------------------------------------------------------- sections
def test_section_colon():
    assert ic.classify_line("SAUCE:")["kind"] == "section"


def test_section_all_caps():
    assert ic.classify_line("FOR THE PASTRY")["kind"] == "section"


def test_for_the_dough_promoted_section():
    # ends in "dough" (a section word, <=3 words) -> now a flagged section header (head-noun match)
    d = ic.classify_line("For the dough")
    assert d["kind"] == "section" and "section_suggested" in d["flags"]


def test_for_serving_still_ambiguous_suggest_section():
    # "serving" is NOT a section word -> stays ambiguous, but still suggests section (for/to path)
    d = ic.classify_line("For serving")
    assert d["kind"] == "flagged" and d["suggestion"] == "section"
    assert "ambiguous_section" in d["flags"]


def test_no_amount_flagged_suggest_ingredient():
    d = ic.classify_line("Extra-virgin olive oil")
    assert d["kind"] == "flagged" and d["suggestion"] == "ingredient"


def test_section_guard_amount_beats_colon_or_caps():
    # a line with a real amount is never a section, even with a colon or all-caps
    assert ic.classify_line("1 cup flour: sifted")["kind"] == "ingredient"
    assert ic.classify_line("2 EGGS")["kind"] == "ingredient"


# ----------------------------------------------------------------- emphasis strip (markdown headings)
def test_strip_emphasis_wrapping_pairs():
    assert ic.strip_emphasis("**Other Ingredients:**") == "Other Ingredients:"
    assert ic.strip_emphasis("**Day 1**") == "Day 1"
    assert ic.strip_emphasis("_Vanilla Cream Cheese Icing_") == "Vanilla Cream Cheese Icing"
    assert ic.strip_emphasis("__Bold Underscore:__") == "Bold Underscore:"


def test_strip_emphasis_leaves_non_wraps_untouched():
    assert ic.strip_emphasis("salt*") == "salt*"                       # trailing-only footnote, no pair
    assert ic.strip_emphasis("plain flour") == "plain flour"            # no markers
    assert ic.strip_emphasis("2 cups **sifted** flour") == "2 cups **sifted** flour"  # mid-line, no wrap


def test_bold_colon_heading_detected_and_stored_clean():
    # "**Other Ingredients:**" -> section via the stripped colon; the STORED text drops the markers
    d = ic.classify_line("**Other Ingredients:**")
    assert d["kind"] == "section" and d["name"] == "Other Ingredients:"


def test_bold_without_colon_or_signal_not_promoted():
    # a bold label with no colon/caps and matching no section_signal rule -> NOT a section
    assert ic.classify_line("**Some Label**")["kind"] != "section"


def test_trailing_footnote_stays_ingredient():
    # a footnote asterisk is not a wrapping pair -> is_section never sees a stripped colon/caps
    assert ic.classify_line("salt*")["kind"] != "section"


# ----------------------------------------------------------------- section_signal (4 extra rules)
def test_section_signal_rule1_ingredients_meta_word():
    assert ic.section_signal("Italian Beef Ingredients")
    assert ic.section_signal("Whole Wheat Ingredients")
    assert ic.section_signal("Dry Ingredient")               # singular, whole-word
    assert not ic.section_signal("flour")                    # a real ingredient word


def test_section_signal_rule2_unit_system_label():
    assert ic.section_signal("Metric")
    assert ic.section_signal("Imperial")
    assert ic.section_signal("US")                           # also caught by is_section caps — fine
    assert ic.section_signal("US Customary")
    assert not ic.section_signal("metallic")                 # not a unit-system word
    assert not ic.section_signal("use metric measurements")  # not an exact whole-line label


def test_section_signal_rule3_day_n():
    assert ic.section_signal("Day 1")
    assert ic.section_signal("Day 3+")
    assert ic.section_signal(ic.strip_emphasis("**Day 1**"))  # stripped by caller
    assert not ic.section_signal("Day of the Dead cake")     # "day" not followed by a digit
    assert not ic.section_signal("Sunday 2 things")          # must START with "day"


def test_section_signal_rule4_prep_allowlist():
    # the purely-prep core: is / ends-in one of {egg wash, dredge, sponge, brine}
    for w in ("Egg wash", "Flour Dredge", "sponge", "Brine", "Buttermilk Brine"):
        assert ic.section_signal(w), w
    # DROPPED from Rule 4 (overlap block 3b's section words) — NOT matched by the allowlist. They may
    # still be caught by is_section IF colon/caps, but the bare title-case forms below are not.
    for w in ("Glaze", "Marinade", "Streusel", "topping", "filling"):
        assert not ic.section_signal(w), w
    # NEGATIVES: excluded / untested / food-words that double as ingredients
    for w in ("cheddar", "meatballs", "salsa", "loaves", "batter", "sauce", "potatoes"):
        assert not ic.section_signal(w), w
    # no mid-word / substring match
    assert not ic.section_signal("dredgel")
    assert not ic.section_signal("gladredge")


def test_section_signal_falls_back_to_is_section():
    assert ic.section_signal("SAUCE:")                        # colon
    assert ic.section_signal("FOR THE PASTRY")                # ALL-CAPS
    assert not ic.section_signal("chopped onion")             # neither


def test_is_section_unchanged_by_new_rules():
    # is_section stays PURE colon/caps — the 4 new rules live only in section_signal
    assert ic.is_section("SAUCE:")
    assert ic.is_section("FOR THE PASTRY")
    assert not ic.is_section("Day 1")                         # section_signal True, but is_section False
    assert not ic.is_section("Egg wash")
    assert not ic.is_section("Italian Beef Ingredients")


def test_day_n_stage_label_promoted_and_stored_clean():
    # "**Day 1**" now promotes via Rule 3; stored clean (emphasis stripped)
    d = ic.classify_line("**Day 1**")
    assert d["kind"] == "section" and d["name"] == "Day 1"


def test_x_ingredients_promoted():
    d = ic.classify_line("Italian Beef Ingredients")
    assert d["kind"] == "section" and d["name"] == "Italian Beef Ingredients"


def test_amount_bearing_egg_wash_stays_ingredient():
    # the KEY safety case: an amount-bearing "egg wash"/"filling" line never reaches section_signal
    assert ic.classify_line("1 egg for egg wash")["kind"] == "ingredient"
    assert ic.classify_line("½ cup canned pumpkin (not pumpkin pie filling)")["kind"] == "ingredient"


def test_classify_step_unaffected_by_section_signal():
    # steps call is_section (NOT section_signal) -> a "Day 1" / "Egg wash" step is NOT a heading
    assert ic.classify_step("Day 1")[0] is False
    assert ic.classify_step("Egg wash")[0] is False
    assert ic.classify_step("FOR THE SAUCE:")[0] is True     # colon/caps still works for steps


# ----------------------------------------------------------------- grams harvest + guard
def test_grams_harvest_simple():
    assert ic.classify_line("2 sticks (226 grams) unsalted butter")["grams_harvested"] == 226.0


def test_grams_harvest_about_prefix():
    assert ic.classify_line("1 pint (about 320 grams) blueberries")["grams_harvested"] == 320.0


def test_grams_dangling_paren_no_crash_no_harvest():
    d = ic.classify_line("3 tbsp Thai tea mix (")
    assert d["grams_harvested"] is None
    assert "grams_declined" not in d["flags"]            # no gram value was present at all


def test_grams_messy_nested_declines_not_harvest_15():
    # the 15g belongs to a sub-measure ("1/2 cup (15g) once soaked"), NOT the 2/3 cup primary
    line = '2/3 cup dried Chinese chillies (not Thai!) (24 x 6cm/2.5" long, 1/2 cup (15g) once soaked)'
    d = ic.classify_line(line)
    assert d["grams_harvested"] is None                  # guard refuses the mis-harvest
    assert "grams_declined" in d["flags"]                # but flags that a gram value was seen


def test_harvested_gram_paren_stripped_from_name():
    # harvest reads the weight AND removes the "(250g)" from the name; raw_text keeps the original
    d = ic.classify_line("14 cups (250g) dried chickpeas")
    assert d["grams_harvested"] == 250.0
    assert d["name"] == "dried chickpeas"
    assert d["raw"] == "14 cups (250g) dried chickpeas"


def test_harvested_gram_paren_strip_keeps_contentful_paren():
    # only the harvested "(270g)" goes; the contentful "(light roast)" stays
    # ⚠️ AND THE "plus 2 tablespoons" GOES INTO THE AMOUNT SINCE ROUND B. It is the second half of
    #    one compound amount, and leaving it at the front of the name read as a name that had lost
    #    its front. Both halves scale.
    d = ic.classify_line("1 cup plus 2 tablespoons (270g) tahini (light roast)")
    assert d["grams_harvested"] == 270.0
    assert d["amount"] == "1 cup + 2 tablespoons"
    assert d["name"] == "tahini (light roast)"


# ----------------------------------------------------------------- dual-unit secondary measure
# ⚠️ secondary_measure MEANS THE AUTHOR'S SECOND AMOUNT SINCE ROUND B, AND IT USED TO MEAN "the
#    volume". Andy's decision 3a: the slot holds what the author wrote as the backup, as written,
#    with the first amount staying in qty. "1 cup (250 g) flour" therefore stores "250 g" where it
#    used to store "1 cup", which was a copy of the amount the row already had. The stray leading
#    slash goes too: 130 live rows held a copy of their own first amount and 163 more a "/10g".
def test_dual_unit_secondary_measure_stripped_from_name():
    # "2 teaspoons / 6 g active dry yeast": keep the primary qty, drop the "/ 6 g" from the label
    d = ic.classify_line("2 teaspoons / 6 g active dry yeast")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"]) == ("2", "teaspoons")
    assert d["name"] == "active dry yeast"               # label is now the clean ingredient name
    assert d["secondary_measure"] == "6 g"
    assert d["raw"] == "2 teaspoons / 6 g active dry yeast"   # raw_text kept intact


def test_dual_unit_metric_weight_stripped_keeps_alternative():
    d = ic.classify_line("3 ½ cups / 440 g bread flour or high gluten flour")
    assert d["name"] == "bread flour or high gluten flour"
    assert d["secondary_measure"] == "440 g"
    assert d["has_alternative"] is True                  # "or" still detected on the clean name


def test_dual_unit_only_leading_secondary_stripped():
    # a "/60 ml" later in a note must NOT be touched — only the leading secondary measure goes
    d = ic.classify_line("1 ¼ cups / 300 ml warm water (you may need ± ¼ cup /60 ml more)")
    assert d["name"].startswith("warm water")
    assert "/60 ml" in d["name"]
    assert d["secondary_measure"] == "300 ml"


def test_no_secondary_measure_for_single_unit_line():
    d = ic.classify_line("2 tbsp olive oil")
    assert d["secondary_measure"] is None and d["name"] == "olive oil"


# ----------------------------------------------------------------- dangling orphan paren
def test_dangling_open_paren_stripped_from_name():
    # the source line is unbalanced ("3 tbsp Thai tea mix (") — strip the lone trailing "("
    d = ic.classify_line("3 tbsp Thai tea mix (")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"]) == ("3", "tbsp")
    assert d["name"] == "Thai tea mix"                    # orphan "(" gone
    assert d["raw"] == "3 tbsp Thai tea mix ("            # raw_text keeps the original


def test_contentful_paren_not_stripped():
    d = ic.classify_line("2 tbsp soy sauce (low sodium)")
    assert d["name"] == "soy sauce (low sodium)"          # balanced paren is left intact


# ----------------------------------------------------------------- dual measure (volume + weight)
def test_weight_first_volume_paren_captured():
    # weight-first: gram is the leading amount; the "(1 cup)" volume paren is stripped + captured
    d = ic.classify_line("100 g (1 cup) granulated sugar")
    assert d["name"] == "granulated sugar"
    assert d["grams_harvested"] == 100.0                  # captured from the leading amount
    assert d["secondary_measure"] == "1 cup"
    assert d["raw"] == "100 g (1 cup) granulated sugar"   # raw_text untouched


def test_volume_first_gram_paren_captures_both():
    # volume-first: the gram is harvested from the paren AND is the author's second amount. It used
    # to store "1 cup", which is the amount the row already carries in qty.
    d = ic.classify_line("1 cup (250g) flour")
    assert d["name"] == "flour"
    assert d["grams_harvested"] == 250.0
    assert d["secondary_measure"] == "250g"


def test_dual_measure_leaves_contentful_paren():
    d = ic.classify_line("2 tbsp tahini (light roast)")
    assert d["name"] == "tahini (light roast)"            # not a volume measure -> not stripped
    assert d["secondary_measure"] is None


# ----------------------------------------------------------------- step headers (trailing dash)
def test_step_trailing_dash_is_heading_stripped():
    is_h, text = ic.classify_step("prepare your pan -")
    assert is_h is True and text == "prepare your pan"     # dash stripped


def test_step_colon_still_heading():
    is_h, text = ic.classify_step("Brown the butter:")
    assert is_h is True and text == "Brown the butter:"


def test_step_normal_not_heading():
    is_h, text = ic.classify_step("Preheat the oven to 350°F and grease the pan.")
    assert is_h is False and text == "Preheat the oven to 350°F and grease the pan."


# ----------------------------------------------------------------- ingredient section-headers
def test_section_word_promoted_and_flagged():
    for w in ("crust", "filling"):
        d = ic.classify_line(w)
        assert d["kind"] == "section", w
        assert "section_suggested" in d["flags"], w


def test_salt_not_promoted_stays_ambiguous():
    d = ic.classify_line("salt")
    assert d["kind"] == "flagged"
    assert "ambiguous_section" in d["flags"] and "section_suggested" not in d["flags"]


def test_amountless_non_section_word_not_promoted():
    d = ic.classify_line("Nonstick spray")
    assert d["kind"] == "flagged" and "ambiguous_section" in d["flags"]


def test_step_mirror_hint_promotes():
    d = ic.classify_line("Habanero Syrup", section_hints={"habanero syrup"})
    assert d["kind"] == "section" and "section_suggested" in d["flags"]


def test_section_ends_with_word_promoted():
    # head-noun match: modifier + section word -> promote + flag (no step-mirror hint needed)
    for line in ("Habanero Syrup", "Lemon Glaze", "Almond Filling"):
        d = ic.classify_line(line)
        assert d["kind"] == "section", line
        assert "section_suggested" in d["flags"], line


def test_ingredient_ending_non_section_word_unaffected():
    for line in ("kosher salt", "olive oil", "ground cumin"):
        d = ic.classify_line(line)
        assert d["kind"] == "flagged" and "section_suggested" not in d["flags"], line


def test_long_line_containing_section_word_not_promoted():
    d = ic.classify_line("maple syrup for drizzling on top")   # >3 words -> the bound holds
    assert d["kind"] == "flagged" and "section_suggested" not in d["flags"]


# ----------------------------------------------------------------- multiplier N=1 vs N>1
def test_multiplier_one_resolved_no_flag():
    d = ic.classify_line("1 x 397 grams can of condensed milk")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"], d["name"]) == ("1", "can", "condensed milk")
    assert d["grams_harvested"] == 397.0
    assert "multiplier" not in d["flags"]


def test_multiplier_two_still_flagged():
    d = ic.classify_line("2 x 6 oz halibut fillets")   # NO container -> still flagged
    assert d["kind"] == "flagged" and "multiplier" in d["flags"]


# ----------------------------------------------------------------- canned goods (COUNT+CONTAINER+SIZE)
def test_canned_unit_before_paren():
    d = ic.classify_line("1 can (15 ounces) chickpeas, rinsed and drained, or 1 1/2 cups cooked chickpeas")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"]) == ("1", "can")
    assert d["grams_harvested"] == 425.0                  # 15 oz -> g
    assert d["name"].startswith("chickpeas") and "or 1 1/2 cups cooked chickpeas" in d["name"]
    assert "multiplier" not in d["flags"]


def test_canned_paren_before_unit():
    d = ic.classify_line("1 (12-ounce) can evaporated milk")
    assert (d["amount"], d["unit"], d["name"]) == ("1", "can", "evaporated milk")
    assert d["grams_harvested"] == 340.0                  # 12 oz -> g


def test_canned_hyphenated_inline():
    d = ic.classify_line("1 8-ounce package cream cheese")
    assert (d["amount"], d["unit"], d["name"]) == ("1", "package", "cream cheese")
    assert d["grams_harvested"] == 227.0                  # 8 oz -> g


def test_canned_x_form_subsumed():
    d = ic.classify_line("1 x 397 grams can of condensed milk")
    assert (d["amount"], d["unit"], d["name"]) == ("1", "can", "condensed milk")
    assert d["grams_harvested"] == 397.0


def test_canned_dual_oz_g_takes_grams():
    d = ic.classify_line("1 1/2 tins (21 oz / 600g) chickpeas, drained")
    assert (d["amount"], d["unit"], d["name"]) == ("1 1/2", "tins", "chickpeas, drained")
    assert d["grams_harvested"] == 600.0                  # dual -> grams directly


def test_canned_n_gt_1_resolves_no_flag():
    d = ic.classify_line("2 cans (14 oz) diced tomatoes")
    assert (d["amount"], d["unit"], d["name"]) == ("2", "cans", "diced tomatoes")
    assert d["grams_harvested"] == 397.0                  # per-can 14 oz -> g
    assert "multiplier" not in d["flags"]


def test_canned_prep_paren_not_eaten():
    d = ic.classify_line("1 jar (drained) artichoke hearts")   # paren is prep, not a weight
    assert d["grams_harvested"] is None and "(drained)" in d["name"]


# ----------------------------------------------------------------- ranges
def test_range_endash():
    d = ic.classify_line("1 – 2 tbsp extra virgin olive oil")
    assert d["range"] == (1.0, 2.0) and d["unit"] == "tbsp"


def test_range_to():
    assert ic.classify_line("4 to 6 slices")["range"] == (4.0, 6.0)


def test_range_hyphen():
    assert ic.classify_line("2-3 cloves garlic")["range"] == (2.0, 3.0)


# ----------------------------------------------------------------- risky -> flagged
def test_multiplier_flagged_with_alternative():
    d = ic.classify_line("2 x 6oz halibut fillets, or other white fish")
    assert d["kind"] == "flagged" and "multiplier" in d["flags"]
    assert d["has_alternative"] is True


def test_each_flagged_but_amount_still_parsed():
    d = ic.classify_line("1/2 tsp each ground coriander, cumin, nutmeg")
    assert d["kind"] == "flagged" and "each_multi" in d["flags"]
    assert d["value"] == 0.5 and d["unit"] == "tsp"      # still parsed, for review


# ----------------------------------------------------------------- servings
@pytest.mark.parametrize("raw,expected", [
    ("Serves 4", 4),
    ("Servings 2", 2),
    ("Servings: 2", 2),
    ("Serves: 4", 4),
    ("Makes 24 cookies", 24),
    ("8 servings", 8),
    ("18", 18),                                           # exact bare integer accepted
    ("10-inch Bundt cake, serving 8 or more", 8),         # adjacent to a word -> 8, never 10
    ("4oz/100g", None),                                   # no servings word -> blank
    ("", None),
])
def test_servings(raw, expected):
    assert ic.parse_servings(raw) == expected


def test_servings_never_grabs_pan_size():
    assert ic.parse_servings("10-inch Bundt cake, serving 8 or more") != 10


# ----------------------------------------------------------------- incomplete recipes (drop nothing)
def test_no_ingredients_flagged():
    r = ic.clean_recipe(_norm(ingredient_lines=[], directions=["1. mix"]))
    assert "no_ingredients" in r["recipe_flags"] and "no_directions" not in r["recipe_flags"]


def test_no_directions_flagged_keeps_ingredients():
    r = ic.clean_recipe(_norm(ingredient_lines=["2 tbsp oil", "1 egg"], directions=[]))
    assert "no_directions" in r["recipe_flags"]
    assert len(r["ingredients"]) == 2                     # nothing dropped


def test_photo_only_flagged():
    r = ic.clean_recipe(_norm(ingredient_lines=[], directions=[], images=[{"bytes": 1}]))
    assert r["recipe_flags"] == ["no_ingredients", "no_directions", "photo_only"]


def test_nothing_dropped_sections_kept():
    r = ic.clean_recipe(_norm(ingredient_lines=["a", "b", "c", "SAUCE:"]))
    assert len(r["ingredients"]) == 4                     # every line preserved, incl. the section


# ------------------------------------------------- split_qty (qty -> quantity + unit, additive)
import re as _re


@pytest.mark.parametrize("qty, quantity, unit", [
    ("2 tablespoons", "2", "tablespoons"),   # number + measuring unit
    ("1 cup", "1", "cup"),
    ("1 1/2 tsp", "1 1/2", "tsp"),           # mixed-fraction amount stays whole in quantity
    ("2", "2", ""),                          # number only, no unit
    ("1 1/2", "1 1/2", ""),
    ("10 to 12", "10 to 12", ""),            # a unit-less range is still a number-only expression
    ("", "", ""),                            # empty
    (None, "", ""),                          # None qty
    ("4 cloves", "4", "cloves"),             # count-noun becomes the unit
    ("2 large", "2", "large"),
    ("1 medium head", "1", "medium head"),
    ("2 lb / 1 kg", "2 lb / 1 kg", ""),      # slash-dual: irreducible -> whole string, no unit
    ("500 g / 1 lb", "500 g / 1 lb", ""),
    ("3 + 2 tbsp", "3 + 2 tbsp", ""),        # compound: irreducible -> whole string
    ("pinch", "pinch", ""),                  # no leading number -> whole string, no unit
    ("to taste", "to taste", ""),
])
def test_split_qty_buckets(qty, quantity, unit):
    assert ic.split_qty(qty) == (quantity, unit)


@pytest.mark.parametrize("qty", [
    "2 tablespoons", "1 cup", "1 1/2 tsp", "2", "1 1/2", "10 to 12", "", "4 cloves",
    "2 large", "1 medium head", "2 lb / 1 kg", "500 g / 1 lb", "3 + 2 tbsp", "pinch", "to taste",
])
def test_split_qty_recombine_is_lossless(qty):
    """The Option-B guarantee: quantity + ' ' + unit (whitespace-normalized) reconstructs qty,
    so the additive split never loses or alters the original."""
    quantity, unit = ic.split_qty(qty)
    norm = (lambda s: _re.sub(r"\s+", " ", s or "").strip())
    assert norm(f"{quantity} {unit}") == norm(qty)


# --------------------------------------------------------------------------- #
# Source-text cleanup layer (CLEANUP_RULES)
# --------------------------------------------------------------------------- #
# The layer exists to ACCUMULATE rules for artifacts other publishers will produce, so these tests
# pin the CONTRACT (shape of the table, flag/reason pairing, raw preservation) as much as today's one
# rule — a second rule should need a tuple and a case, not a rethink.

def test_cleanup_rule_table_has_the_shape_the_writer_expects():
    """Each rule is (flag, compiled pattern, replacement, reason). import_write._line_flag_rows looks
    the reason up by flag, so a rule missing one would write a flag row with reason NULL."""
    for flag, rx, repl, reason in ic.CLEANUP_RULES:
        assert flag.startswith("cleaned_"), flag        # namespaced, so a queue can filter them
        assert hasattr(rx, "sub") and isinstance(repl, str)
        assert reason and isinstance(reason, str)
    # ⚠️ EVERY RULE HAS A REASON, AND THE MAP MAY HOLD MORE THAN THE RULES. It did hold exactly the
    #    rules, and the direction that matters is this one: a flag with no reason writes a queue row
    #    saying nothing.
    for flag, _p, _rp, reason in ic.CLEANUP_RULES:
        assert ic.CLEANUP_REASONS.get(flag) == reason, flag
    # ⚠️ THE ENTRIES THAT ARE NOT REGEX SUBSTITUTIONS ARE NAMED, AND THE LAST VERSION OF THIS COMMENT
    #    SAID THAT WAS SO WHILE THE ASSERTION BELOW IT FORBADE THE NEXT ONE. It named one entry with
    #    an equality, which is the same thing as forbidding a second. The three line-flag reasons
    #    polish round 2 added are read by import_write._line_flag_rows exactly as the others are, and
    #    they are not "cleaned_" because nothing substituted anything: one moves a row, one rewrites a
    #    name and one is a REFUSAL to.
    #    Round B adds five more for the same reason: each names a row the amount rules REFUSED, and
    #    a refusal with no words is the one a person has to read.
    extra = set(ic.CLEANUP_REASONS) - {f for f, _p, _rp, _r in ic.CLEANUP_RULES}
    assert extra == {"cleaned_emphasis_wrap", "ingredient_optional_grouped",
                     "ingredient_name_lowercased", "ingredient_name_title_cased",
                     "unbalanced_bracket", "broken_amount_unproved", "no_name_column",
                     "no_name_left", "food_inside_the_fragment"}, extra
    assert all(r and isinstance(r, str) for r in ic.CLEANUP_REASONS.values())


def test_clean_source_text_reports_what_it_changed():
    out, flags = ic.clean_source_text("flour (, bread or plain)")
    assert out == "flour (bread or plain)"
    assert flags == ["cleaned_paren_comma"]


def test_clean_source_text_is_a_no_op_on_well_formed_text():
    for s in ["flour (bread or plain)", "2 tbsp oil, canola", "1 (14-ounce) can beans",
              "chicken thighs (boneless, skinless)"]:
        assert ic.clean_source_text(s) == (s, [])


@pytest.mark.parametrize("src,expected", [
    ("3 cups (450g) flour (, bread or plain/all purpose (Note 1))",
     "flour (bread or plain/all purpose (Note 1))"),
    ("1 1/2 tbsp plain oil - canola (, vegetable, peanut)",
     "plain oil - canola (vegetable, peanut)"),
    ("1 1/2 tbsp flour (, for dusting)", "flour (for dusting)"),
])
def test_classify_line_cleans_the_name(src, expected):
    assert ic.classify_line(src)["name"] == expected


def test_the_publishers_original_text_survives_untouched():
    """`raw` becomes recipe_ingredients.raw_text. The cleanup improves the parsed NAME; it must never
    edit the source record, or the original wording is unrecoverable."""
    src = "1 1/2 tbsp plain oil - canola (, vegetable, peanut)"
    line = ic.classify_line(src)
    assert line["raw"] == src
    assert line["name"] != src


def test_a_note_reference_survives_the_cleanup_verbatim():
    """A later feature resolves "(Note N)" against the page's notes. The cleanup repairs the bracket
    AROUND the reference and must not touch, renumber or strip the reference itself."""
    line = ic.classify_line("2 tsp cooking salt (, HALVE if using table salt (Note 3))")
    assert "(Note 3)" in line["name"]
    assert line["name"] == "cooking salt (HALVE if using table salt (Note 3))"


def test_a_cleaned_line_carries_a_flag_so_the_tidying_is_visible():
    line = ic.classify_line("2 tbsp flour (, for dusting)")
    assert "cleaned_paren_comma" in line["flags"]


def test_a_cleanup_flag_becomes_a_review_row_with_its_reason():
    import import_write
    line = ic.classify_line("2 tbsp flour (, for dusting)")
    rows = import_write._line_flag_rows(3, line)
    assert rows == [{"position": 3, "flag": "cleaned_paren_comma",
                     "reason": "removed a stray comma after '(' — publisher artifact"}]


def test_cleanup_composes_with_the_existing_grams_declined_flag():
    """Flags accumulate rather than replace — a line can be both cleaned and gram-declined."""
    line = ic.classify_line("2 tbsp flour (, for dusting)")
    assert isinstance(line["flags"], list)
    assert line["flags"].count("cleaned_paren_comma") == 1


# ---- rule 2: doubled parentheses ------------------------------------------------------------- #
@pytest.mark.parametrize("src,expected", [
    ("2 tsp dark soy ((Note 4))", "dark soy (Note 4)"),
    ("2 dried red chillies ((barely spicy, but can omit))", "dried red chillies (barely spicy, but can omit)"),
    ("1 Tbsp coconut oil ((or water))", "coconut oil (or water)"),
    ("21 ounces firm tofu ((1 1/2 containers, 600g; cut into cubes))",
     "firm tofu (1 1/2 containers, 600g; cut into cubes)"),
])
def test_doubled_parens_collapse_at_both_ends(src, expected):
    assert ic.classify_line(src)["name"] == expected


def test_the_open_space_open_variant_is_the_same_shape():
    """minimalistbaker emits '( (' rather than '((' — a stray space, same template defect, and the
    \\s* in the pattern covers it without a rule of its own."""
    out, flags = ic.clean_source_text("lentils ( (rinsed and drained // or sub red))")
    assert out == "lentils (rinsed and drained // or sub red)"
    assert flags == ["cleaned_double_paren"]


@pytest.mark.parametrize("src", [
    "dark soy ((Note 4)",          # doubled open, single close
    "dark soy (Note 4))",          # single open, doubled close
    "((Note 4",                    # no close at all
])
def test_an_unbalanced_row_is_left_alone_rather_than_half_fixed(src):
    """Collapsing on the prefix alone would strand a bracket. The pattern requires BOTH ends, so an
    unbalanced row is returned exactly as found and raises no flag — nothing was cleaned."""
    assert ic.clean_source_text(src) == (src, [])


@pytest.mark.parametrize("src", [
    # real recipetineats text: the inner paren does NOT span the whole content
    "2 tbsp Chinese cooking wine (or Taiwanese rice wine (mijiu) if you can find it, or stock (Note 5))",
    "3 cups flour (bread or plain/all purpose (Note 1))",
    "1 (14- to 16-ounce) package firm tofu, drained",
    "4 cloves garlic (minced)",
])
def test_legitimate_nesting_is_never_collapsed(src):
    """Two brackets that mean different things must stay two brackets — merging them would lose the
    distinction between a qualifier and the note reference inside it."""
    assert ic.clean_source_text(src) == (src, [])


def test_both_rules_can_fire_on_one_line_and_each_is_flagged():
    out, flags = ic.clean_source_text("soy (, or all-purpose) and chilli ((omit if mild))")
    assert out == "soy (or all-purpose) and chilli (omit if mild)"
    assert flags == ["cleaned_paren_comma", "cleaned_double_paren"]


def test_a_note_reference_survives_the_doubled_paren_collapse():
    assert ic.classify_line("2 tsp dark soy ((Note 4))")["name"] == "dark soy (Note 4)"


def test_paren_balance_is_preserved_by_every_rule():
    """A cleanup must never leave a row less balanced than it found it."""
    for src in ["dark soy ((Note 4))", "flour (, for dusting)", "x ((a))", "x (, y (Note 1))",
                "wine (or rice (mijiu) if you can (Note 5))"]:
        out, _ = ic.clean_source_text(src)
        assert out.count("(") == out.count(")"), out


# ---------------------------------------- compound quantities written with a connective ("1 and 1/2")
# The signal is INTEGER + connective + FRACTION, never the word alone. These tests hold BOTH sides of
# that boundary: the forms that must parse, and the "and" lines that must NOT become quantities.

@pytest.mark.parametrize("line, amount, value, unit, name", [
    # the 4 real forms, verbatim from sallysbakingaddiction.com (4 of its 17 ingredient lines)
    ("1 and 1/4 cups (285g) canned pumpkin puree*", "1 1/4", 1.25, "cups", "canned pumpkin puree*"),
    ("1 and 2/3 cups (208g) all-purpose flour (spooned & leveled)", "1 2/3", 5 / 3, "cups",
     "all-purpose flour (spooned & leveled)"),
    ("1 and 1/2 teaspoons ground cinnamon", "1 1/2", 1.5, "teaspoons", "ground cinnamon"),
    ("1 and 1/2 cups (180g) confectioners' sugar", "1 1/2", 1.5, "cups", "confectioners' sugar"),
    # the anticipated (unwitnessed) connectives
    ("1 & 1/2 cups flour", "1 1/2", 1.5, "cups", "flour"),
    ("1 + 1/2 cups flour", "1 1/2", 1.5, "cups", "flour"),
    ("1 and 1/2 cups flour", "1 1/2", 1.5, "cups", "flour"),
])
def test_connective_compound_parses_as_one_quantity(line, amount, value, unit, name):
    """The connective is a spelling of the space in a mixed number, so it yields ONE amount with a
    real numeric value — the value matters as much as the text: a regex-only change would match here
    and still hand back value=None, because _to_value splits a mixed number on whitespace."""
    d = ic.classify_line(line)
    assert d["amount"] == amount
    assert d["value"] == pytest.approx(value)
    assert d["unit"] == unit
    assert d["name"] == name


@pytest.mark.parametrize("line, amount, value, unit", [
    ("1 1/4 cups flour", "1 1/4", 1.25, "cups"),      # plain-space mixed number
    ("1½ cups flour", "1½", 1.5, "cups"),   # digit + unicode fraction, adjacent
    ("1 ½ cups flour", "1 ½", 1.5, "cups"),  # digit + unicode fraction, spaced
    ("½ cup water", "½", 0.5, "cup"),        # bare unicode fraction
    ("2 cups flour", "2", 2.0, "cups"),                # plain integer
    ("1/2 teaspoon salt", "1/2", 0.5, "teaspoon"),     # bare ascii fraction
])
def test_already_working_compound_forms_are_unchanged(line, amount, value, unit):
    """PINNED so the connective pattern can't be loosened later without this failing."""
    d = ic.classify_line(line)
    assert (d["amount"], d["unit"]) == (amount, unit)
    assert d["value"] == pytest.approx(value)


@pytest.mark.parametrize("line, amount, name", [
    # "and" joining two NON-NUMERIC things is not a quantity — a fraction must follow the connective
    ("Salt and pepper (optional)", "", "Salt and pepper (optional)"),
    ("1 red bell pepper, cored and diced", "1", "red bell pepper, cored and diced"),
    ("1/2 tsp each salt and pepper", "1/2", "each salt and pepper"),
    ("2 tablespoons chopped fresh cilantro (stems and leaves)", "2",
     "chopped fresh cilantro (stems and leaves)"),
])
def test_and_between_non_numbers_is_not_a_compound_quantity(line, amount, name):
    """The false-positive boundary. Measured over 7,052 corpus+archive+fixture lines: 379 contain
    "and", 4 match INTEGER+connective+FRACTION, and those 4 are the intended targets."""
    d = ic.classify_line(line)
    assert d["amount"] == amount
    assert d["name"] == name
    assert "and" not in d["amount"]


# ----------------------------------------------------------------- measure-list parenthetical
# A parenthetical whose WHOLE content is a delimited list of measures restates ONE quantity, so its
# gram is the line's weight. The discriminator is the ABSENCE of prose — see _MEASURE_LIST.
@pytest.mark.parametrize("line, grams", [
    # the 7 seriousseats fixture lines (the only site in the 9 committed fixtures with this shape)
    ("4 ounces plain Greek yogurt (1/2 cup; 115g), preferably nonfat", 115.0),
    ("1/2 ounce vanilla extract (1 tablespoon; 15g)", 15.0),
    ("10 ounces all-purpose flour (2 cups; 280g)", 280.0),
    ("5 1/4 ounces sugar (3/4 cup; 150g), preferably toasted", 150.0),
    ("3 ounces oat flour (3/4 cup; 85g), such as Bob's Red Mill (see note)", 85.0),
    ("5 1/4 ounces coconut oil, virgin or refined (3/4 cup; 150g), creamy but firm, about 70°F (21°C)", 150.0),
    # the stored-corpus shapes: semicolon, slash, hedged, unicode fraction, "stick" as a unit word
    ("1 cup (16 Tbsp; 226g) unsalted butter, cut into 16 pieces", 226.0),
    ("2 sticks (16 tablespoons/226 grams) unsalted butter", 226.0),
    ("8 ounces (about 1½ cups/227 grams) chopped semisweet chocolate", 227.0),
    ("½ cup unsalted butter (1 stick/113g)", 113.0),
    ("2 ½ teaspoons baking powder (0.35 oz / 10g)", 10.0),
])
def test_measure_list_paren_harvests_its_gram(line, grams):
    d = ic.classify_line(line)
    assert d["grams_harvested"] == grams
    assert "grams_declined" not in d["flags"]     # it is harvested, so nothing is declined


@pytest.mark.parametrize("line, grams", [
    # TWO WEIGHTS, one gram: the gram wins and the oz/lb sibling is ignored — this column stores
    # GRAMS, so the metric token needs no conversion and no rounding.
    ("1 cup (6 ounces/170 grams) bittersweet or semisweet chocolate chips", 170.0),
    ("1 cup (8 ounces or 230 grams) unsalted butter, at room temperature", 230.0),
    ("½ cup (about 3.5 ounces/100 g) short-grain rice", 100.0),
    ("2 large eggs (3.5 oz / 100g)", 100.0),
    # THREE measures, still one gram
    ("2 packages (about 3 cups/74 grams/ 2.6 ounces total) freeze-dried raspberries", 74.0),
])
def test_measure_list_takes_the_gram_not_the_ounce(line, grams):
    assert ic.classify_line(line)["grams_harvested"] == grams


def test_measure_list_with_two_different_grams_declines():
    # genuinely ambiguous — decline over guess. (0 such rows in the corpus; pinned so a future
    # "just take the first" loosening is a deliberate choice rather than an accident.)
    d = ic.classify_line("1 cup (100 g; 200 g) mystery")
    assert d["grams_harvested"] is None
    assert "grams_declined" in d["flags"]


@pytest.mark.parametrize("line", [
    # PROSE in the paren -> not a restatement -> declines exactly as before. Each of these would be
    # a WRONG harvest: a per-unit weight, extra flour, an uncooked weight, an alternative form.
    "4 chicken thigh fillets, skin-on and bone-in (~250g/8oz each)",
    "2 medium sea bass (around 10 oz./300g each)",
    "3 ½ cups bread flour (you may need up to 1/2 cup / 60g for kneading)",
    "5 cups cooked jasmine rice (from 1⅔ cups/300g uncooked)",
    "2 banana shallots (about 2 oz/70g total prepared weight), finely chopped",
])
def test_prose_in_the_paren_still_declines(line):
    d = ic.classify_line(line)
    assert d["grams_harvested"] is None
    assert "grams_declined" in d["flags"]


@pytest.mark.parametrize("line, name", [
    # NO weight in the paren -> the new path is never reached; name and fields untouched.
    ("1 cup coffee (light roast)", "coffee (light roast)"),
    ("2 tbsp soy sauce (low sodium)", "soy sauce (low sodium)"),
    # ⚠️ 'large' MOVED TO THE UNIT with the size-word rule, and this case is still about the PAREN.
    #    'bundle' is not a counting noun here (it is not in _COUNT_NOUNS) so it stays in the name.
    ("1 large bundle kale (loosely chopped or torn)", "bundle kale (loosely chopped or torn)"),
])
def test_paren_with_no_weight_is_untouched(line, name):
    d = ic.classify_line(line)
    assert d["grams_harvested"] is None
    assert d["name"] == name
    assert "grams_declined" not in d["flags"]


def test_measure_list_leaves_the_name_alone():
    """harvest_grams still hands back no gram_paren, so _strip_gram_paren has nothing to remove.

    ⚠️ ROUND B IS THE LATER STAGE THIS TEST WAS WAITING FOR. The restatement list leaves the name
    as the author's second amount, both measures of it, joined by the separator the display
    stacks on. The harvest is unchanged, which is what the last line still pins."""
    line = "1 cup (16 Tbsp; 226g) unsalted butter, cut into 16 pieces"
    d = ic.classify_line(line)
    assert d["grams_harvested"] == 226.0
    assert d["name"] == "unsalted butter, cut into 16 pieces"
    assert d["secondary_measure"] == "16 Tbsp / 226g"
    assert d["raw"] == line
    assert ic.harvest_grams(line)[2] is None            # no paren handed to the name-stripper


@pytest.mark.parametrize("line, grams, name, secondary", [
    # The single-measure forms, pinned. grams is unchanged by round B in every one of them, which
    # is the half this table was written to hold. secondary_measure now names the author's backup.
    ("(250g) dried chickpeas", 250.0, "(250g) dried chickpeas", None),
    ("14 cups (250g) dried chickpeas", 250.0, "dried chickpeas", "250g"),
    ("1 cup (250 g) flour", 250.0, "flour", "250 g"),
    ("100 g (1 cup) granulated sugar", 100.0, "granulated sugar", "1 cup"),
    ("1 cup plus 2 tablespoons (270g) tahini (light roast)", 270.0,
     "tahini (light roast)", "270g"),
])
def test_single_measure_gram_paren_forms_unchanged(line, grams, name, secondary):
    d = ic.classify_line(line)
    assert d["grams_harvested"] == grams
    assert d["name"] == name
    assert d["secondary_measure"] == secondary


# --------------------------------------------------------------------------- #
# normalize_time
# --------------------------------------------------------------------------- #
# ⚠️ THE TABLE IS THE LIVE CORPUS, NOT A HANDFUL OF INVENTED STRINGS. tests/fixtures/time-cases.json
#    was generated from all 63 distinct spellings the 218 stored times actually use, plus the edge
#    cases neither corpus happens to hold. tests/js/timefmt-sync.test.js asserts static/timefmt.js
#    against the SAME file, so the two implementations cannot drift apart silently.
TIME_CASES = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "time-cases.json").read_text(encoding="utf-8"))


def test_the_time_case_table_covers_the_real_corpus():
    """61 distinct spellings are stored, down from 63 once the two junk values were cleared, plus
    the edge cases and the already-parenthesized forms no stored row happens to hold."""
    assert len(TIME_CASES) >= 61


@pytest.mark.parametrize("case", TIME_CASES, ids=lambda c: c["in"] or "<empty>")
def test_normalize_time_over_every_stored_spelling(case):
    assert ic.normalize_time(case["in"]) == case["out"]


@pytest.mark.parametrize("raw,want", [
    ("10 mins", "10 min"), ("10 minutes", "10 min"), ("15mins", "15 min"),
    ("1 hour", "1 hr"), ("2 hrs", "1 hr".replace("1", "2")), ("1 hours", "1 hr"),
    ("1 hr, 30 min", "1 hr 30 min"), ("8 hr, 20 min", "8 hr 20 min"),
    ("1 hour 10 minutes", "1 hr 10 min"),
])
def test_the_unit_words_publishers_use_map_to_the_two_the_app_shows(raw, want):
    assert ic.normalize_time(raw) == want


def test_a_range_stays_a_range():
    """⚠️ NOT THE duration_text RULE. That one takes the upper end of an ISO Duration range, where
    the publisher gave two machine values for one column and one had to be chosen. An author who
    wrote a range in words meant the range, so narrowing it would invent precision."""
    assert ic.normalize_time("15-20 minutes") == "15–20 min"


@pytest.mark.parametrize("raw,want", [
    ("35 min (plus 1–3 hr marinating)", "35 min (plus 1–3 hr marinating)"),
    ("30 mins, plus 1 hour soaking", "30 min (plus 1 hr soaking)"),
    ("20 minutes additional time", "20 min (additional time)"),
    ("2 hours 25 mins, plus cooling", "2 hr 25 min (plus cooling)"),
    ("40 min (plus 2 hr+ marinating)", "40 min (plus 2 hr+ marinating)"),
])
def test_a_trailing_note_is_kept_and_its_own_durations_normalized(raw, want):
    """'plus 1 hr soaking' is the difference between a dish you can start at six and one you
    cannot. The number is normalized and the note keeps its own words.

    ⚠️ PARENTHESES, NOT THE MIDDLE DOT. The reading view joins Prep, Cook and Total with " · ", so a
    note carrying the same divider made a four-part line out of two facts. Parentheses say
    subordinate where the dot says sibling, and they leave the dot meaning one thing."""
    assert ic.normalize_time(raw) == want


@pytest.mark.parametrize("case", TIME_CASES, ids=lambda c: c["in"] or "<empty>")
def test_normalize_time_is_idempotent(case):
    """Running it over its own output changes nothing. A note that arrives already wrapped has its
    parens stripped and put back, which is what makes re-normalizing a stored value safe."""
    assert ic.normalize_time(case["out"]) == case["out"]


@pytest.mark.parametrize("junk", ["1 cup", "to taste", "whenever", "--", "overnight"])
def test_an_unreadable_value_is_returned_exactly_as_stored(junk):
    """⚠️ NEVER BLANKED AND NEVER GUESSED AT. A time column holding '1 cup' stays visible and
    fixable. Two of the 218 stored times are not times, and both are fixed by hand."""
    assert ic.normalize_time(junk) == junk


def test_normalize_time_handles_none_and_empty():
    assert ic.normalize_time(None) == "" and ic.normalize_time("   ") == ""


def test_a_new_import_stores_the_normalized_time():
    """The normalizer runs on the way IN as well as on the way out, so a fresh import and an
    already-stored row finally read the same."""
    cleaned = ic.clean_recipe({
        "name": "T", "ingredient_lines": ["1 large egg"], "directions": ["Do it."],
        "servings_raw": "2", "source": "url", "source_url": "https://example.test/t",
        "categories": [], "description": "", "notes": "", "rating": None, "uid": "t-1",
        "hash": "h", "images": [], "primary_photo": None, "source_rating": None,
        "prep_time": "10 mins", "cook_time": "1 hour", "total_time": "",
    })
    assert cleaned["times"] == {"prep": "10 min", "cook": "1 hr", "total": ""}


# ================================================================================================ #
# STEP STRUCTURE (migration 059) — the rules a new import applies, and the SAME rules the repair
# pass applies. scripts/convert_step_headings.py imports these names, so a recipe imported tomorrow
# is structured the way the 300 already-imported recipes were just repaired to be.
# ================================================================================================ #

def _plan(lines, notes=""):
    rows, out_notes, conv = ic.plan_step_rows(lines, notes)
    shape = [(r["heading_level"] if r["is_heading"] else 0, r["text"]) for r in rows]
    return shape, out_notes, {c["flag"] for c in conv}


def test_birria_shape_an_emphasized_title_and_two_dash_labels():
    """⚠️ THE NUMERIC RANGE IS THE ONE THAT MATTERS HERE. "Bake for 30 - 35 minutes" is a duration,
    and without the guard it becomes a heading reading "Bake for 30" with "35 minutes" under it.
    8 of the 62 dash candidates in the corpus review were this shape."""
    shape, _, flags = _plan([
        "**MAKE CRISPY CHEESY BIRRIA TACOS!**",
        "Deseed – Trim and discard stems. Cut lengthwise, remove the seeds.",
        "Simmer – Put chillis in a large saucepan of boiling water.",
        "Bake for 30 – 35 minutes, until the cheese melts.",
    ])
    assert shape == [
        (1, "Make crispy cheesy birria tacos!"),          # unwrapped AND recased
        (2, "Deseed"),
        (0, "Trim and discard stems. Cut lengthwise, remove the seeds."),
        (2, "Simmer"),
        (0, "Put chillis in a large saucepan of boiling water."),
        (0, "Bake for 30 – 35 minutes, until the cheese melts."),
    ]
    assert flags == {"step_heading_unwrapped", "step_label_lifted", "step_heading_recased"}


def test_butter_chicken_shape_a_colon_label_and_a_dash_label_are_the_same_thing():
    shape, _, flags = _plan([
        "Marinade: Mix the chicken with the yogurt and spices.",
        # ⚠️ "Blend", capitalized, so this test is about the colon and the dash and not about the
        #    sentence gate. A lowercase continuation is now flagged rather than lifted (see
        #    _starts_a_sentence), which is a different question and has its own tests.
        "Optional blitz – Blend the sauce until smooth.",
        "Cook the chicken for 20 minutes.",
    ])
    # ⚠️ LEVEL 1 FOR BOTH, BECAUSE NOTHING OPENS A GROUP ABOVE THEM (Andy's rule). "Marinade" is
    #    the first heading in the recipe, so it opens a part rather than belonging to one, and
    #    "Optional blitz" sits under it as a sibling section for the same reason: the demotion
    #    needs a SECTION above, and the first lifted label is what creates the first one.
    assert shape == [
        (1, "Marinade"), (0, "Mix the chicken with the yogurt and spices."),
        # ⚠️ "Blend", NOT "blend". Lifting a label leaves the step starting mid-sentence, so its
        #    first visible letter is capitalized (rule 6).
        (2, "Optional blitz"), (0, "Blend the sauce until smooth."),
        (0, "Cook the chicken for 20 minutes."),
    ]
    assert flags == {"step_label_lifted"}


def test_beans_shape_an_all_caps_section_a_label_and_a_note():
    shape, notes, flags = _plan([
        "THE PREP",
        "Rinse: Tip the beans into a colander and rinse well.",
        "Soak the beans overnight in plenty of cold water.",
        "Note: Pick over the beans for stones first.",
    ])
    assert shape == [
        (1, "The prep"),                                  # ALL CAPS, no colon -> a SECTION
        (2, "Rinse"), (0, "Tip the beans into a colander and rinse well."),
        (0, "Soak the beans overnight in plenty of cold water."),
    ]
    assert notes == "Note: Pick over the beans for stones first."
    assert flags == {"step_label_lifted", "step_note_moved", "step_heading_recased"}


def test_bagel_shape_an_italic_heading_and_two_notes_joined_to_existing_notes():
    """⚠️ A BLANK LINE, MEASURED. 78 of the 79 newline runs in the corpus's notes are one blank
    line, so a moved note joins the convention already there rather than inventing one."""
    shape, notes, flags = _plan([
        "_Cold Proof_",
        "Shape them into rounds.",
        "Note: Please see directions on your brand of yeast.",
        "Tip - a wetter dough gives a chewier crumb.",
    ], notes="Keeps 3 days in a paper bag.")
    assert shape == [(1, "Cold Proof"), (0, "Shape them into rounds.")]
    # ⚠️ EACH KEEPS ITS OWN LABEL, which is what the kind headers group on: the Note goes under
    #    Notes and the Tip under Tips. Stripping them made both read as Notes.
    assert notes == ("Keeps 3 days in a paper bag.\n\n"
                     "Note: Please see directions on your brand of yeast.\n\n"
                     "Tip - a wetter dough gives a chewier crumb.")
    assert ic.note_kind("Note: Please see directions on your brand of yeast.") == "notes"
    assert ic.note_kind("Tip - a wetter dough gives a chewier crumb.") == "tips"
    assert flags == {"step_heading_unwrapped", "step_note_moved"}


def test_a_note_is_checked_before_the_label_rule():
    """⚠️ ORDER IS LOAD-BEARING. "Note: Check your yeast" matches the lead-in label shape exactly, so
    a label-first reading lifts "Note" into a heading and leaves the note standing as an
    instruction — the opposite of what it is."""
    shape, notes, _ = _plan(["Note: Check your yeast."])
    assert shape == []
    assert notes == "Note: Check your yeast."


def test_a_short_title_like_step_is_left_alone():
    """⚠️ A DECISION, NOT A GAP. "Prepare the pan" and "Chop everything" are the same shape, one a
    heading and one an instruction, and no length or verb rule told them apart on the corpus without
    also catching real steps. The repair converted 21 of these from a reviewed list; an importer has
    no reviewer, so it leaves them as steps. That error is visible and fixable in the step row menu.
    The opposite error hides an instruction inside a heading."""
    shape, _, flags = _plan(["Prepare the pan", "Chop everything", "Make the crust"])
    assert shape == [(0, "Prepare the pan"), (0, "Chop everything"), (0, "Make the crust")]
    assert flags == set()


def test_a_hyphenated_word_is_not_a_label():
    """The dash separator needs spaces on both sides. Without that, "Slow-cook the beef" lifts
    "Slow" into a heading."""
    shape, _, _ = _plan(["Slow-cook the beef until it shreds."])
    assert shape == [(0, "Slow-cook the beef until it shreds.")]


def test_a_label_carrying_a_link_lifts_and_the_link_moves_into_the_step():
    """⚠️ A HEADING IS ESCAPED AND NEVER LINKIFIED (app.js renderStepRow), so a lifted label holding
    [[spinach]] would print the brackets. It used to be refused for that reason. The heading now
    takes the plain words and the link moves to the next mention of the same word in the step,
    which is where a reader would reach for it anyway. bulgogi-bowls is the corpus case.

    ⚠️ THROUGH THE REVIEWED PATH, WHICH IS HOW THE CORPUS REACHES IT. bulgogi-bowls' real text runs
    on in lowercase ("...spinach]]: heat 2 tsp oil..."), so the importer's sentence gate now declines
    to judge it and flags it instead (test below). A person judged it, and a reviewed label keeps its
    decision, so the lift and the link move still happen exactly as they did."""
    text = "Wilt the [[spinach]]: heat 2 tsp oil in a pan. Add half the spinach, toss with tongs."
    label, rest = ic.split_lead_label(text, label="Wilt the spinach")
    label, rest, moved = ic.move_link_out_of_label(label, rest)
    assert moved is True
    assert label == "Wilt the spinach"
    assert ic.capitalize_first_visible(rest) == \
        "Heat 2 tsp oil in a pan. Add half the [[spinach|spinach]], toss with tongs."


def test_the_importer_flags_that_same_bulgogi_step_rather_than_guessing():
    """The other side of the same row. With no decision in hand, nothing after the label starts a
    new sentence, so the importer leaves the step whole and says so."""
    text = "Wilt the [[spinach]]: heat 2 tsp oil in a pan. Add half the spinach, toss with tongs."
    shape, _, flags = _plan([text])
    assert shape == [(0, text)]
    assert flags == {"step_label_unjudged"}


def test_a_link_with_no_later_mention_lifts_anyway_and_is_flagged():
    """⚠️ A HEADING ANDY HAS DECIDED ON IS NOT BLOCKED BY A LINK, which is his ruling. The link
    cannot be carried anywhere, so the lift happens and the loss is surfaced for re-linking rather
    than the heading being refused. Capitalized after the label, so this is about the link and not
    about the sentence gate."""
    shape, _, flags = _plan(["Wilt the [[spinach]]: Heat the oil and cook briefly."])
    # level 1: it is the recipe's first heading, so nothing opens a group above it (Andy's rule)
    assert shape == [(1, "Wilt the spinach"), (0, "Heat the oil and cook briefly.")]
    assert "step_label_link_lost" in flags


def test_the_link_id_is_never_touched_when_a_step_is_capitalized():
    """⚠️ LINKS RESOLVE BY THE ID INSIDE [[...]], not by the words — app.js openPanel fetches
    /api/ingredients/<key> with the key exactly as stored. Capitalizing a letter inside the markup
    would break the link silently, so a link with no label GAINS one instead."""
    assert ic.capitalize_first_visible("[[spinach]] wilts fast") == "[[spinach|Spinach]] wilts fast"
    assert ic.capitalize_first_visible("[[spinach|spinach]] wilts") == "[[spinach|Spinach]] wilts"
    assert ic.capitalize_first_visible("[[spinach|Spinach]] wilts") == "[[spinach|Spinach]] wilts"


@pytest.mark.parametrize("text, label", [
    ("30 min cool: Leave the fries to cool.", "30 min cool"),
    ("50 sec fry: Fry for 50 seconds.", "50 sec fry"),
    ("2 hr rest - Rest the dough.", "2 hr rest"),
])
def test_a_number_led_label_is_a_label_when_the_number_is_a_duration(text, label):
    """french-fries writes "30 min cool:", a stage like any other, missed only because the pattern
    demanded a capital letter."""
    got = ic.split_lead_label(text)
    assert not isinstance(got, str), got
    assert got[0] == label


@pytest.mark.parametrize("text", [
    "1 cup: of flour goes in next",
    "2 tbsp - olive oil",
    "250 g: plain flour",
])
def test_an_ingredient_amount_is_not_a_label(text):
    """⚠️ THE GUARD THAT MAKES RULE 4 SAFE. A leading number is a label only when a TIME unit
    follows it. An amount names a quantity, and lifting one would make a heading out of "1 cup"."""
    assert ic.split_lead_label(text) == "an ingredient amount, not a label"


# ⚠️ THE LEVEL TAKES THE RECIPE INTO ACCOUNT NOW, NOT THE LABEL ALONE (Andy's rule). A lifted label
# is a subheading only when a section heading already opens a group above it; with nothing above it
# there is no group to belong to, so it opens one itself. A label that NAMES A COMPONENT is a section
# either way.
@pytest.mark.parametrize("label, level", [
    ("To make the chocolate icing", 1),
    ("If using dried chickpeas", 1),
    ("For the dough", 1),
    ("For same day baking", 1),
    ("Make the marinade", 1),
    ("While the dough rests, make the filling", 1),
    ("Deseed", 1),
    ("Simmer", 1),
    ("30 min cool", 1),
])
def test_a_label_with_nothing_above_it_opens_a_section(label, level):
    assert ic.label_level(label) == level


def test_sibling_alternatives_directly_under_a_section_become_subheadings():
    """brioche-bread: "Shaping options" then "Option 1:" and "Option 2:", each with its own step.
    They are two ways of doing the one thing the section names."""
    shape, _, flags = _plan([
        "Shaping options:", "Option 1:", "Divide into 8 pieces.",
        "Option 2:", "Divide into 3 pieces.", "Let the dough rise.", "Baking:", "Preheat the oven."])
    assert shape == [
        (1, "Shaping options:"),
        (2, "Option 1:"), (0, "Divide into 8 pieces."),
        (2, "Option 2:"), (0, "Divide into 3 pieces."),
        (0, "Let the dough rise."),
        (1, "Baking:"), (0, "Preheat the oven."),
    ]
    assert "step_alternatives" in flags


def test_alternatives_that_are_not_directly_under_a_section_are_only_flagged():
    """⚠️ "DIRECTLY UNDER" IS THE WHOLE CONDITION. the-best-new-york-style-bagel puts "For Same Day
    Baking" seven steps below the heading above it: those are phases of the recipe, not two ways of
    mixing the dough, and demoting them would say the opposite. Where the shared steps resume is a
    judgement about the recipe, so it is flagged for a person."""
    rows = [
        {"is_heading": 1, "heading_level": 1, "text": "To mix the dough:"},
        {"is_heading": 0, "heading_level": 1, "text": "Add dry ingredients."},
        {"is_heading": 0, "heading_level": 1, "text": "Knead it."},
        {"is_heading": 1, "heading_level": 1, "text": "For same day baking"},
        {"is_heading": 0, "heading_level": 1, "text": "Cover with wrap."},
        {"is_heading": 1, "heading_level": 1, "text": "For next day baking"},
        {"is_heading": 0, "heading_level": 1, "text": "Into the fridge."},
    ]
    out, notes = ic.group_alternatives(rows)
    assert [r["heading_level"] for r in out if r["is_heading"]] == [1, 1, 1], "nothing demoted"
    assert [n["flag"] for n in notes] == ["step_alternatives"]
    assert "not under a section" in notes[0]["detail"]


def test_positions_are_the_index_in_the_heading_inclusive_list():
    """The same rule write_recipe_rows uses, so an imported recipe and a saved one number alike."""
    rows, _, _ = ic.plan_step_rows(["Deseed – Trim the stems.", "Simmer it."])
    assert [r["position"] for r in rows] == [0, 1, 2]


def test_every_conversion_says_which_row_and_what_it_did():
    """The review queue is the undo path, so a conversion with no position and no detail is a
    conversion the owner cannot find."""
    _, _, _ = _plan(["Deseed – Trim the stems."])
    rows, _, conv = ic.plan_step_rows(["**FOR THE SAUCE**", "Simmer – Reduce by half."])
    for c in conv:
        assert c["position"] is not None and c["reason"] and c["detail"]
    assert {c["flag"] for c in conv} == {"step_heading_unwrapped", "step_label_lifted",
                                         "step_heading_recased"}


# ================================================================================================ #
# NOTE KINDS and the notes data rule. The kind table is static/note-kinds.json, the SAME file
# static/note-blocks.js imports, so a label means one thing in the display and in the importer.
# ================================================================================================ #

def test_the_kind_table_is_the_file_the_client_reads():
    import json, pathlib
    on_disk = json.loads((pathlib.Path(__file__).resolve().parent.parent
                          / "static" / "note-kinds.json").read_text())["kinds"]
    assert ic.NOTE_KINDS == on_disk
    assert on_disk[0]["kind"] == "notes", "the first kind is the fallback"


@pytest.mark.parametrize("para, kind", [
    ("Note: some text", "notes"),
    ("Notes: some text", "notes"),
    ("Cook's note: some text", "notes"),
    ("Cook’s note: some text", "notes"),          # a curly apostrophe
    ("Tip: some text", "tips"),
    ("Pro tip: some text", "tips"),
    ("Storing. some text", "storage"),                  # the period form, brioche-bread's shape
    ("To freeze: some text", "storage"),
    ("Variation: some text", "variations"),
    ("SAME DAY VERSION: some text", "variations"),      # bagel, shouted
    ("Blind Bake: some text", None),                    # a one-off topic label stays unlisted
    ("Tomato Bouillon: granules or cubes", None),
    ("Made with Vedant and Sophia.", None),             # a sentence, not a label
    ("Consider using vital wheat gluten.", None),
])
def test_note_kind(para, kind):
    assert ic.note_kind(para) == kind


def test_a_label_only_paragraph_is_removed():
    """"Note." on its own names nothing and renders as a heading over the next person's paragraph."""
    out, removed = ic.clean_notes("Note.\n\nNote: Some legumes need no soak.")
    assert out == "Note: Some legumes need no soak."
    assert removed == [("label-only paragraph", "Note.")]


def test_a_label_only_fragment_glued_to_the_next_note_is_dropped():
    out, removed = ic.clean_notes("Note. Note: Some legumes need no soak.")
    assert out == "Note: Some legumes need no soak."
    assert removed == [("label-only fragment", "Note.")]


def test_an_unlisted_label_is_never_treated_as_a_fragment():
    """⚠️ THE GUARD THAT STOPS THIS DELETING A NOTE. "Made with Vedant and Sophia." is a whole
    sentence that happens to be short, and a rule that read any short phrase as a label would take
    the note with it."""
    for keep in ("Made with Vedant and Sophia.", "Blind Bake: Place a coffee filter in the shell."):
        assert ic.clean_notes(keep) == (keep, [])


def test_nothing_removed_means_nothing_written():
    """⚠️ COSMETIC WHITESPACE IS LEFT ALONE, and that is a decision this project already made once.
    Rejoining unconditionally also trims trailing whitespace, which changed 18 of the corpus's 95
    noted recipes and changed nothing a reader would see — the client trims for display."""
    for untouched in ("Keeps 3 days.\n", "a\n\n\n\nb", "  padded  ", ""):
        assert ic.clean_notes(untouched) == (untouched, [])


def test_a_moved_note_starts_its_own_paragraph():
    """Rule 3's third part, through the path that actually moves one.

    ⚠️ THE LABEL COMES WITH IT, and that is what the kind headers read. This asserted the stripped
    form while scripts/convert_step_headings.py kept the label, so the importer and the corpus pass
    classified the same paragraph under two different headers. A "Tip:" step imported tomorrow landed
    under Notes, and the label it needed to say otherwise had been deleted.
    """
    rows, notes, conv = ic.plan_step_rows(["Mix it.", "Note: Check the yeast."], "Keeps 3 days.")
    assert notes == "Keeps 3 days.\n\nNote: Check the yeast."
    assert ic.note_kind("Note: Check the yeast.") == "notes"
    assert [r["text"] for r in rows] == ["Mix it."]


def test_a_note_moved_onto_a_bare_label_cleans_up_after_itself():
    """⚠️ THE ORDER IS LOAD-BEARING. Moving a Note step is what can CREATE the shape clean_notes
    removes, so the notes rule runs after the moves rather than before them."""
    rows, notes, conv = ic.plan_step_rows(["Mix it.", "Note: Check the yeast."], "Note.")
    assert notes == "Note: Check the yeast."
    assert {c["flag"] for c in conv} == {"step_note_moved", "note_fragment_removed"}


def test_note_kind_agrees_with_the_client_on_every_case_in_the_shared_fixture():
    """The Python half of tests/js/note-kinds-sync.test.js.

    ⚠️ THE KIND TABLE WAS SHARED AND THE REGEX THAT READS THE LABEL WAS NOT. Six other
    cross-language mirrors in this project each have a sync test (factor-sync, fraction-sync,
    timefmt-sync, unit-abbrev-sync, step-ping-sync, save-payload-sync). This pair had none, and the
    two had already drifted from `_NOTE_STEP` on the separator set, so a "Tip - ..." step moved into
    the notes with its dash and neither side could read the label back.

    The fixture carries every label in the table in five separator forms and two casings, the shapes
    that must NOT classify, and every real notes paragraph in the corpus.
    """
    import json
    import pathlib

    cases = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures"
                        / "note-kind-cases.json").read_text())["cases"]
    assert len(cases) > 400, f"only {len(cases)} cases"
    labels = {l for k in ic.NOTE_KINDS for l in k["labels"]}
    covered = {c["text"].split(":")[0].split(".")[0].strip().lower() for c in cases}
    missing = [l for l in labels
               if not any(c["text"].lower().startswith(l.lower()) for c in cases)]
    assert missing == [], f"the fixture is stale, it does not cover {missing}"
    wrong = [(c["text"][:60], c["kind"], ic.note_kind(c["text"]))
             for c in cases if ic.note_kind(c["text"]) != c["kind"]]
    assert wrong == [], f"{len(wrong)} of {len(cases)} disagree with the recorded kind"


def test_a_dash_joined_kind_label_classifies_like_a_colon_joined_one():
    """⚠️ _NOTE_STEP ACCEPTS FIVE SEPARATORS AND _NOTE_LEAD ACCEPTED TWO, so a note moved out of the
    method kept a separator the classifier could not read. Two real corpus paragraphs were printing
    under the wrong header because of it."""
    assert ic.note_kind("Leftovers – Best to pan fry fresh so they are crispy.") == "storage"
    assert ic.note_kind("VARIATION - For pita pockets, use a rolling pin.") == "variations"
    assert ic.note_kind("Tip - a wetter dough gives a chewier crumb.") == "tips"
    # and widening the separator must not start classifying ordinary prose
    assert ic.note_kind("Serve with rice - or with bread.") is None
    assert ic.note_kind("Flour - 500g of it.") is None


def test_the_lead_pattern_agrees_with_the_client_case_by_case():
    """The Python half of tests/js/note-lead-sync.test.js.

    ⚠️ THE KIND SYNC TEST CANNOT SEE THIS. It compares the kind each side answers, and a label the
    table does not list answers "no kind" on both sides whether the pattern matched or not. So both
    halves reading ASCII only was invisible to it: "Café: use a dark roast" matched nothing in
    either language and every test passed.

    Regenerate the fixture with scripts/gen_note_lead_cases.py."""
    import json
    import pathlib

    cases = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures"
                        / "note-lead-cases.json").read_text())["cases"]
    wrong = []
    for c in cases:
        m = ic._NOTE_LEAD.match(c["text"])
        got = (m.group(1), m.group(2)) if m else (None, None)
        if got != (c["label"], c["body"]):
            wrong.append((c["text"][:48], c["label"], got[0]))
    assert wrong == [], f"{len(wrong)} of {len(cases)} disagree with the recorded label"


def test_a_label_may_be_written_in_any_script():
    """⚠️ [A-Za-z] WAS THE WHOLE RULE AND IT IS NOT WHAT A LETTER IS. The é fails the inner class,
    the match stops there, and the paragraph is prose. The corpus carries no such label, so this was
    found by reading the pattern rather than by running it over the 177."""
    assert ic.note_lead("Caf\u00e9: use a dark roast.") == ("Caf\u00e9", "use a dark roast.")
    assert ic.note_lead("Cr\u00e8me fra\u00eeche: stir it in off the heat.") == (
        "Cr\u00e8me fra\u00eeche", "stir it in off the heat.")
    assert ic.note_lead("Jalape\u00f1o \u2013 take the seeds out.") == (
        "Jalape\u00f1o", "take the seeds out.")
    assert ic.note_lead("\u03a1\u03af\u03b3\u03b1\u03bd\u03b7: dried on the stalk.") == (
        "\u03a1\u03af\u03b3\u03b1\u03bd\u03b7", "dried on the stalk.")
    assert ic.note_lead("\u0411\u043e\u0440\u0449: serve it with sour cream.") == (
        "\u0411\u043e\u0440\u0449", "serve it with sour cream.")
    # a digit and an underscore are still not letters, so neither opens a label
    assert ic.note_lead("500g: that is the flour.") is None
    assert ic.note_lead("_private: not a letter.") is None


def test_the_look_alike_repair_still_declines_a_real_other_script():
    """⚠️ THE TWO RULES PULL IN OPPOSITE DIRECTIONS AND BOTH ARE RIGHT. normalize_lookalikes
    rewrites "\u041c\u0410\u041a\u0415 THE CHICKEN" because every non-Latin letter in it has a
    Latin twin, and it leaves \u0411\u043e\u0440\u0449 and \u03a1\u03af\u03b3\u03b1\u03bd\u03b7
    alone because \u0449, \u03b3 and \u03b7 have none. Widening the label class is what lets a real
    Cyrillic or Greek label be READ as a label, instead of being turned into mojibake first."""
    for text in ["\u0411\u043e\u0440\u0449: serve it with sour cream and dill.",
                 "\u03a1\u03af\u03b3\u03b1\u03bd\u03b7: the Greek kind is dried on the stalk."]:
        assert ic.normalize_lookalikes(text) == text
    # and the one corpus row the repair exists for is still repaired
    assert ic.normalize_lookalikes("\u041c\u0410\u041a\u0415 THE CHICKEN:") == "MAKE THE CHICKEN:"


# ---- the label refusals (review fix 4) -----------------------------------------------------------
# ⚠️ MEASURED AGAINST THE REVIEWED CORPUS IN BOTH DIRECTIONS. A person approved 104 lead-in labels
# over the 300 recipes and declined 12. With no decisions in hand the importer lifted 122 of them, so
# 18 of its lifts were rows a person had already said no to. The rules below refuse 0 of the 104 and
# 6 of the 12. The rows they cannot reach are named in label_refusal's docstring and still lift with
# a step_label_lifted flag, which is the review queue.

@pytest.mark.parametrize("label, fragment", [
    # brownies, the sentence split that started this: the step is "Pour the batter into the prepared
    # pan (it'll be thick - that's ok) and use a spatula to smooth the top."
    ("Pour the batter into the prepared pan (it'll be thick", "bracket is left open"),
    ("Warm milk up in a saucepan (optional", "bracket is left open"),           # meat-lasagna
    ("Take the dough [the cold half", "bracket is left open"),
    # roasted-cauliflower, and hummus-2's dash row, which a person declined as "a sentence, not a label"
    ("While this cool, pre-heat your oven as hot as it goes", "comma joins two clauses"),
    ("Taste, and adjust as necessary", "comma joins two clauses"),
    ("Then velvet the beef", "continues the step before it"),                   # pepper-steak
    ("Meanwhile make the sauce", "continues the step before it"),
    ("Line a large bowl with paper towels", "is a clause"),                     # french-fries, 7 words
    ("Remove from heat and let it rest for 10 minutes", "is a clause"),         # mejadra, 10 words
])
def test_a_label_a_rule_can_read_as_a_clause_is_refused(label, fragment):
    why = ic.label_refusal(label)
    assert why is not None, f"{label!r} was accepted as a title"
    assert fragment in why, why


@pytest.mark.parametrize("label", [
    "Fry the chicken (the first time)",   # 6 words, the longest a person approved, and balanced
    "Birria Adobo (paste)",
    "To make the chocolate icing",
    "If using dried chickpeas",
    "Slow cook 2 1/2 hours",
    "Finish with COLD butter",
    "Keep warm", "Deseed", "To serve", "Wilt the spinach", "Fry #2",
    "Rest 10 minutes", "Simmer 30 min", "OVERNIGHT SOAK", "On the stovetop",
])
def test_a_label_a_person_approved_is_not_refused(label):
    assert ic.label_refusal(label) is None


def test_no_approved_corpus_label_is_refused():
    """⚠️ THE WHOLE REVIEWED SET, NOT A SAMPLE. These rules run for the corpus pass too (the reviewed
    label goes through the same function), so a rule that refused even one of them would silently
    drop a heading a person had already approved and the gate would move."""
    import csv
    approved = []
    repairs = pathlib.Path(ic.__file__).resolve().parent / "docs" / "data-repairs"
    for name in ("step-leadin-labels-2026-09-30.csv", "step-dash-labels-2026-09-30.csv"):
        path = repairs / name
        with path.open(newline="", encoding="utf-8") as f:
            approved += [r["label"] for r in csv.DictReader(f)
                         if r["DECISION_make_heading_yes_no"] == "yes"]
    assert len(approved) == 104, f"the reviewed set changed size: {len(approved)}"
    refused = [(l, ic.label_refusal(l)) for l in approved if ic.label_refusal(l)]
    assert refused == [], refused


def test_the_longest_approved_label_sets_the_ceiling():
    """The ceiling is the corpus maximum rather than a round number, so it is stated as one."""
    assert ic.MAX_LABEL_WORDS == 6


# ---- the refusal reaches BOTH callers ------------------------------------------------------------

def test_split_lead_label_refuses_a_detected_clause_with_a_readable_reason():
    got = ic.split_lead_label("Then velvet the beef: in a medium bowl, mix the beef with water.")
    assert isinstance(got, str)
    assert got.startswith(ic.LABEL_DECLINED), got
    assert "Then" in got


def test_split_lead_label_refuses_an_APPROVED_label_that_trips_a_rule():
    """⚠️ A STALE DECISION LOSES TO THE RULE. The corpus pass passes the label a person approved, and
    'is this a title or a clause' is the same question either way. A CSV row that has gone stale must
    not override the rule, or the two callers are back to deciding separately."""
    text = "Remove from heat and let it rest for 10 minutes - during this time liquid absorbs."
    got = ic.split_lead_label(text, label="Remove from heat and let it rest for 10 minutes")
    assert isinstance(got, str) and got.startswith(ic.LABEL_DECLINED), got


def test_a_refused_label_leaves_the_step_whole_and_flags_it():
    """FLAG, DON'T LIFT. The step keeps its words and the candidate reaches the review queue, so a
    person can disagree with the rule."""
    rows, _, conv = ic.plan_step_rows(
        ["Then velvet the beef: in a medium bowl, mix the beef with water and cornstarch."])
    assert [(r["is_heading"], r["text"]) for r in rows] == \
           [(0, "Then velvet the beef: in a medium bowl, mix the beef with water and cornstarch.")]
    flags = [c["flag"] for c in conv]
    assert flags == ["step_label_declined"], conv
    assert "continues the step before it" in conv[0]["detail"]


def test_an_ordinary_step_with_no_label_is_not_flagged():
    """The flag would be noise on every step in every recipe if it fired for 'no lead-in label'."""
    _rows, _notes, conv = ic.plan_step_rows(["Heat the oil in a large pan over medium heat."])
    assert conv == []


def test_the_declined_flag_is_a_step_structure_flag():
    """⚠️ import_flags HAS ONE position COLUMN and it means a different thing on a step flag. A new
    step flag missing from this set would have its STEP index read as an INGREDIENT line index and
    mark an unrelated row."""
    assert "step_label_declined" in ic.STEP_STRUCTURE_FLAGS
    assert "step_label_declined" in ic.STEP_STRUCTURE_REASONS


# ---- a label no rule can judge is flagged, not lifted (Andy's decision 4) -------------------------
# ⚠️ THE ONE SIGNAL THE CORPUS ACTUALLY SHOWS. Of the 104 lead-in labels a person approved, 99 are
# followed by a capital letter. All three of the rows a person declined as instructions or as a
# sentence are followed by a lowercase word or a digit, which is how a reader can tell the author
# wrote ONE sentence with a colon in the middle. By every other measure "Salt lightly" is "Keep warm"
# and "Set up three mixing bowls" is "Make the toasted rice powder".
#
# It is a FLAG and not a refusal, because 5 of the 104 are ALSO followed by a lowercase word. It can
# only say that nothing here decides. And it runs ONLY where nobody has judged: a reviewed label
# keeps its decision, so the corpus pass still lifts all 104 and the corpus result does not move.

@pytest.mark.parametrize("text, label", [
    # the three Andy named, in their real wording
    ("Salt lightly - this is mainly to draw excess liquid out. We don't squeeze every drop.",
     "Salt lightly"),
    ("Do a window pane test: take a small walnut sized piece of dough and stretch it thinly.",
     "Do a window pane test"),
    ("Set up three mixing bowls: 1) one with the remaining 1 cup flour, 2) one with the panko.",
     "Set up three mixing bowls"),
    # and their kind
    ("Rest the dough: it will relax while the oven heats.", "Rest the dough"),
    ("Toast the nuts - they burn fast, so watch them.", "Toast the nuts"),
])
def test_a_label_nothing_can_judge_is_flagged_and_the_step_stays_whole(text, label):
    got = ic.split_lead_label(text)
    assert isinstance(got, str), f"{label!r} was lifted"
    assert got.startswith(ic.LABEL_UNJUDGED), got
    rows, _notes, conv = ic.plan_step_rows([text])
    assert [(r["is_heading"], r["text"]) for r in rows] == [(0, text)], "the step was split"
    assert [c["flag"] for c in conv] == ["step_label_unjudged"], conv


@pytest.mark.parametrize("text", [
    "Deseed: Trim the stems and shake out the seeds.",
    "Keep warm: Put it in a low oven until the rest is ready.",
    "Make the flour dredge: Whisk the flour and the spices together.",
    "To make the chocolate icing: Melt the chocolate over a bain-marie.",
    "Rest 10 minutes: Let it sit before slicing.",
])
def test_a_label_followed_by_a_new_sentence_still_lifts(text):
    got = ic.split_lead_label(text)
    assert not isinstance(got, str), got


def test_a_reviewed_label_keeps_its_decision_and_the_gate_does_not_run():
    """⚠️ THE HALF THAT KEEPS THE CORPUS WHERE IT IS. 5 of the 104 approved labels are followed by a
    lowercase word — bulgogi-bowls' three, butter-chicken's "Optional blitz" and jamaican-jerk-fish's
    "Flip". A person judged each of them. The gate runs only on the auto-detect path, so the corpus
    pass lifts all 104 exactly as before, and only the importer declines to guess."""
    text = ("Wilt the spinach: heat 2 tsp oil in a large non-stick pan over high heat. "
            "Add half the spinach.")
    assert isinstance(ic.split_lead_label(text), str), "auto-detect should decline this one"
    got = ic.split_lead_label(text, label="Wilt the spinach")
    assert not isinstance(got, str), got
    assert got[0] == "Wilt the spinach"


def test_the_hard_refusal_still_wins_over_the_gate():
    """A reviewed label that trips a RULE is still refused — the gate is the weaker of the two and
    does not reorder them."""
    text = "Remove from heat and let it rest for 10 minutes - during this time liquid absorbs."
    got = ic.split_lead_label(text, label="Remove from heat and let it rest for 10 minutes")
    assert isinstance(got, str) and got.startswith(ic.LABEL_DECLINED), got


def test_the_unjudged_flag_is_a_step_structure_flag():
    assert "step_label_unjudged" in ic.STEP_STRUCTURE_FLAGS
    assert "step_label_unjudged" in ic.STEP_STRUCTURE_REASONS


def test_the_two_kinds_of_no_are_different_flags():
    """They mean different things to a reviewer: one says this is not a title, the other says this
    might be and nothing here can tell. The action differs, so the flag does."""
    declined = ic.plan_step_rows(["Then velvet the beef: in a bowl, mix the beef with water."])[2]
    unjudged = ic.plan_step_rows(["Salt lightly - this draws the liquid out."])[2]
    assert [c["flag"] for c in declined] == ["step_label_declined"]
    assert [c["flag"] for c in unjudged] == ["step_label_unjudged"]


@pytest.mark.parametrize("label", ["Deseed", "Simmer", "Assembly", "Fry the chicken"])
def test_a_label_under_a_section_heading_is_a_subheading(label):
    """The other half of Andy's rule: a group is open above it, so the label belongs to that group.

    ⚠️ "30 min cool" WAS IN THIS LIST AND ANDY REVERSED IT ON 2026-10-08. It names a duration, so it
    is a stage of the recipe rather than a caption on the stage above it, and names_a_stage now
    promotes it. The case is kept, in test_a_label_that_names_a_stage_is_a_section_whatever_sits_above_it
    below, asserting the opposite answer. A reversed decision is moved, not deleted."""
    assert ic.label_level(label, section_above=True) == 2


@pytest.mark.parametrize("label,why", [
    ("30 min cool", "names a duration"),
    ("50 sec fry", "names a duration"),
    ("Dry 5 min", "names a duration"),
    ("Slow cook 2 1/2 hours", "names a duration"),
    ("Fry #2", "names a numbered stage"),
    ("Batch 2", "names a numbered stage"),
])
def test_a_label_that_names_a_stage_is_a_section_whatever_sits_above_it(label, why):
    """⚠️ ANDY'S CALL AFTER THE 2026-10-08 CLICK-THROUGH, on french-fries. Its author wrote "Fry #1"
    as a section and the lifted "50 sec fry", "30 min cool" and "Fry #2" sat under it as captions.
    They are the next three things that happen, not notes on the first fry."""
    assert ic.names_a_stage(label).startswith(why)
    assert ic.label_level(label, section_above=True) == ic.SECTION
    assert ic.label_level(label, section_above=False) == ic.SECTION


@pytest.mark.parametrize("label", ["Option 1:", "Option 2", "Method 2", "Version 1",
                                   "Variation 2"])
def test_an_alternative_carries_a_counter_and_is_still_not_a_stage(label):
    """⚠️ THE ONE SHAPE THE COUNTER HALF MUST NOT CLAIM. brioche-bread's "Option 1:" and "Option 2:"
    are siblings UNDER a heading, not stages of one sequence, and Andy confirmed in the preview that
    they stay subheadings. Without the _ALTERNATIVE check first, the trailing number promotes both."""
    assert ic.names_a_stage(label) is None
    assert ic.label_level(label, section_above=True) == ic.SUBHEADING


@pytest.mark.parametrize("label", ["3 L water", "2 cups flour", "Assembly", "Marinade",
                                   "Tomatoes"])
def test_a_label_with_no_stage_in_it_is_not_promoted(label):
    """A measure is not a duration and a plain caption carries no counter. "3 L water" is the one
    that matters: the counter half reads a word then a number, and a one-letter unit is not a word,
    which is what the three-letter minimum is for."""
    assert ic.names_a_stage(label) is None


@pytest.mark.parametrize("label", ["To make the chocolate icing", "For the dough",
                                   "If using dried chickpeas", "Make the marinade",
                                   "While the dough rests, make the filling"])
def test_a_label_that_names_a_component_is_a_section_whatever_sits_above_it(label):
    """⚠️ A COMPONENT IS A PART OF THE RECIPE, NOT A CAPTION ON A STEP. "Make the chicken" under a
    "Marinade" section opens its own part, which is the case Andy's click-through turned up."""
    assert ic.label_level(label, section_above=True) == 1
    assert ic.label_level(label, section_above=False) == 1
