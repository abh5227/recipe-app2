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


# ⚠️ REVISION 1 REFUSED BOTH OF THESE, AND ANDY'S FINAL CALL SPLITS THEM (decisions-3). Each leaves
#    a word the name never had ("English", "pureed"), and revision 1 read any such word as a
#    possible different food and sent both to the review list. The head of each name decides it:
#    an English cucumber is a cucumber, so "English" says which kind and stays on the second line,
#    and pureed tomatoes are not tomato sauce, so that alternative is R5's and goes to the note.
def test_a_count_of_the_same_food_keeps_the_words_that_say_which_kind():
    plan = ic.amount_plan(row("Persian cucumber or ½ English cucumber, finely diced",
                              qty="1", quantity="1",
                              raw_text="1 Persian cucumber or ½ English cucumber, finely diced"))
    assert plan["changes"]["secondary_measure"] == "or ½ English"
    assert plan["changes"]["label"] == "Persian cucumber, finely diced"
    assert "note" not in plan["changes"]


def test_a_count_of_a_different_food_is_r5_and_goes_to_the_note():
    plan = ic.amount_plan(row("tomato sauce, or 2 pureed tomatoes", qty="1/4 cup", quantity="1/4",
                              unit="cup", raw_text="1/4 cup tomato sauce, or 2 pureed tomatoes"))
    assert plan["changes"]["note"] == "or 2 pureed tomatoes"
    assert plan["changes"]["label"] == "tomato sauce"
    assert plan["changes"].get("secondary_measure") is None
    assert not plan["notes"]


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


# =========================================================================== #
# What two fresh reviewers found in revision 1
#
# Fourteen MUST-FIX between them, every one verified by running the repro
# before it was fixed. Each test below names the defect it holds shut.
# =========================================================================== #

def test_a_discarded_plan_leaves_no_note_and_no_second_food():
    """⚠️ update() CANNOT REMOVE A KEY THE PLAN ADDED. Block 3d snapshots `res`, runs the plan, and
    restores the snapshot when no amount comes back. `res` carries neither `note` nor
    `second_food` at snapshot time, so a DISCARDED plan left both behind: the cumin row was
    written as an ambiguous row stating its substitution twice, in the name and in the note under
    it, and the apple-pie line named the same zest twice.

    ⚠️ REVISION 2 MOVED THE NOTE BACK, ON PURPOSE, AND THE GUARD IS NOW WHAT IT ALWAYS MEANT: ONCE.
    note_rules runs on the no-amount path too, because the corpus pass applies R5 to the same line
    stored with no amount. The substitution is in the note and OUT of the name, which is stated
    once. What this test held shut was stating it twice."""
    d = ic.classify_line("cumin seeds (or 1 tsp ground cumin)")
    assert d["kind"] == "flagged"
    assert d["note"] == "or 1 tsp ground cumin"
    assert "or 1 tsp" not in d["name"]
    assert d.get("second_food") is None
    d = ic.classify_line("lemon juice (plus the zest of half of a lemon)")
    assert d.get("second_food") is None


def test_r4_flags_a_row_it_would_leave_with_no_name_rather_than_looping():
    """⚠️ `insert` COUNTS AS A RULE HAVING FIRED. "(plus 1 cup sugar)" is a whole name inside a
    plus-bracket: nothing landed in `changes`, the no-name guard did not fire, and the insert came
    back on EVERY run. That is the round's own "a second run writes nothing" gate failing."""
    r = row("(plus 1 cup sugar)")
    for _ in range(3):
        plan = ic.amount_plan(r)
        assert plan["insert"] is None
        assert any(f == ic.NO_NAME_LEFT_FLAG for f, _x in plan["flags"])
        assert plan["changes"] == {}


@pytest.mark.parametrize("line, name, note", [
    ("1 pound beef or 1 pound lamb, cut into 1-inch cubes",
     "beef, cut into 1-inch cubes", "or 1 pound lamb"),
    ("1 cup yogurt (or 1 cup sour cream), whisked", "yogurt, whisked", "or 1 cup sour cream"),
    ("1 cup milk or 1 cup cream, warmed, plus 2 tablespoons for brushing",
     "milk, warmed, plus 2 tablespoons for brushing", "or 1 cup cream"),
])
def test_r5_s_bare_or_run_stops_at_a_comma_like_r2_s(line, name, note):
    """⚠️ EVERYTHING AFTER THE COMMA IS THE ROW'S OWN PREP CLAUSE. R5's loop stopped at ";()" where
    R2's stops at ",;()", so the cut instruction went into the alternative's note and left the
    ingredient altogether. The bracketed spelling of the same line already kept it, so the two
    spellings of one thing disagreed."""
    d = ic.classify_line(line)
    assert d["name"] == name
    assert d["note"] == note


