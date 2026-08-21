"""Phase 15 — import cleanup core (import_cleanup).

Tests the PARSE-vs-FLAG boundaries, because a wrong STRUCTURE silently corrupts imported
recipes: the failure mode must be "flagged a line," never "structured it wrong." Heaviest
emphasis on the decline points — the grams confidence guard, section ambiguity, the risky
multiplier/each patterns, and the servings traps."""
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


def test_count_word_stays_in_name():
    # counts (cloves) are NOT measure units — they stay in the name (Confirmation 3)
    d = ic.classify_line("3 Garlic Cloves, peeled")
    assert d["value"] == 3.0 and d["unit"] == "" and d["name"].startswith("Garlic Cloves")


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
    d = ic.classify_line("1 cup plus 2 tablespoons (270g) tahini (light roast)")
    assert d["grams_harvested"] == 270.0
    assert d["name"] == "plus 2 tablespoons tahini (light roast)"


# ----------------------------------------------------------------- dual-unit secondary measure
def test_dual_unit_secondary_measure_stripped_from_name():
    # "2 teaspoons / 6 g active dry yeast": keep the primary qty, drop the "/ 6 g" from the label
    d = ic.classify_line("2 teaspoons / 6 g active dry yeast")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"]) == ("2", "teaspoons")
    assert d["name"] == "active dry yeast"               # label is now the clean ingredient name
    assert d["secondary_measure"] == "/ 6 g"
    assert d["raw"] == "2 teaspoons / 6 g active dry yeast"   # raw_text kept intact


def test_dual_unit_metric_weight_stripped_keeps_alternative():
    d = ic.classify_line("3 ½ cups / 440 g bread flour or high gluten flour")
    assert d["name"] == "bread flour or high gluten flour"
    assert d["secondary_measure"] == "/ 440 g"
    assert d["has_alternative"] is True                  # "or" still detected on the clean name


def test_dual_unit_only_leading_secondary_stripped():
    # a "/60 ml" later in a note must NOT be touched — only the leading secondary measure goes
    d = ic.classify_line("1 ¼ cups / 300 ml warm water (you may need ± ¼ cup /60 ml more)")
    assert d["name"].startswith("warm water")
    assert "/60 ml" in d["name"]
    assert d["secondary_measure"] == "/ 300 ml"


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
    # volume-first: gram harvested from the paren (as before) + the leading volume captured
    d = ic.classify_line("1 cup (250g) flour")
    assert d["name"] == "flour"
    assert d["grams_harvested"] == 250.0
    assert d["secondary_measure"] == "1 cup"


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
    assert ic.CLEANUP_REASONS == {f: r for f, _p, _rp, r in ic.CLEANUP_RULES}


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
    ("1 large bundle kale (loosely chopped or torn)", "large bundle kale (loosely chopped or torn)"),
])
def test_paren_with_no_weight_is_untouched(line, name):
    d = ic.classify_line(line)
    assert d["grams_harvested"] is None
    assert d["name"] == name
    assert "grams_declined" not in d["flags"]


def test_measure_list_leaves_the_name_alone():
    """The volume STAYS in the name for now (moving it is a later stage), so the harvest returns
    no gram_paren and _strip_gram_paren has nothing to remove."""
    line = "1 cup (16 Tbsp; 226g) unsalted butter, cut into 16 pieces"
    d = ic.classify_line(line)
    assert d["grams_harvested"] == 226.0
    assert d["name"] == "(16 Tbsp; 226g) unsalted butter, cut into 16 pieces"
    assert d["raw"] == line
    assert ic.harvest_grams(line)[2] is None            # no paren handed to the name-stripper


@pytest.mark.parametrize("line, grams, name, secondary", [
    # The ALREADY-WORKING single-measure forms, pinned: the new path must not change any of them.
    ("(250g) dried chickpeas", 250.0, "(250g) dried chickpeas", None),
    ("14 cups (250g) dried chickpeas", 250.0, "dried chickpeas", "14 cups"),
    ("1 cup (250 g) flour", 250.0, "flour", "1 cup"),
    ("100 g (1 cup) granulated sugar", 100.0, "granulated sugar", "1 cup"),
    ("1 cup plus 2 tablespoons (270g) tahini (light roast)", 270.0,
     "plus 2 tablespoons tahini (light roast)", "1 cup"),
])
def test_single_measure_gram_paren_forms_unchanged(line, grams, name, secondary):
    d = ic.classify_line(line)
    assert d["grams_harvested"] == grams
    assert d["name"] == name
    assert d["secondary_measure"] == secondary
