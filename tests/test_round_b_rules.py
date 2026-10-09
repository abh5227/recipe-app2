"""Round B's rules: the author's second amount, the units left in names, the broken amounts.

Every case here is a real corpus line unless it is marked as one the rule must NOT fire on. The
refusals are the half worth reading: a rule that only ever fires is a rule nobody has measured.
"""
import pytest

import import_cleanup as ic
import planahead as pa


def row(label, qty="", quantity=None, unit="", raw_text=None, secondary=None, grams=None,
        recipe_id="a-recipe", note=None):
    return {"recipe_id": recipe_id, "label": label, "raw_text": raw_text or label, "qty": qty,
            "quantity": quantity if quantity is not None else qty, "unit": unit,
            "secondary_measure": secondary, "grams": grams, "is_heading": 0, "note": note}


# --------------------------------------------------------------------------- #
# The widened duration reader
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, minutes", [
    ("2 1/2 hours", 150), ("1½ hours", 90), ("1 ½ hours", 90), ("¾ hour", 45),
    ("half an hour", 30), ("one hour", 60), ("two minutes", 2), ("3 1/2 hours", 210),
    ("45 minutes", 45), ("1 hr 30 min", 90),
])
def test_the_duration_reader_reads_every_shape_an_author_writes(text, minutes):
    assert pa.clock_minutes(text) == (minutes, minutes)
    assert pa.read_duration(text) == (minutes, minutes)


def test_a_mixed_number_range_keeps_both_ends():
    assert pa.read_duration("1 1/2 - 4 hours") == (90, 240)


def test_the_author_s_own_number_shape_is_written_back():
    """Reshaping "2 1/2 hr" into "2 hr 30 min" is the same invention as narrowing a range."""
    assert ic.normalize_time("2 1/2 hours") == "2 1/2 hr"
    assert ic.normalize_time("1½ hours") == "1½ hr"
    assert ic.normalize_time("half an hour") == "½ hr"       # a word has no numeral of its own
    assert ic.normalize_time("one hour") == "1 hr"


def test_every_duration_the_reader_writes_reads_back_as_itself():
    for text in ("2 1/2 hours", "1½ hours", "¾ hour", "half an hour", "one hour",
                 "1 1/2 - 4 hours", "35 min (plus one hour resting)"):
        once = ic.normalize_time(text)
        assert ic.normalize_time(once) == once


# --------------------------------------------------------------------------- #
# What a fragment IS
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, after, verdict", [
    ("250g", "", ic.FRAGMENT_ALTERNATE),
    ("8 tablespoons/113 grams", "", ic.FRAGMENT_ALTERNATE),
    ("about 1 ¼ cups", "", ic.FRAGMENT_ALTERNATE),
    ("about 2 cloves", "", ic.FRAGMENT_COUNT),
    ("2 large semi-ripe bananas", "", ic.FRAGMENT_COUNT),
    ("about 1 bunch", "", ic.FRAGMENT_COUNT),
    ("9\"", " pie crusts", ic.FRAGMENT_PACKAGE),
    ("14-ounce can", " tomatoes", ic.FRAGMENT_PACKAGE),
    ("½ pound each", "", ic.FRAGMENT_PER_ITEM),
    ("light roast", "", ic.FRAGMENT_PROSE),
    ("~4 pieces, heaped 3/4 cup once chopped", "", ic.FRAGMENT_PROSE),
])
def test_classify_fragment(text, after, verdict):
    assert ic.classify_fragment(text, after=after)[0] == verdict


@pytest.mark.parametrize("text", [
    "from about 1 lime",       # a source, not a count of this line's food
    "4 large, 5 medium",       # a list of two answers
    "16-20 per lb",            # a grade
    "1 if large",              # a note
    "or to taste",             # no count at all
    "or apple cider vinegar",  # an alternative ingredient with no count
    "or 1 tsp ground cumin",   # an alternative carrying its own unit of measure
])
def test_a_count_restatement_refuses_what_only_looks_like_a_count(text):
    assert ic.count_restatement(text) == ""
    assert ic.classify_fragment(text)[0] == ic.FRAGMENT_PROSE


# ⚠️ "or 2 small cloves" WAS ON THE LIST ABOVE AND ANDY'S R2 TOOK IT OFF. Decision 5 refused every
#    fragment carrying an "or" on the grounds that it offers a different ingredient. The
#    click-through's ruling is that an "or" COUNT of the same food is a second amount, keeping the
#    "or", and the test that held the old answer is this one rather than a deletion.
@pytest.mark.parametrize("frag, context, stored", [
    ("or 2 small cloves", "1 large clove garlic, minced ", "or 2 small cloves"),
    ("or 2 small ones", "1 large skin-on chicken breast ", "or 2 small"),
    ("or 6-8 cilantro stems", "3-4 cilantro roots ", "or 6\u20138 stems"),
    ("or 1 large onion", "2 small onions , finely diced", "or 1 large"),
    ("4 medium or 2 long cucumbers", "500 g / 1 lb cucumbers ", "4 medium or 2 long"),
])
def test_an_or_count_of_the_same_food_is_a_second_amount(frag, context, stored):
    assert ic.count_restatement(frag, context)
    assert ic.count_parts(frag, context)["count"] == stored


@pytest.mark.parametrize("line, stored", [
    ("3-4 cilantro roots or 6-8 cilantro stems", "or 6\u20138 stems"),
    ("2 small onions or 1 large onion, finely diced", "or 1 large"),
    ("1 large skin-on chicken breast (or 2 small ones)", "or 2 small"),
])
def test_a_bare_or_outside_brackets_is_read_too(line, stored):
    assert ic.author_second_amount(line)[0] == stored


# ⚠️ AND A COUNT THAT NAMES A FOOD THE ROW DOES NOT IS REFUSED, which is what keeps R2 from
#    swallowing an alternative INGREDIENT that happens to carry a bare count. Both of these leave
#    a word the name never had, and both go to the review list with nothing moved.
@pytest.mark.parametrize("name, raw", [
    ("tomato sauce, or 2 pureed tomatoes", "1/4 cup tomato sauce, or 2 pureed tomatoes"),
    ("Persian cucumber or \u00bd English cucumber, deseeded",
     "1 Persian cucumber or \u00bd English cucumber, deseeded"),
])
def test_a_count_naming_another_food_is_refused_and_noted(name, raw):
    plan = ic.amount_plan(row(name, qty="1", quantity="1", raw_text=raw))
    assert plan["changes"].get("secondary_measure") is None
    assert any(f == ic.COUNT_NAMES_ANOTHER_FOOD_FLAG for f, _r in plan["notes"])