@pytest.mark.parametrize("name", [
    "beef or 1 lb beef",
    "milk or 240 ml milk",
])
def test_an_or_that_restates_the_same_food_is_not_a_substitution(name):
    """⚠️ THE RULE'S OWN REASON CLAIMED "a different ingredient" WITHOUT TESTING IT. These are one
    food in a second unit, which is what the second-amount slot exists for. The row goes to the
    review list: admitting it would widen R2 past the decision Andy made, and guessing is what
    decline-over-guess exists to stop. R2's count_parts answers the question, so the test is
    shared rather than written twice."""
    a = ic.substitution_to_note(row(name, qty="500 g", quantity="500", unit="g"))
    assert a is not None and a["flag"] == ic.SUBSTITUTION_SAME_FOOD_FLAG


# ⚠️ AND A DIFFERENT FORM OF A FOOD IS A DIFFERENT FOOD, which is where the first two drafts of
#    that test went wrong in opposite directions. Asking "does the alternative name any word the
#    row does not" declined the two cardamom rows, because a trailing "(freshly ground is best)"
#    lent them the word "ground". Stripping every MODWORD from both sides declined these four,
#    because "kosher", "table", "ground" and "cooked" are prep words AND are exactly what tells
#    one form of a food from another. Whole pods are not ground cardamom.
@pytest.mark.parametrize("name, note", [
    ("green cardamom pods, or 1 teaspoon ground cardamom (freshly ground is best)",
     "or 1 teaspoon ground cardamom"),
    ("cumin seeds (or 1 tsp ground cumin)", "or 1 tsp ground cumin"),
    ("kosher salt (or 1/2 tsp table salt)", "or 1/2 tsp table salt"),
    ("cloves (or 1/4 tsp ground cloves)", "or 1/4 tsp ground cloves"),
    ("chickpeas, rinsed and drained, or 1 \u00bd cups cooked chickpeas",
     "or 1 \u00bd cups cooked chickpeas"),
])
def test_a_different_form_of_a_food_is_still_a_substitution(name, note):
    a = ic.substitution_to_note(row(name, qty="1 cup", quantity="1", unit="cup"))
    assert a is not None and a.get("note") == note


def test_two_substitutions_and_one_note_column_is_named_not_dropped():
    a = ic.substitution_to_note(
        row("2 tablespoons sugar or 2 tablespoons honey (or 1 tablespoon maple syrup)"))
    assert a is not None and a["flag"] == ic.SUBSTITUTION_TWO_FLAG


def test_the_canned_branch_runs_the_rules_too():
    """⚠️ A BRANCH THAT RETURNS EARLY IS NOT A SECOND CALLER. classify_line's canned-good branch
    returned before apply_amount_plan, so one line got two answers: the importer kept the
    substitution in the name and the corpus pass, reading the same row back, moved it."""
    d = ic.classify_line("2 (14-ounce) cans whole tomatoes (or 2 tablespoons tomato paste)")
    assert (d["amount"], d["unit"]) == ("2", "cans")
    assert d["name"] == "whole tomatoes"
    assert d["note"] == "or 2 tablespoons tomato paste"
    d = ic.classify_line("1 (15-ounce) can pumpkin puree (plus 1 cup heavy cream)")
    assert d["second_food"]["label"] == "1 cup heavy cream"
    # an ordinary canned line is untouched
    d = ic.classify_line("1 (14-ounce) can coconut milk")
    assert (d["amount"], d["unit"], d["name"]) == ("1", "can", "coconut milk")
    assert (d.get("note") or None) is None


def test_the_multiplier_is_a_times_sign_and_never_a_letter_x():
    """⚠️ "1 x 2-inch piece" IS A DIMENSION PAIR, a sheet of kombu an inch by two. The writer
    declines to make an amount of it, and the READER accepted its "1 x" as a count, so at 2x a
    sheet that got no bigger printed "2 × 2-inch piece"."""
    assert ic.sized_piece_text("1 x 2-inch piece") == (None, None)
    assert ic.sized_piece_text("2 × 1-inch knob") == ("2", "1-inch knob")
    assert ic.sized_piece_amount(row("a 1 x 2-inch piece of kombu")) is None


