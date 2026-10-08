"""Round B's rules: the author's second amount, the units left in names, the broken amounts.

Every case here is a real corpus line unless it is marked as one the rule must NOT fire on. The
refusals are the half worth reading: a rule that only ever fires is a rule nobody has measured.
"""
import pytest

import import_cleanup as ic
import planahead as pa


def row(label, qty="", quantity=None, unit="", raw_text=None, secondary=None, grams=None,
        recipe_id="a-recipe"):
    return {"recipe_id": recipe_id, "label": label, "raw_text": raw_text or label, "qty": qty,
            "quantity": quantity if quantity is not None else qty, "unit": unit,
            "secondary_measure": secondary, "grams": grams, "is_heading": 0}


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
    "or 2 small cloves",       # an alternative ingredient
    "4 large, 5 medium",       # a list of two answers
    "16-20 per lb",            # a grade
    "1 if large",              # a note
])
def test_a_count_restatement_refuses_what_only_looks_like_a_count(text):
    assert ic.count_restatement(text) == ""
    assert ic.classify_fragment(text)[0] == ic.FRAGMENT_PROSE


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
    (row("-inch knob ginger, finely chopped", qty="1"), "sized_piece", "",
     "1-inch knob ginger, finely chopped"),
    (row(", Italian Imported Marsala Wine", qty="2 Cups", quantity="2", unit="Cups"),
     "leading_punctuation", "2 Cups", "Italian Imported Marsala Wine"),
    (row("of Olive Oil", qty="1/2 Cup", quantity="1/2", unit="Cup"), "word_the_unit_left",
     "1/2 Cup", "Olive Oil"),
    (row("a 2-inch piece of ginger (smashed)"), "a_an_sized_piece", "1",
     "2-inch piece of ginger (smashed)"),
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


def test_a_fragment_carrying_the_food_s_own_name_stays_in_the_name():
    r = row("(2 large semi-ripe bananas) , peeled and roughly chopped", qty="300 grams",
            quantity="300", unit="grams",
            raw_text="300 grams (2 large semi-ripe bananas), peeled and roughly chopped")
    plan = ic.amount_plan(r)
    # The name keeps the fragment. It is tidied (the space in front of the comma is the artifact
    # cleaned_space_before_comma exists for) and the bananas stay in it.
    assert "2 large semi-ripe bananas" in plan["changes"]["label"]
    assert plan["notes"][0][0] == ic.FOOD_INSIDE_FRAGMENT_FLAG
    assert plan["changes"]["secondary_measure"] == "2 large semi-ripe bananas"


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
    assert plan["changes"] == {}
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
    assert plan["changes"] == {} and plan["flags"][0][0] == ic.BROKEN_AMOUNT_FLAG


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