# --------------------------------------------------------------------------- #
# The front of the name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("r, rule, qty, name_after", [
    (row("pint fresh medium blueberries", qty="1"), "stranded_unit", "1 pint",
     "fresh medium blueberries"),
    (row("quarts water", qty="3½"), "stranded_unit", "3½ quarts", "water"),
    (row("L water", qty="3"), "stranded_unit", "3 L", "water"),
    (row("Quart, Brodo (broth) or Stock", qty="1"), "stranded_unit", "1 Quart",
     "Brodo (broth) or Stock"),
    (row("quarts of water", qty="4"), "stranded_unit", "4 quarts", "water"),
    (row("+ 2 tablespoons ghee or olive oil, divided", qty="¼ cup", unit="cup"),
     "compound_amount", "¼ cup + 2 tablespoons", "ghee or olive oil, divided"),
    (row("Two 16-ounce cans cannellini beans, drained"), "number_word", "2",
     "16-ounce cans cannellini beans, drained"),
    (row("Scant ½ cup extra-virgin olive oil"), "leading_measure", "scant ½ cup",
     "extra-virgin olive oil"),
    (row("up to 2 cups of milk"), "leading_measure", "up to 2 cups", "milk"),
    # ⚠️ THESE TWO USED TO ANSWER sized_piece AND a_an_sized_piece, AND R1 ANSWERS THEM THE OTHER
    #    WAY. The old rules put the size back into the name and left the row with no amount at
    #    all; Andy's click-through call is that a sized piece IS what the row measures in.
    (row("-inch knob ginger, finely chopped", qty="1"), "sized_piece_amount", "1-inch knob",
     "ginger, finely chopped"),
    (row(", Italian Imported Marsala Wine", qty="2 Cups", quantity="2", unit="Cups"),
     "leading_punctuation", "2 Cups", "Italian Imported Marsala Wine"),
    (row("of Olive Oil", qty="1/2 Cup", quantity="1/2", unit="Cup"), "word_the_unit_left",
     "1/2 Cup", "Olive Oil"),
    (row("a 2-inch piece of ginger (smashed)"), "sized_piece_amount", "2-inch piece",
     "ginger (smashed)"),
    # The arm R1 did NOT take: a size with no piece word after it, where the number goes back to
    # the words it sizes. chocolate-hazelnut-wedges' "-inch cubes" is the row that needs it.
    (row("-ounce pumpkin puree", qty="15", quantity="15"), "sized_piece", "",
     "15-ounce pumpkin puree"),
    (row("a Lemon", qty="1/2"), "article_after_amount", "1/2", "Lemon"),
])
def test_the_front_of_the_name(r, rule, qty, name_after):
    front = ic.front_of_name(r)
    assert front is not None and front["rule"] == rule
    plan = ic.amount_plan(r)
    assert plan["changes"].get("qty", r["qty"]) == (qty or None if "qty" in plan["changes"] else qty)
    assert plan["changes"].get("label", r["label"]) == name_after


@pytest.mark.parametrize("r", [
    row("a pinch of salt"),                       # decision 7: the four phrases stay
    row("a handful fresh coriander"),
    row("a few bay leaves"),
    row("a package of basil"),
    row("salt and pepper, to taste"),             # never split, never read as an amount
    row("five spice powder"),                     # a compound name, not five of a powder
    row("half-and-half"),
    row("small onion, diced"),                    # the bare "l" must not reach "small"
    row("oil, for frying"),                       # or "oil"
    row("extra firm tofu (drained and pressed)", qty="16 oz", quantity="16", unit="oz"),
    row("2 (9\") pie crusts"),                    # a package size stays
])
def test_the_front_rules_refuse_what_they_must(r):
    assert ic.front_of_name(r) is None


def test_a_row_the_rules_cannot_read_is_left_exactly_as_it_is():
    r = row("stick ½ cup/113 grams) cold unsalted butter, cut into", qty="1")
    plan = ic.amount_plan(r)
    assert plan["changes"] == {}
    assert plan["flags"][0][0] == ic.UNBALANCED_BRACKET_FLAG


# --------------------------------------------------------------------------- #
# The author's second amount
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line, second", [
    ("1 cup (250 g) flour", "250 g"),
    ("2 cups/250g bread flour, plus more to dust", "250g"),
    ("1 stick (8 tablespoons/113 grams) unsalted butter", "8 tablespoons / 113 grams"),
    ("170 grams (6 ounces) chocolate, roughly chopped (about 1 cup)", "6 ounces / about 1 cup"),
    ("2 large bunches Swiss chard (24 ounces total), rinsed well", "24 ounces total"),
    ("1 tablespoon minced garlic (about 2 cloves)", "about 2 cloves"),
    ("2 tbsp olive oil", ""),
    ("4 tilapia fillets (½ pound each)", ""),            # per item, so it is not the line's own
    ("2 (9\") pie crusts", ""),                          # a package size
    ("2 tbsp soy sauce (low sodium)", ""),               # prose
    ("4 Persian cucumbers, or 10 oz./350g (about 1) regular English cucumber", ""),
])
def test_the_second_amount_is_read_off_the_author_s_line(line, second):
    assert ic.author_second_amount(line)[0] == second


def test_a_slot_holding_a_copy_of_the_first_amount_is_rewritten():
    """130 live rows held their own first amount in the slot, which is no backup at all."""
    r = row("flour", qty="1 cup", quantity="1", unit="cup", raw_text="1 cup (250 g) flour",
            secondary="1 cup")
    assert ic.amount_plan(r)["changes"]["secondary_measure"] == "250 g"


def test_a_slot_holding_a_stray_slash_is_rewritten():
    r = row("parsley leaves, finely chopped", qty="3 tablespoons", quantity="3",
            unit="tablespoons", raw_text="3 tablespoons/10g parsley leaves, finely chopped",
            secondary="/10g")
    assert ic.amount_plan(r)["changes"]["secondary_measure"] == "10g"


# ⚠️ THIS TEST USED TO ASSERT THAT THE WHOLE FRAGMENT STAYED IN THE NAME, and R2 settles it the
#    other way: the food's own words come back and the count is the second amount. It is residual
#    row 2832, decided in round-b-residual-decisions-2026-10-08.csv, and no rule could reach it
#    until the count fragment was split into what measures and what names the food.
def test_a_count_carrying_the_food_s_own_name_gives_the_name_back():
    r = row("(2 large semi-ripe bananas) , peeled and roughly chopped", qty="300 grams",
            quantity="300", unit="grams",
            raw_text="300 grams (2 large semi-ripe bananas), peeled and roughly chopped "
                     "(about 1 \u00bc cups)")
    plan = ic.amount_plan(r)
    assert plan["changes"]["label"] == "semi-ripe bananas, peeled and roughly chopped"
    assert plan["changes"]["secondary_measure"] == "2 large / about 1 \u00bc cups"
    assert plan["changes"].get("qty") is None          # 300 grams is still the first amount
    assert not plan["flags"]