def test_every_sized_piece_the_writer_emits_is_in_the_cross_language_fixture():
    """⚠️ THE WORD-LIST GUARD MISSED EVERYTHING THAT MATTERED. tests/js/sized-piece-sync.test.js
    compared PIECE_WORDS and four integer examples and passed while the two number grammars had
    diverged on six shapes this side actually writes. tests/fixtures/sized-piece.json is generated
    FROM this reader and asserted by both suites, so the next drift goes red."""
    import json
    import pathlib
    doc = json.loads((pathlib.Path(__file__).resolve().parent
                      / "fixtures" / "sized-piece.json").read_text())
    assert len(doc["cases"]) >= 30
    for case in doc["cases"]:
        count, piece = ic.sized_piece_text(case["amount"])
        assert count == case["count"], case["amount"]
        assert piece == case["piece"], case["amount"]
    # and the six shapes the JS could not read are all in it
    held = {c["amount"] for c in doc["cases"] if c["count"]}
    for shape in ("1/2-inch slices", "1 to 2-inch chunks", "roughly 3 cm chunk",
                  "about 2-inch piece", "4 in. piece", "1 1/2-inch piece"):
        assert shape in held, shape


def test_per_serving_has_one_home_and_head_is_not_on_the_list():
    """⚠️ ONE RULE, THREE CALLERS. The list lived in import_cleanup where only one of the three
    could see it, and stepscale did not lock the same figure: at 2x the ledger read "about ½ cup
    per person" while the step beside it read "1 cup rice per person".
    ⚠️ AND "head" IS OFF IT. _COUNT_NOUNS holds "head"/"heads" as a UNIT the parse writes into the
    unit column, so "1 pound per head" read as a per-diner figure and the scaler then refused to
    scale a head of cabbage."""
    import units
    assert ic.PER_SERVING_WORDS is units.PER_SERVING_WORDS
    assert "head" not in units.PER_SERVING_WORDS
    assert "head" in ic._COUNT_NOUNS and "heads" in ic._COUNT_NOUNS
    assert ic.per_serving_amount(row("cabbage, 1 pound per head")) is None


def test_the_method_text_locks_a_per_person_figure_in_its_own_clause():
    import stepscale
    locked = stepscale.api_spans("Serve with about 1/2 cup rice per person.")
    assert all(s["t"] == "plain" for s in locked)
    # ⚠️ AND THE LOOKAHEAD STOPS AT A COMMA. A clause-wide guard would have locked both figures.
    mixed = stepscale.api_spans("Divide 2 cups rice among the bowls, about 1/2 cup per person.")
    assert [s["text"] for s in mixed if s["t"] == "scale"] == ["2 cups"]
    # a full stop is a boundary too
    two = stepscale.api_spans("Add 1 cup stock. Serve 2 tablespoons per person.")
    assert [s["text"] for s in two if s["t"] == "scale"] == ["1 cup"]


def test_fix_plurals_has_a_right_hand_boundary():
    """⚠️ "2 pint-sized jars" BECAME "2 pints-sized jars". A unit used attributively is not the
    thing being counted. static/scaler.js carries the identical guard."""
    import units
    assert units.fix_plurals("or 2 pint-sized jars tomatoes") == "or 2 pint-sized jars tomatoes"
    assert units.fix_plurals("2 can-sized boxes") == "2 can-sized boxes"
    assert units.fix_plurals("2 cup") == "2 cups"            # still does its job
    assert units.fix_plurals("1 cups") == "1 cup"


def test_r6_has_an_importer_caller():
    """⚠️ CLAUSE (2) OF FIX BY RULE WAS MISSING FOR R6. Nothing outside the corpus pass and the
    tests called remark_row_to_note, so an imported remark under a heading was written as an
    ingredient named after the remark."""
    import import_write as iw
    rows, _flags, remarks = iw._ingredient_rows({"ingredients": [
        ic.classify_line(line) for line in
        ["FOR THE CHICKEN:", "(use the dark meat if you can get it)", "2 pounds chicken thighs"]]})
    assert [r["label"] or r["raw_text"] for r in rows] == ["FOR THE CHICKEN:", "chicken thighs"]
    assert remarks == [{"title": "FOR THE CHICKEN",
                        "text": "use the dark meat if you can get it"}]


