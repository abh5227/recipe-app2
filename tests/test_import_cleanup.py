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
        name="X", uid="u", hash="h", ingredient_lines=[], directions="",
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


def test_for_the_dough_flagged_suggest_section():
    d = ic.classify_line("For the dough")
    assert d["kind"] == "flagged" and d["suggestion"] == "section"
    assert "ambiguous_section" in d["flags"]


def test_no_amount_flagged_suggest_ingredient():
    d = ic.classify_line("Extra-virgin olive oil")
    assert d["kind"] == "flagged" and d["suggestion"] == "ingredient"


def test_section_guard_amount_beats_colon_or_caps():
    # a line with a real amount is never a section, even with a colon or all-caps
    assert ic.classify_line("1 cup flour: sifted")["kind"] == "ingredient"
    assert ic.classify_line("2 EGGS")["kind"] == "ingredient"


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


# ----------------------------------------------------------------- multiplier N=1 vs N>1
def test_multiplier_one_resolved_no_flag():
    d = ic.classify_line("1 x 397 grams can of condensed milk")
    assert d["kind"] == "ingredient"
    assert (d["amount"], d["unit"], d["name"]) == ("1", "can", "condensed milk")
    assert d["grams_harvested"] == 397.0
    assert "multiplier" not in d["flags"]


def test_multiplier_two_still_flagged():
    d = ic.classify_line("2 x 6 oz halibut fillets")
    assert d["kind"] == "flagged" and "multiplier" in d["flags"]


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
    r = ic.clean_recipe(_norm(ingredient_lines=[], directions="1. mix"))
    assert "no_ingredients" in r["recipe_flags"] and "no_directions" not in r["recipe_flags"]


def test_no_directions_flagged_keeps_ingredients():
    r = ic.clean_recipe(_norm(ingredient_lines=["2 tbsp oil", "1 egg"], directions=""))
    assert "no_directions" in r["recipe_flags"]
    assert len(r["ingredients"]) == 2                     # nothing dropped


def test_photo_only_flagged():
    r = ic.clean_recipe(_norm(ingredient_lines=[], directions="", images=[{"bytes": 1}]))
    assert r["recipe_flags"] == ["no_ingredients", "no_directions", "photo_only"]


def test_nothing_dropped_sections_kept():
    r = ic.clean_recipe(_norm(ingredient_lines=["a", "b", "c", "SAUCE:"]))
    assert len(r["ingredients"]) == 4                     # every line preserved, incl. the section