# A fragment that is NOT a count and still carries the food is left exactly where it is, which is
# the half of the old rule that stands.
def test_a_non_count_fragment_carrying_the_food_stays_in_the_name():
    r = row("(224 grams), plus more for dusting", qty="1\u00be cups", quantity="1\u00be",
            unit="cups", raw_text="1\u00be cups (224 grams), plus more for dusting")
    plan = ic.amount_plan(r)
    assert any(f == ic.FOOD_INSIDE_FRAGMENT_FLAG for f, _r in plan["notes"])


# --------------------------------------------------------------------------- #
# A broken amount, repaired only where one reading is proved
# --------------------------------------------------------------------------- #
def test_a_flattened_mixed_number_is_repaired_where_the_grams_prove_it():
    r = row("dried chickpeas", qty="14 cups", quantity="14", unit="cups",
            raw_text="14 cups (250g) dried chickpeas", grams=250.0)
    assert ic.amount_plan(r, 0.85)["changes"]["qty"] == "1¼ cups"


def test_a_fraction_that_lost_its_whole_part_is_repaired_where_the_grams_prove_it():
    r = row("packed light brown sugar", qty="1/3 cups", quantity="1/3", unit="cups",
            raw_text="1/3 cups (267 grams) packed light brown sugar", grams=267.0)
    assert ic.amount_plan(r, 0.85)["changes"]["qty"] == "1⅓ cups"


def test_a_unit_with_no_number_takes_the_count_the_other_measure_makes_it():
    r = row("stick (8 tablespoons/113 grams) unsalted butter, room temperature",
            raw_text="stick (8 tablespoons/113 grams) unsalted butter, room temperature")
    plan = ic.amount_plan(r)
    assert plan["changes"]["qty"] == "1 stick"
    assert plan["changes"]["label"] == "unsalted butter, room temperature"


@pytest.mark.parametrize("r", [
    # nothing on the line settles it
    row("/ cups all-purpose flour", qty="1", quantity="1", unit="",
        raw_text="1/ cups all-purpose flour"),
    # more than one reading fits
    row("spooned and leveled all-purpose flour", qty="3/4 cups", quantity="3/4", unit="cups",
        raw_text="3/4 cups spooned and leveled all-purpose flour (416 grams)", grams=416.0),
])
def test_a_broken_amount_no_measure_proves_is_flagged_and_left_alone(r):
    plan = ic.amount_plan(r, 0.53)
    # ⚠️ THE AMOUNT AND THE NAME BOTH STAY. Letting the name move re-opened the half-repair:
    #    "1/ cups all-purpose flour" lost its "/" on one run and the next read the name as opening
    #    with a stranded unit and wrote the amount "1 cups". Only the slot may move.
    assert set(plan["changes"]) <= {"secondary_measure"}
    assert plan["flags"][0][0] == ic.BROKEN_AMOUNT_FLAG


def test_a_repair_needs_a_clear_winner_and_not_merely_a_passing_one():
    """marble-bundt-cake reads 2⅔ at 9 percent off the flour density against 3⅔ at 34, which is a
    reading. lavender's "3/4 cups" reads 3¾ at 12 against 2¾ at 21, which is a coin toss, and the
    amount the grams point at, 3½, is not a reading of "3/4" at all."""
    clear = row("all-purpose flour", qty="2/3 cups", quantity="2/3", unit="cups",
                raw_text="2/3 cups (305 grams) all-purpose flour", grams=305.0)
    assert ic.amount_plan(clear, 0.53)["changes"]["qty"] == "2⅔ cups"
    toss = row("spooned and leveled all-purpose flour", qty="3/4 cups", quantity="3/4",
               unit="cups", raw_text="3/4 cups spooned and leveled all-purpose flour (416 grams)",
               grams=416.0)
    plan = ic.amount_plan(toss, 0.53)
    assert "qty" not in plan["changes"] and plan["flags"][0][0] == ic.BROKEN_AMOUNT_FLAG
    # the slot held a copy of that same "3/4 cups", which is no backup at all
    assert plan["changes"]["secondary_measure"] == "416 grams"


def test_the_proof_is_the_row_s_second_amount_even_where_the_slot_is_already_right():
    """⚠️ bananas-foster already stores "2 ¾ cups" correctly, so a repair that read only the
    CHANGE to the slot had nothing to measure "35 grams" against. It is a digit short of 350."""
    r = row("spooned and leveled all-purpose flour", qty="35 grams", quantity="35", unit="grams",
            raw_text="35 grams (2 ¾ cups) spooned and leveled all-purpose flour", grams=35.0,
            secondary="2 ¾ cups")
    assert ic.second_amount(r) is None            # the slot is already what the author wrote
    plan = ic.amount_plan(r, 0.54)
    assert plan["changes"] == {} and plan["flags"][0][0] == ic.BROKEN_AMOUNT_FLAG


def test_a_measure_that_is_the_first_amount_again_proves_nothing():
    """The grams column is a copy of the amount on that row, so it agreed with it perfectly and
    the gate concluded the amount was fine."""
    r = row("flour", qty="35 grams", quantity="35", unit="grams", raw_text="35 grams flour",
            grams=35.0)
    assert ic.amount_plan(r, 0.54)["flags"] == []     # nothing else on the line, so nothing is said


def test_an_ordinary_fraction_under_a_plural_unit_is_not_a_broken_amount():
    """⚠️ A fraction below one cannot really be plural, and authors write "3/4 teaspoons" anyway."""
    r = row("sea salt", qty="3/4 teaspoons", quantity="3/4", unit="teaspoons",
            raw_text="3/4 teaspoons sea salt")
    assert ic.amount_plan(r)["changes"] == {}
    assert ic.amount_plan(r)["flags"] == []


def test_an_ordinary_two_digit_amount_is_not_a_broken_amount():
    r = row("extra firm tofu", qty="16 oz", quantity="16", unit="oz",
            raw_text="16 oz extra firm tofu")
    assert ic.amount_plan(r)["changes"] == {}