def test_the_note_title_loses_a_trailing_colon_for_both_callers():
    """A stored heading has already lost it and one arriving from an import has not, so the two
    callers produced two different titles for one rule."""
    a = ic.remark_row_to_note({"is_heading": 1, "raw_text": "FOR THE CHICKEN:"},
                              row("(use the dark meat if you can get it)"))
    assert a["title"] == "FOR THE CHICKEN"


def test_r4_s_insert_renumbers_and_takes_no_flag_with_it():
    """⚠️ _group_optional_lines EARLY-RETURNS WHEN IT FINDS NO GROUP, so a recipe with an R4 insert
    and no Optional run was written with two rows at one position. And a flag's position was the
    CLEANED LINE index while the move map is keyed on the ROW index, so every flag after an
    insert was remapped onto its neighbour."""
    import import_write as iw
    rows, _f, _r = iw._ingredient_rows({"ingredients": [ic.classify_line(line) for line in
        ["1 tablespoon lemon juice (plus the zest of half of a lemon)", "2 cups flour",
         "1 tsp salt"]]})
    assert [r["position"] for r in rows] == [0, 1, 2, 3]
    assert [r["label"] for r in rows] == ["lemon juice", "zest of ½ lemon", "flour", "salt"]

    rows, flags, _r = iw._ingredient_rows({"ingredients": [ic.classify_line(line) for line in
        ["1 tablespoon lemon juice (plus the zest of half of a lemon)",
         "2 cups flour, each sifted", "Optional: 1 tsp vanilla",
         "Optional: 1 tsp almond extract"]]})
    assert [r["position"] for r in rows] == [0, 1, 2, 3, 4, 5]
    where = {f["flag"]: f["position"] for f in flags if f["flag"] == "each_multi"}
    assert where["each_multi"] == 2            # the flour, not the inserted zest
    assert sorted(f["position"] for f in flags if f["flag"] == "ambiguous_section") == [4, 5]


# =========================================================================== #
# Revision 2. Andy's final call on "or" (decisions-3), and "plus more" to the note
# =========================================================================== #

# --------------------------------------------------------------------------- #
# 2a. An "or" of the SAME food is a second amount line, keeping "or", minus the
#     words that only repeat the line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line, qty, label, second", [
    ("1 large skin-on chicken breast (or 2 small ones)", "1 large",
     "skin-on chicken breast (or 2 small ones)", "or 2 small"),
    ("3-4 cilantro roots or 6-8 cilantro stems", "3-4", "cilantro roots or 6-8 cilantro stems",
     "or 6–8 stems"),
    ("1 large garlic clove, minced (or 2 small cloves)", "1 large clove",
     "garlic, minced (or 2 small cloves)", "or 2 small"),
    ("1 Persian cucumber or ½ English cucumber, finely diced", "1",
     "Persian cucumber or ½ English cucumber, finely diced", "or ½ English"),
])
def test_an_or_of_the_same_food_is_its_own_second_amount_line(line, qty, label, second):
    plan = ic.amount_plan(row(label, qty=qty, raw_text=line))
    assert plan["changes"]["secondary_measure"] == second
    assert "note" not in plan["changes"]


def test_a_counting_noun_the_amount_does_not_say_is_kept():
    """panang-curry's "(~ 6 leaves)" sits under "1 tbsp". Dropping "leaves" because the NAME says
    it would leave "~ 6" under a tablespoon, which reads as six of them."""
    assert ic.count_parts("~ 6 leaves", "1 tbsp kaffir lime leaves ", "1 tbsp")["count"] == "~ 6 leaves"
    assert ic.count_parts("or 2 small cloves", "1 large garlic clove ", "1 large clove")["count"] \
        == "or 2 small"


# --------------------------------------------------------------------------- #
# 2b. A backup count with an "or" INSIDE it is two lines
# --------------------------------------------------------------------------- #
def test_an_or_inside_a_backup_count_splits_into_stacked_lines():
    plan = ic.amount_plan(row("cucumbers (4 medium or 2 long cucumbers)", qty="500 g",
                              quantity="500", unit="g",
                              raw_text="500g/ 1 lb cucumbers (4 medium or 2 long cucumbers)"))
    assert plan["changes"]["secondary_measure"] == "1 lb / 4 medium / or 2 long"
    assert plan["changes"]["label"] == "cucumbers"