# --------------------------------------------------------------------------- #
# The coherence check, which flags and never fixes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("first, second", [
    ("500 g", "1 lb"), ("2 lb", "1 kg"), ("600 g", "1.2lb"), ("220 g", "7oz"),
    ("250 g", "8 oz"), ("1.5 lb", "750 g"), ("226 grams", "8 ounces"),
])
def test_an_honest_metric_and_imperial_rounding_does_not_flag(first, second):
    assert ic.coherence(first, second)[0] is True


@pytest.mark.parametrize("name, first, second", [
    ("parsley leaves, finely chopped", "3 tablespoons", "10g"),
    ("mixed baby sprouts, herbs, and microgreens", "2 cups", "about 60g"),
    ("1-inch cubes sturdy white bread", "2 cups", "60 grams"),
    ("roughly chopped fresh cilantro", "¼ cup", "5g"),
])
def test_a_light_food_does_not_flag_for_being_light(name, first, second):
    assert ic.is_light_food(name) is True
    assert ic.coherence(first, second, light=True)[0] is True


@pytest.mark.parametrize("first, second, density", [
    ("700 g", "1.2 lb", None),            # the author's own figures disagree by 29 percent
    ("4 cups", "500ml", None),            # by 89
    ("1 tsp", "7g", 0.85),                # a teaspoon of sugar is 4 grams
    ("1 tablespoon", "20g", 0.90),        # a tablespoon of butter is 14
])
def test_a_pair_that_cannot_both_be_right_is_flagged(first, second, density):
    assert ic.coherence(first, second, density)[0] is False


def test_the_corpus_speaks_for_a_food_only_when_two_recipes_agree():
    """One row cannot vouch for itself, so a single odd pair still falls back to the band."""
    pairs = [("recipe-a", "parsley", "3 tablespoons", "10g"),
             ("recipe-b", "parsley", "3 tablespoons", "10g"),
             ("recipe-c", "saffron", "1 cup", "900 g")]
    index = ic.density_index(pairs)
    assert "parsley" in index and 0.20 < index["parsley"] < 0.26
    assert "saffron" not in index


# --------------------------------------------------------------------------- #
# A row that is half of one line
# --------------------------------------------------------------------------- #
def test_a_row_whose_line_above_ends_mid_phrase_joins_it():
    above = row("cold unsalted butter, cut into")
    assert "mid-phrase" in ic.joins_the_row_above(above, row("-inch cubes", qty="½"))


def test_a_row_that_is_only_a_measure_joins_the_row_above():
    above = row("spooned and leveled all-purpose flour", qty="2 cups")
    assert "measures the row above" in ic.joins_the_row_above(above, row("(224 grams)"))


def test_a_comma_joins_only_a_prep_clause_and_only_under_a_row_with_no_amount():
    """⚠️ vanilla-mug-cake writes every line of its list with a trailing comma, and reading that
    the way a connective is read merged five ingredients into one."""
    above = row("natural, unsweetened cocoa powder,", qty="¼ cup")
    assert "prep clause" in ic.joins_the_row_above(above, row("sifted"))
    # its own amount, so its own ingredient
    assert ic.joins_the_row_above(row("sugar,", qty="2 tablespoons"),
                                 row("baking powder,", qty="1/4 teaspoon")) == ""
    # no amount, and still a food of its own
    assert ic.joins_the_row_above(row("baking powder,", qty="1/4 teaspoon"),
                                 row("dash salt")) == ""


@pytest.mark.parametrize("above, this", [
    (row("kosher salt", qty="1 tsp"), row("black pepper", qty="1 tsp")),
    ({"is_heading": 1, "label": "For the sauce"}, row("olive oil", qty="2 tbsp")),
    (None, row("olive oil", qty="2 tbsp")),
])
def test_an_ordinary_row_stands_on_its_own(above, this):
    assert ic.joins_the_row_above(above, this) == ""


# --------------------------------------------------------------------------- #
# The importer is the second caller, not a second copy of the rules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line, amount, unit, second, name", [
    ("1 stick (8 tablespoons/113 grams) unsalted butter", "1", "stick",
     "8 tablespoons / 113 grams", "unsalted butter"),
    ("One 16-ounce can chickpeas, drained", "1", "", None, "16-ounce can chickpeas, drained"),
    ("Scant ½ cup (120ml) extra-virgin olive oil", "scant ½ cup", "", "120ml",
     "extra-virgin olive oil"),
    ("3 L water", "3", "L", None, "water"),
    ("1½ Ib./700g skinned white fish fillets", "1½", "lb", "700g",
     "skinned white fish fillets"),
    ("¼ cup + 2 tablespoons ghee", "¼ cup + 2 tablespoons", "", None, "ghee"),
    ("1 cup of milk", "1", "cup", None, "milk"),
])
def test_an_import_gets_the_shape_the_repair_gave_the_corpus(line, amount, unit, second, name):
    d = ic.classify_line(line)
    assert (d["amount"], d["unit"], d["secondary_measure"], d["name"]) == (amount, unit, second,
                                                                          name)


@pytest.mark.parametrize("line", [
    "a pinch of salt", "salt and pepper, to taste", "five spice powder", "half-and-half",
])
def test_the_importer_refuses_the_same_lines_the_rules_do(line):
    d = ic.classify_line(line)
    assert d["name"] == line and d["amount"] == ""


def test_the_look_alike_letter_is_repaired_before_any_rule_reads_the_line():
    """"Ib." is not a unit, so the amount parse found none and the count-noun lift read 'fillets'
    as the unit, storing 1½ fillets of "Ib./700g skinned white fish"."""
    d = ic.classify_line("1½ Ib./700g skinned white fish fillets")
    assert d["unit"] == "lb" and "cleaned_lookalike_lb" in d["flags"]
    assert ic.repair_lookalike_units("Ibsen") == "Ibsen"           # only after a number


# --------------------------------------------------------------------------- #
# The cook estimate
# --------------------------------------------------------------------------- #
def _steps(*texts):
    return [{"id": i + 1, "position": i, "is_heading": 0, "text": t} for i, t in enumerate(texts)]


def test_the_estimate_reads_the_steps_and_says_so_with_a_tilde():
    e = pa.cook_estimate({"id": "r", "cook_time": None},
                         _steps("Fry the onions for 5 minutes.", "Bake for 30 to 35 minutes."))
    assert e["label"] == "~35 min – 40 min"


def test_an_author_s_own_cook_time_wins():
    e = pa.cook_estimate({"id": "r", "cook_time": "25 min"}, _steps("Bake for 30 minutes."))
    assert e["label"] == "" and e["verdict"] == "the author gave a cook time"


def test_a_cook_s_hand_edit_to_the_cook_time_is_never_overridden():
    """The smoothie's baseline said "0 mins" and its cook cleared it. 1 of the 300."""
    e = pa.cook_estimate({"id": "r", "cook_time": None}, _steps("Blend for 2 minutes."),
                         baseline_cook_time="0 mins")
    assert e["label"] == "" and e["verdict"] == "the cook edited the cook time by hand"


def test_the_seven_no_estimate_recipes_are_the_ones_the_decision_file_names():
    """⚠️ A DECLARED LIST, HELD TO THE FILE THAT DECIDED IT. A column would make these seven
    judgements user data a rebuild cannot explain, and a second copy of a list is a thing to
    drift."""
    import csv, io as _io, pathlib
    path = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "data-repairs"
            / "round-b-decisions-2026-10-08.csv")
    decided = {r["recipe_id"] for r in csv.DictReader(_io.open(path, encoding="utf-8-sig"))
               if r["action"] == "no_estimate"}
    assert decided == set(pa.NO_COOK_ESTIMATE), (decided ^ set(pa.NO_COOK_ESTIMATE))


@pytest.mark.parametrize("text, label", [
    ("Sear for 3 minutes per side.", "~6 min"),                     # per side is paid twice
    ("Simmer for at least 20 minutes.", "~20 min+"),                # at least has no ceiling
    ("Start this 30 minutes before you are ready to serve.", ""),   # scheduling, not heat
])
def test_decision_10_s_three_rules_about_what_a_duration_means(text, label):
    assert pa.cook_estimate({"id": "r", "cook_time": None}, _steps(text))["label"] == label


def test_a_bake_is_time_on_the_heat_even_where_the_clause_also_freezes_something():
    """buttermilk-biscuits step 17, one of the 14 read by hand. The sentence holds a rest AND a
    bake, and judging the sentence whole threw the bake away with the rest."""
    e = pa.cook_estimate({"id": "r", "cook_time": None}, _steps(
        "Place the tray in the freezer for 15 minutes, then transfer straight to the oven and "
        "bake for 15 to 17 minutes, rotating once at the 10-minute mark."))
    assert e["label"] == "~15 min – 17 min"


def test_two_trays_in_one_oven_are_not_two_tasks():
    """"Bake both sheets at the same time" took the whole estimate off four cookie recipes."""
    e = pa.cook_estimate({"id": "r", "cook_time": None},
                         _steps("Bake both sheets at the same time for 12 to 14 minutes."))
    assert e["label"] == "~12 min – 14 min"


def test_a_second_task_running_inside_the_first_still_takes_the_estimate_away():
    e = pa.cook_estimate({"id": "r", "cook_time": None}, _steps(
        "Boil the rice for 20 minutes.",
        "Meanwhile, simmer the lentils for 15 minutes."))
    assert e["label"] == "" and e["verdict"] == "no estimate, the steps overlap"


@pytest.mark.parametrize("text", [
    "Let the cookies cool for at least 1 hour on the baking sheets.",   # cookies is not a verb
    "If reusing one of the baking sheets, allow it to cool for 15 minutes.",
    "Allow the brownies to cool for 20 minutes.",
])
def test_a_cooling_is_not_a_bake_because_the_words_look_like_cooking(text):
    e = pa.cook_estimate({"id": "r", "cook_time": None}, _steps(text))
    assert e["label"] == ""


def test_the_wait_s_own_figure_is_excluded_and_the_rest_of_its_step_is_not():
    """blueberry-muffin-sugar-cookies browns butter for 3 to 4 minutes and cools it for 30, both
    in step 1, and the step carrying the wait took the browning with it."""
    steps = _steps("Cook the butter until fragrant, 3 to 4 minutes. Let it cool for 30 minutes.")
    waits = [{"step_id": 1, "label": "cool 30 min", "ext_label": "",
              "min_minutes": 30, "max_minutes": 30, "when_kind": "always"}]
    e = pa.cook_estimate({"id": "r", "cook_time": None}, steps, waits)
    assert e["label"] == "~3 min – 4 min"


def test_the_estimate_is_computed_and_never_stored():
    """There is no column and no migration. The proof is that recipe_total cannot see it: it reads
    recipe["cook_time"], which the estimate never writes."""
    recipe = {"id": "r", "cook_time": None, "prep_time": "10 min", "total_time": None}
    before = pa.recipe_total(recipe, [])
    pa.cook_estimate(recipe, _steps("Bake for 30 minutes."))
    assert recipe["cook_time"] is None
    assert pa.recipe_total(recipe, []) == before


# --------------------------------------------------------------------------- #
# What three fresh reviewers found, and none of it changed a cell of this round
# --------------------------------------------------------------------------- #
# Measured: the rehearsal before these fixes and after them differed by 0 cells. Every one is a
# path the 300 recipes do not exercise and an IMPORT, a save or the next recipe would.

def test_a_zero_denominator_is_not_a_number():
    """"1/0 hour" normalized happily to "1/0 hr" and then every reader of it raised."""
    assert ic.time_number("1/0") is None
    assert ic.normalize_time("1/0 hour") == "1/0 hour"
    assert pa.clock_minutes("1/0 hour") == (None, None)
    assert pa.read_duration("1/0 hour") == (None, None)


def test_a_figure_continued_by_and_a_half_is_refused_rather_than_halved():
    """It wrote "1 hr (and a half)", which STATES an hour for an hour and a half."""
    assert ic.normalize_time("one hour and a half") == "one hour and a half"
    assert pa.clock_minutes("one hour and a half") == (None, None)
    assert pa.read_duration("one hour and a half") == (None, None)


def test_the_first_segment_is_not_always_the_first_time():
    """⚠️ THE WIDENED READER LOST SIX DURATIONS IT USED TO READ. A word number matches "twelve
    balls" and "one batch", whose unit is not a time word, and read_duration took the first segment
    and gave up. The extension sentences in docs/data-repairs/ are written exactly that way."""
    for text, minutes in (("or roll into twelve balls and chill 30 minutes", 30),
                          ("or make one batch and rest 2 hours", 120),
                          ("cut each into four strips, then marinate 30 minutes", 30),
                          ("leave two thirds of the dough to rise 1 hour", 60)):
        assert pa.read_duration(text) == (minutes, minutes), text


def test_half_a_minute_is_a_minute_and_not_nothing():
    """int() truncated it to 0, and round() reads a half to the even number, which is also 0."""
    assert pa.clock_minutes("half a minute") == (1, 1)
    assert pa.clock_minutes("35 min") == (35, 35)          # a whole number is unchanged