def test_a_leading_or_is_one_line_not_two():
    assert ic._split_at_or("or 2 small") == ["or 2 small"]
    assert ic._split_at_or("4 medium or 2 long") == ["4 medium", "or 2 long"]


# --------------------------------------------------------------------------- #
# 2c. An "or" substituting a DIFFERENT food with its own amount is R5, the note
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label, qty, line, note", [
    ("tomato sauce, or 2 pureed tomatoes", "1/4 cup", "1/4 cup tomato sauce, or 2 pureed tomatoes",
     "or 2 pureed tomatoes"),
    ("Tao Jiew (Thai fermented soybean paste) OR 2 tablespoon Korean doenjang + 1 tablespoon water",
     "3 Tbsp", "3 Tbsp Tao Jiew (Thai fermented soybean paste) OR 2 tablespoon Korean doenjang "
     "+ 1 tablespoon water", "or 2 tablespoons Korean doenjang + 1 tablespoon water"),
])
def test_an_or_of_a_different_food_is_the_note(label, qty, line, note):
    plan = ic.amount_plan(row(label, qty=qty, raw_text=line))
    assert plan["changes"]["note"] == note
    assert plan["changes"].get("secondary_measure") is None


def test_the_same_food_question_has_one_answer_for_r2_and_r5():
    """or_count_alternative is asked by both rules, so a count goes to exactly one of them."""
    for name, line in [
        ("Persian cucumber or ½ English cucumber, finely diced",
         "1 Persian cucumber or ½ English cucumber, finely diced"),
        ("tomato sauce, or 2 pureed tomatoes", "1/4 cup tomato sauce, or 2 pureed tomatoes"),
        ("skin-on chicken breast (or 2 small ones)",
         "1 large skin-on chicken breast (or 2 small ones)"),
    ]:
        second = bool(ic.author_second_amount(line)[0])
        sub = ic.substitution_to_note(row(name, raw_text=line))
        assert second != bool(sub and "note" in sub), name


@pytest.mark.parametrize("line", [
    "kosher salt, or to taste",
    "salt and pepper, or to taste",
    "1 tsp kosher salt, or to taste",
])
def test_or_to_taste_does_not_fire(line):
    plan = ic.amount_plan(row(line, raw_text=line))
    assert "secondary_measure" not in plan["changes"]
    assert "note" not in plan["changes"]
    assert ic.or_count_alternative("or to taste", line) is None


# --------------------------------------------------------------------------- #
# The importer runs 2a, 2b and 2c, which is clause (2) of FIX BY RULE
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line, name, second, note", [
    ("1 Persian cucumber or ½ English cucumber, finely diced", "Persian cucumber, finely diced",
     "or ½ English", None),
    ("1 large garlic clove, minced (or 2 small cloves)", "garlic, minced", "or 2 small", None),
    ("500g/ 1 lb cucumbers (4 medium or 2 long cucumbers)", "cucumbers",
     "1 lb / 4 medium / or 2 long", None),
    ("1/4 cup tomato sauce, or 2 pureed tomatoes", "tomato sauce", None, "or 2 pureed tomatoes"),
    ("1 tsp kosher salt, or to taste", "kosher salt, or to taste", None, None),
])
def test_the_importer_runs_revision_2_s_or_rule(line, name, second, note):
    d = ic.classify_line(line)
    assert d["name"] == name
    assert (d.get("secondary_measure") or None) == second
    assert (d.get("note") or None) == note