def test_a_repair_declines_where_nothing_states_the_density():
    """⚠️ THE CORPUS PASS KNOWS WHAT EACH FOOD WEIGHS AND THE IMPORTER DOES NOT. Run with no
    density the wide band admitted several readings and the clear-winner test then picked one:
    classify_line read "2/3 cups (305 grams) all-purpose flour" as 1⅔ where the pass reads 2⅔."""
    d = ic.classify_line("2/3 cups (305 grams) all-purpose flour")
    assert d["amount"] == "2/3" and ic.BROKEN_AMOUNT_FLAG in d["flags"]
    # one candidate needs no choice, so the shapes with a single reading still work at import
    assert ic.classify_line("14 cups (250g) dried chickpeas")["amount"] == "1¼"
    assert ic.classify_line("stick (8 tablespoons/113 grams) unsalted butter")["amount"] == "1"


@pytest.mark.parametrize("line, second", [
    ("3 (6-ounce) salmon fillets", None),          # a per-piece size, and it used to SCALE
    ("6 (4-ounce) lamb chops", None),
    ("2 (1-pound) pork tenderloins", None),
    ("1 (14-ounce) can coconut milk", None),       # already caught, by the noun after it
    ("2 cups (about 320 grams) blueberries", "about 320 grams"),   # still a backup
])
def test_a_hyphenated_measure_in_a_bracket_is_a_size(line, second):
    assert ic.classify_line(line)["secondary_measure"] == second


@pytest.mark.parametrize("line", [
    "1 1/4 cups warm water (110 degrees F)",       # a temperature
    "1 pound ground chuck (80 percent lean)",      # a grade
    "1 cup heavy cream (36 percent fat)",
    "4 eggs (2 days old)",
])
def test_a_count_restatement_has_to_end_on_something_countable(line):
    """The trailing "<number> plus any lowercase words" had no positive test at all, so these were
    taken out of the name and stored as amounts that SCALE."""
    d = ic.classify_line(line)
    assert d["secondary_measure"] is None
    assert "(" in d["name"]                        # the bracket stays in the name


def test_a_discarded_plan_leaves_no_flag_behind():
    """A shallow copy is not a snapshot: the flag list is the same object, so a plan this block
    discarded still left its flag on the row, paired with the next rule's reason."""
    assert ic.classify_line("Zest of 1 lemon (optional")["flags"] == ["ambiguous_section"]
    assert ic.classify_line("")["flags"] == ["ambiguous_section"]


def test_every_round_b_flag_carries_its_reason_for_the_review_queue():
    for flag in (ic.UNBALANCED_BRACKET_FLAG, ic.BROKEN_AMOUNT_FLAG, ic.NO_NAME_COLUMN_FLAG,
                 ic.NO_NAME_LEFT_FLAG, ic.FOOD_INSIDE_FRAGMENT_FLAG):
        assert ic.CLEANUP_REASONS.get(flag), flag


def test_per_side_doubles_only_a_clause_that_states_one_duration():
    """"a total of around 4 minutes, 2 minutes on each side" states the total and then breaks it
    down, and the 4 was DOUBLED: 8 minutes printed for a 4-minute sear."""
    one = pa.cook_estimate({"id": "r", "cook_time": None},
                           _steps("Sear for 3 minutes per side."))
    assert one["label"] == "~6 min"
    for text, label in (("Sear the steak for a total of around 4 minutes, 2 minutes on each side.",
                         "~4 min"),
                        ("Grill for 10 minutes, 5 minutes per side.", "~10 min")):
        assert pa.cook_estimate({"id": "r", "cook_time": None}, _steps(text))["label"] == label


def test_keep_on_a_simmer_is_not_a_shelf_life():
    """_SHELF_LIFE opens on "keeps?|keeping", and the cooking-verb override was wired to the rest
    test alone, so "Cover and keep on a low simmer for 20 minutes" lost 20 minutes of heat."""
    e = pa.cook_estimate({"id": "r", "cook_time": None}, _steps(
        "Brown the sausage for 5 minutes.", "Cover and keep on a low simmer for 20 minutes."))
    assert e["label"] == "~25 min"
    # and a real shelf life is still excluded
    assert pa.cook_estimate({"id": "r", "cook_time": None},
                            _steps("These keep for up to 3 days in the fridge."))["label"] == ""


def test_a_wait_does_not_swallow_a_cooking_time_of_the_same_length():
    """The wait is matched by its MINUTES, so a 30-minute chill took a 30-minute simmer with it."""
    steps = _steps("Simmer for 30 minutes, then chill for 30 minutes.")
    waits = [{"step_id": 1, "label": "chill 30 min", "ext_label": "", "min_minutes": 30,
              "max_minutes": 30, "when_kind": "always"}]
    assert pa.cook_estimate({"id": "r", "cook_time": None}, steps, waits)["label"] == "~30 min"


def test_the_recipe_payload_computes_its_estimate_inside_the_session():
    """⚠️ THE RETURN jsonify(...) SITS OUTSIDE THE `with orm_session()`, so a query evaluated in
    that dict runs on a CLOSED session: SQLAlchemy opens a new transaction, checks out a
    connection, and nothing is left to return it. Measured by hammering one recipe through the test
    client: the commit :8000 runs served 60 requests cleanly and this one 500'd from the 26th,
    which is a pool of 5 plus an overflow of 10 leaking exactly one connection per page view. A
    real server dies after fifteen page loads.

    Stated over the SOURCE rather than by hammering a database, because the leak is a question
    about where the call sits and the suite has no 300-recipe database to hammer."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "app.py").read_text()
    body = src[src.index("def get_recipe("):]
    body = body[:body.index("\n@app.route")]
    estimate = body.index("planahead.cook_estimate(")
    handoff = body.index("\n    return jsonify(")
    assert estimate < handoff, (
        "planahead.cook_estimate is evaluated after the session block has closed, which leaks a "
        "connection on every recipe page view")


# =========================================================================== #
# REVISION 1: the six rules Andy's :8002 click-through asked for
#
# Each was measured over all 300 recipes before it was written. The counts in
# the comments are those measurements, and the rows named are the real rows.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# The four phrases EVERY rule here must leave alone
# --------------------------------------------------------------------------- #
MUST_NOT_FIRE = ["plus more for dusting", "salt and pepper, to taste", "or to taste",
                 "4 to 5 minutes per side"]


@pytest.mark.parametrize("text", MUST_NOT_FIRE)
def test_no_revision_1_rule_fires_on_the_four_phrases(text):
    """⚠️ ONE TEST OVER ALL SIX RULES, because a phrase that is safe from five of them and not
    from the sixth is the defect this list exists to catch."""
    r = row(text, raw_text=text)
    assert ic.sized_piece_amount(r) is None
    assert ic.per_serving_amount(r) is None
    assert ic.plus_another_food(r) is None
    assert ic.substitution_to_note(r) is None
    assert ic.remark_row_to_note({"is_heading": 1, "heading": "FOR THE DOUGH"}, r) is None
    assert ic.count_restatement(text) == ""
    # and with an amount in front of it, which is how three of them really appear
    with_amount = row(text, qty="1 tablespoon", quantity="1", unit="tablespoon",
                      raw_text="1 tablespoon " + text)
    assert ic.sized_piece_amount(with_amount) is None
    assert ic.per_serving_amount(with_amount) is None
    assert ic.substitution_to_note(with_amount) is None


# --------------------------------------------------------------------------- #
# R1. A sized piece IS the amount
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("r, qty, name_after", [
    # the 7 corpus rows, as they are stored
    (row("One 2-inch piece ginger, coarsely chopped (no need to peel)"),
     "2-inch piece", "ginger, coarsely chopped (no need to peel)"),
    (row("One 1½-inch piece fresh ginger, cut into quarters"),
     "1½-inch piece", "fresh ginger, cut into quarters"),
    (row("-inch knob ginger, finely chopped", qty="1", quantity="1"),
     "1-inch knob", "ginger, finely chopped"),
    (row("-inch section daikon, peeled and cut into big chunks", qty="3", quantity="3"),
     "3-inch section", "daikon, peeled and cut into big chunks"),
    (row("a 2-inch piece of ginger (smashed)"), "2-inch piece", "ginger (smashed)"),
    (row("One 2-inch piece ginger, peeled and coarsely chopped"),
     "2-inch piece", "ginger, peeled and coarsely chopped"),
    (row("One 2-inch piece cinnamon stick"), "2-inch piece", "cinnamon stick"),
])
def test_a_sized_piece_is_the_amount(r, qty, name_after):
    a = ic.sized_piece_amount(r)
    assert a is not None
    assert a["qty"] == qty
    name = r["label"]
    assert ic._tidy_name(name[a["front_len"]:]) == name_after


@pytest.mark.parametrize("r, why", [
    # ⚠️ 49 OF THE 56 CORPUS ROWS CARRYING A DIMENSION NEXT TO A SHAPE WORD ARE A CUT INSTRUCTION.
    (row("potatoes, cut into 2-inch sticks", qty="2 medium"), "a cut, and not at the front"),
    (row("bacon, cut into ½-inch pieces", qty="4 ounces"), "a cut"),
    (row("asparagus, chopped into ¾ in/2cm pieces", qty="8 oz"), "a cut"),
    (row("1-inch cubes of sturdy white bread", qty="2 cups", quantity="2", unit="cups"),
     "the row measures in cups and 'cubes' is the cut"),
    (row("-inch cubes", qty="½", quantity="½"),
     "chocolate-hazelnut-wedges: 'cube' is a cut word and there is no food after it"),
    (row("(torn ½-inch pieces) stale sourdough bread", qty="1 cup", quantity="1", unit="cup"),
     "bracketed, and the row has its own amount"),
    (row("kombu (a 4-inch x 6-inch piece of kelp)", qty="1 ounce"), "mid-name, in a bracket"),
    (row("2-inch piece"), "a size with no food after it is not an amount"),
])
def test_a_cut_instruction_is_not_an_amount(r, why):
    assert ic.sized_piece_amount(r) is None, why


def test_the_scaler_and_the_rule_read_one_sized_piece():
    """The amount the rule WRITES is the amount static/scaler.js has to scale. One reader."""
    assert ic.sized_piece_text("1-inch knob") == ("1", "1-inch knob")
    assert ic.sized_piece_text("2 × 1-inch knob") == ("2", "1-inch knob")
    assert ic.sized_piece_text("1 cup") == (None, None)
    assert ic.sized_piece_text("1-inch cubes") == (None, None)


# --------------------------------------------------------------------------- #
# R3. An amount marked per person
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("r, qty, name_after", [
    (row("ditalini, about 1/4 per person"), "about 1/4 per person", "ditalini"),
    (row("Thai basil leaves, 3 leaves per serving"), "3 leaves per serving",
     "Thai basil leaves"),
    (row("extra chicken stock for serving on the side, about 1/2 cup per person (see note 3)"),
     "about 1/2 cup per person", "extra chicken stock for serving on the side (see note 3)"),
])
def test_an_amount_marked_per_person_is_the_amount(r, qty, name_after):
    a = ic.per_serving_amount(r)
    assert a is not None and a["qty"] == qty and a["name"] == name_after


def test_a_row_that_already_has_an_amount_is_a_different_question():
    assert ic.per_serving_amount(row("ditalini, about 1/4 per person", qty="1 cup")) is None


def test_the_per_serving_rule_is_the_one_the_scaler_reads():
    assert ic.PER_SERVING_RE.search("about 1/2 cup per person")
    assert ic.PER_SERVING_RE.search("3 leaves per serving")
    assert not ic.PER_SERVING_RE.search("4 to 5 minutes per side")


# --------------------------------------------------------------------------- #
# R4. "(plus <amount> <another food>)" is its own row
# --------------------------------------------------------------------------- #
def test_a_second_food_in_a_plus_bracket_becomes_its_own_row():
    r = row("lemon juice (plus the zest of half of a lemon)", qty="1 tablespoon",
            quantity="1", unit="tablespoon",
            raw_text="1 tablespoon lemon juice (plus the zest of half of a lemon)")
    plan = ic.amount_plan(r)
    assert plan["changes"]["label"] == "lemon juice"
    assert plan["insert"]["label"] == "zest of ½ lemon"
    assert plan["insert"]["qty"] is None


def test_an_ice_cube_is_a_second_food_too():
    r = row("cold water (plus one ice cube)", qty="½ cup", quantity="½", unit="cup",
            raw_text="½ cup cold water (plus one ice cube)")
    plan = ic.amount_plan(r)
    assert plan["changes"]["label"] == "cold water"
    assert plan["insert"]["label"] == "1 ice cube"


@pytest.mark.parametrize("name", [
    "lemon juice (plus more for massaging kale // ~2 small lemons)",
    "mint leaves (plus more for garnish)",
    "all-purpose flour, plus more for dusting",
    "kosher salt, plus more if needed",
])
def test_plus_more_is_untouched(name):
    assert ic.plus_another_food(row(name)) is None


def test_more_of_the_same_food_for_another_job_is_flagged_not_split():
    """mongolian-chicken: "(plus ⅓ cup/80ml for frying)" is the row's own oil again. Taking
    the measures and the purpose off leaves nothing, and a row with no name is not a row."""
    a = ic.plus_another_food(row("vegetable oil (plus ⅓ cup/80ml for frying)"))
    assert a is not None and a["flag"] == ic.PLUS_NAMES_NO_FOOD_FLAG


# --------------------------------------------------------------------------- #
# R5. A substitution with its own amount moves to the row's note
# --------------------------------------------------------------------------- #
def test_a_substitution_with_its_own_amount_becomes_the_note():
    r = row("Tao Jiew (Thai fermented soybean paste) OR 2 tablespoon Korean doenjang "
            "+ 1 tablespoon water", qty="3 Tbsp", quantity="3", unit="Tbsp",
            raw_text="3 Tbsp Tao Jiew (Thai fermented soybean paste) OR 2 tablespoon Korean "
                     "doenjang + 1 tablespoon water")
    plan = ic.amount_plan(r)
    assert plan["changes"]["note"] == "or 2 tablespoons Korean doenjang + 1 tablespoon water"
    assert plan["changes"]["label"] == "Tao Jiew (Thai fermented soybean paste)"


@pytest.mark.parametrize("name, note", [
    ("cumin seeds (or 1 tsp ground cumin)", "or 1 tsp ground cumin"),
    ("kosher salt (or 1/2 tsp table salt)", "or 1/2 tsp table salt"),
    ("unsalted butter (or 2 tbsp canola or veg oil)", "or 2 tbsp canola or veg oil"),
    ("harissa, or 1 teaspoon Maras pepper", "or 1 teaspoon Maras pepper"),
])
def test_the_substitutions_the_corpus_carries(name, note):
    a = ic.substitution_to_note(row(name))
    assert a is not None and a["note"] == note


@pytest.mark.parametrize("name, why", [
    ("(8 ounces or 230 grams) unsalted butter, softened", "the same amount in two units"),
    ("Persian cucumbers, or 10 oz./350g (about 3 cups)", "no food of its own"),
    ("bundle kale (loosely chopped or torn // ~6-8 cups or 10 ounces as original recipe "
     "is written)", "a remark, not an ingredient"),
    ("fresh wide rice noodles, either pre-cut or in sheets, or 8 ounces dried wide rice "
     "noodles 3 tablespoons neutral oil", "two ingredients run together, nothing joins them"),
    ("garlic, minced (or 2 small cloves)", "a count with no unit: that is R2, not R5"),
])
def test_what_is_not_a_substitution(name, why):
    a = ic.substitution_to_note(row(name))
    assert a is None or "flag" in a, why


def test_r2_and_r5_can_never_both_fire():
    """⚠️ THE UNIT IS WHAT DIVIDES THEM, so the two rules are exclusive by construction: R2 needs
    a count with NO unit of measure and R5 needs an amount WITH one. Asserted rather than
    reasoned, because two rules writing one row is how a pass comes to set and unset a cell on
    every run."""
    for name in ["garlic, minced (or 2 small cloves)", "skin-on chicken breast (or 2 small ones)",
                 "cumin seeds (or 1 tsp ground cumin)", "harissa, or 1 teaspoon Maras pepper",
                 "cilantro roots or 6-8 cilantro stems"]:
        r = row(name, raw_text=name)
        second = bool(ic.author_second_amount(name)[0])
        sub = ic.substitution_to_note(r)
        assert not (second and sub and "flag" not in sub), name


def test_a_row_whose_note_is_taken_is_flagged_rather_than_overwritten():
    a = ic.substitution_to_note(row("cumin seeds (or 1 tsp ground cumin)", note="use whole"))
    assert a is not None and a["flag"] == ic.SUBSTITUTION_NOTE_TAKEN_FLAG


# --------------------------------------------------------------------------- #
# R6. A remark row under an ingredient heading becomes a recipe note
# --------------------------------------------------------------------------- #
def test_a_remark_under_a_heading_is_a_note_titled_with_the_heading():
    heading = {"is_heading": 1, "heading": "Basic Asian-Style Chicken Stock", "raw_text": None}
    r = row("(This makes more than you need, but you can freeze the rest)")
    a = ic.remark_row_to_note(heading, r)
    assert a is not None
    assert a["title"] == "Basic Asian-Style Chicken Stock"
    assert a["text"] == "This makes more than you need, but you can freeze the rest"


@pytest.mark.parametrize("above, name, why", [
    ({"is_heading": 0, "label": "chicken breast"}, "(thinly sliced)",
     "under an ordinary row, so it belongs to the line above it"),
    ({"is_heading": 0, "label": "low sodium chicken stock"}, "(160 ml, warmed)",
     "under an ordinary row, and it carries a measure"),
    ({"is_heading": 1, "heading": "FOR THE DOUGH"}, "(450g, medium thickness)",
     "a measure in it makes it a line of the recipe"),
    ({"is_heading": 1, "heading": "FOR THE DOUGH"}, "(sifted)",
     "two words is a prep clause, not a remark about a section"),
    (None, "(This makes more than you need, but you can freeze the rest)", "nothing above it"),
])
def test_what_is_not_a_remark_about_a_section(above, name, why):
    assert ic.remark_row_to_note(above, row(name)) is None, why


# --------------------------------------------------------------------------- #
# The importer runs every one of them, which is clause (2) of FIX BY RULE
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line, amount, name, note", [
    ("1-inch knob ginger, finely chopped", "1-inch knob", "ginger, finely chopped", None),
    ("One 2-inch piece ginger, peeled", "2-inch piece", "ginger, peeled", None),
    ("10 cloves (or 1/4 tsp ground cloves)", "10", "cloves", "or 1/4 tsp ground cloves"),
    ("2 tsp cumin seeds (or 1 tsp ground cumin)", "2", "cumin seeds", "or 1 tsp ground cumin"),
])
def test_the_importer_runs_the_revision_1_rules(line, amount, name, note):
    d = ic.classify_line(line)
    assert d["amount"] == amount
    assert d["name"] == name
    assert (d.get("note") or None) == note


def test_the_importer_carries_r4_s_second_row():
    d = ic.classify_line("1 tablespoon lemon juice (plus the zest of half of a lemon)")
    assert d["name"] == "lemon juice"
    assert d["second_food"]["label"] == "zest of ½ lemon"


def test_the_importer_reads_an_or_count_as_a_second_amount():
    d = ic.classify_line("1 large skin-on chicken breast (or 2 small ones)")
    assert d["secondary_measure"] == "or 2 small"
    assert d["name"] == "skin-on chicken breast"