# --------------------------------------------------------------------------- #
# R7. "plus more …" is the row's note
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label, name, note", [
    ("all-purpose flour, plus more for dusting", "all-purpose flour", "plus more for dusting"),
    ("kosher salt, plus more if needed", "kosher salt", "plus more if needed"),
    ("milk, plus more as needed", "milk", "plus more as needed"),
    ("mint leaves (plus more for garnish)", "mint leaves", "plus more for garnish"),
    ("self-rising flour (plus extra for dusting)", "self-rising flour", "plus extra for dusting"),
    ("thyme, plus some for garnish", "thyme", "plus some for garnish"),
    ("heavy cream plus more for brushing", "heavy cream", "plus more for brushing"),
    ("olive oil, divided, plus more for drizzling", "olive oil, divided", "plus more for drizzling"),
    ("unsalted butter, plus more for pan, at room temperature",
     "unsalted butter, at room temperature", "plus more for pan"),
    ("kosher salt, plus more to taste and for seasoning croquettes", "kosher salt",
     "plus more to taste and for seasoning croquettes"),
    ("parsley, finely chopped, plus extra for garnish (optional)", "parsley, finely chopped",
     "plus extra for garnish (optional)"),
])
def test_plus_more_goes_to_the_note(label, name, note):
    plan = ic.amount_plan(row(label, qty="1 cup", quantity="1", unit="cup",
                              raw_text="1 cup " + label))
    assert plan["changes"]["label"] == name
    assert plan["changes"]["note"] == note
    # and a second run over the result changes nothing
    again = ic.amount_plan(row(name, qty="1 cup", quantity="1", unit="cup",
                               raw_text="1 cup " + label, note=note))
    assert "note" not in again["changes"] and "label" not in again["changes"]


@pytest.mark.parametrize("label, qty, why", [
    ("plus 2 tablespoons", "½ cup", "a compound amount stays in the amount"),
    ("lemon juice (plus the zest of half of a lemon)", "1 tablespoon", "another food is R4"),
    ("vegetable oil (plus ⅓ cup/80ml for frying)", "1 tablespoon",
     "more with an amount of its own: Andy's 'keep as is' on mongolian-chicken 4666"),
    ("cornstarch (plus 2 teaspoons)", "1/4 cup", "Andy's 'keep as is' on teriyaki-tofu 5799"),
    ("salt and pepper, to taste", "", "no plus at all"),
    ("plus more for dusting", "", "a row that is only the remark keeps its name"),
])
def test_what_r7_leaves_alone(label, qty, why):
    plan = ic.amount_plan(row(label, qty=qty, raw_text=(qty + " " + label).strip()))
    assert plan["changes"].get("note") is None, why


@pytest.mark.parametrize("label", [
    "extra virgin olive oil, plus more to serve freshly ground black pepper",
    "good olive oil, plus more for serving 1 teaspoon whole black peppercorns",
    "skin-on boneless snapper, 10 to 12 ounces each 2 teaspoons kosher salt, plus more for the sauce",
    "lemon juice (plus more for massaging kale // ~2 small lemons)",
])
def test_a_remark_that_carries_another_ingredient_is_flagged_not_hidden(label):
    """A note would hide the pepper inside a remark about olive oil. Each of these is a real line."""
    plan = ic.amount_plan(row(label, qty="2 tablespoons", raw_text="2 tablespoons " + label))
    assert "note" not in plan["changes"]
    assert ic.PLUS_MORE_RUNS_ON_FLAG in [f for f, _ in plan["notes"]]


def test_the_compound_half_is_not_read_as_a_second_ingredient():
    """cinnamon-sugar-speculoos: the leading "plus 1 teaspoon" is the amount's own second half."""
    plan = ic.amount_plan(row("plus 1 teaspoon milk, plus more as needed", qty="1 tablespoon",
                              quantity="1", unit="tablespoon",
                              raw_text="1 tablespoon plus 1 teaspoon milk, plus more as needed"))
    assert plan["changes"]["label"] == "milk"
    assert plan["changes"]["note"] == "plus more as needed"
    assert plan["changes"]["qty"] == "1 tablespoon + 1 teaspoon"


def test_a_taken_note_is_flagged_rather_than_overwritten():
    plan = ic.amount_plan(row("kosher salt, plus more if needed", qty="1 tsp",
                              raw_text="1 tsp kosher salt, plus more if needed", note="Diamond"))
    assert "note" not in plan["changes"]
    assert ic.PLUS_MORE_NOTE_TAKEN_FLAG in [f for f, _ in plan["notes"]]


def test_r5_s_note_and_r7_s_remark_on_one_row_name_the_clash():
    plan = ic.amount_plan(row("kosher salt (or 1/2 tsp table salt), plus more to taste",
                              qty="1 tsp", raw_text="1 tsp kosher salt (or 1/2 tsp table salt), "
                                                    "plus more to taste"))
    assert plan["changes"]["note"] == "or 1/2 tsp table salt"
    assert ic.PLUS_MORE_NOTE_TAKEN_FLAG in [f for f, _ in plan["notes"]]


@pytest.mark.parametrize("line, name, note", [
    ("2 cups all-purpose flour, plus more for dusting", "all-purpose flour",
     "plus more for dusting"),
    ("1/4 cup mint leaves (plus more for garnish)", "mint leaves", "plus more for garnish"),
])
def test_the_importer_runs_r7(line, name, note):
    d = ic.classify_line(line)
    assert d["name"] == name
    assert d.get("note") == note


# =========================================================================== #
# What the fresh reviewer of revision 2 found. Each test holds one defect shut;
# every one was reproduced before it was fixed.
# =========================================================================== #

@pytest.mark.parametrize("line", [
    "4 tablespoons extra virgin olive oil, plus more for serving freshly ground black pepper",
    "2 tbsp olive oil, plus more for drizzling Kosher salt and black pepper",
])
def test_a_for_purpose_cannot_carry_another_ingredient_into_the_note(line):
    """MUST-FIX: the "for" arm took "for" plus anything without a digit, so the importer put the
    pepper inside a note about olive oil with no flag. A purpose is short and lowercase."""
    d = ic.classify_line(line)
    assert d.get("note") is None
    assert ic.PLUS_MORE_RUNS_ON_FLAG in d["flags"]


@pytest.mark.parametrize("remark", [
    "plus more for dusting", "plus more for rolling out the dough", "plus more for oiling the dough",
    "plus more for greasing the pan", "plus more for kneading and rolling", "plus more for dough resting",
    "plus more for the sauce", "plus extra for pan-frying", "plus more to taste and for seasoning croquettes",
    "plus more if needed", "plus some for garnish",
])
def test_every_purpose_shape_the_corpus_writes_still_reads_as_a_remark(remark):
    assert ic._PLUS_MORE_REMARK_RE.match(remark), remark


@pytest.mark.parametrize("line, name, note", [
    ("1 lemon or 2 limes", "lemon", "or 2 limes"),
    ("1 medium onion (or 2 shallots)", "onion", "or 2 shallots"),
])
def test_an_or_count_of_a_food_the_line_never_names_keeps_its_food(line, name, note):
    """MUST-FIX: "limes" shared no word with the line, so there was no leftover, no ruling, and R2
    stored "or 2" alone. The limes were in no column at all."""
    d = ic.classify_line(line)
    assert d["name"] == name
    assert d.get("note") == note
    assert not d.get("secondary_measure")


def test_the_alternative_s_head_is_a_food_word_never_a_counting_noun():
    """SHOULD-FIX: "or 6 small lemon thyme sprigs" ended on "sprigs", which the line's head had
    already stripped, so the two heads disagreed on one food and nothing moved or was flagged."""
    d = ic.classify_line("4 sprigs thyme (or 6 small lemon thyme sprigs)")
    assert d["secondary_measure"] == "or 6 small lemon"
    assert d["name"] == "thyme"


@pytest.mark.parametrize("line, name, note", [
    ("Kosher salt, plus more for serving", "Kosher salt", "plus more for serving"),
    ("cumin seeds (or 1 tsp ground cumin)", "cumin seeds", "or 1 tsp ground cumin"),
])
def test_the_importer_s_no_amount_path_still_runs_r5_and_r7(line, name, note):
    """SHOULD-FIX: block 3d threw the whole plan away when no amount resolved, so the corpus pass
    moved these remarks and the importer kept them in the name. note_rules is now both paths'."""
    d = ic.classify_line(line)
    assert d["name"] == name
    assert d["note"] == note


# ---- revision 3a: the third residual file ------------------------------------------------------- #
import pathlib as _pathlib                                                      # noqa: E402
import sys as _sys                                                              # noqa: E402

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import apply_round_b as _rb                                                     # noqa: E402


def test_the_latest_residual_file_wins_and_every_fix_in_it_is_accounted_for():
    """kachumber-tilapia 4145 was sent to the note by the second file and to the second amount by
    the third. The pass reads all three, the latest wins, and a "fix" nothing runs stops the pass."""
    decided = _rb._residual_decisions_all()
    assert "second amount" in decided[4145][0]
    assert 4145 in _rb.RESIDUAL_2_BY_RULE
    assert not set(_rb.RESIDUAL_2_BY_RULE) & set(_rb.RESIDUAL_2_NOT_RUN)

