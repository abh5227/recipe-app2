"""The look-alike, heading-level and capitalization rules, stated against the shapes that broke them.

⚠️ EVERY TEST BELOW IS A DEFECT AN INDEPENDENT REVIEW FOUND IN THIS ROUND'S OWN WORK. They are
grouped here because they are one family: a rule that was admitted on too little evidence.
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import import_cleanup as ic  # noqa: E402


# ---- look-alike letters -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Борщ (Borscht)",
    "Молоко 200 ml",
    "сметана (sour cream)",
    "Хлеб bread",
    "Пельмени / Pelmeni",
    "Σπανακόπιτα - Spanakopita",
    "Ρίγανη oregano",
])
def test_real_cyrillic_or_greek_is_left_completely_alone(text):
    """⚠️ THE TEST USED TO BE "DOES IT CONTAIN A LATIN LETTER", AND THAT CONDEMNED EVERY ONE OF
    THESE. A transliteration in brackets, a unit, or one stray Latin character was enough, and
    clean_recipe runs this on the recipe NAME, which reaches the slug. The evidence that a text is
    really in another script is a letter the table does NOT know, because a copy-paste artifact is
    made entirely of letters that look Latin."""
    assert ic.normalize_lookalikes(text) == text


def test_the_one_corpus_artifact_is_still_repaired():
    """garlic-ginger-chicken step 2: every non-Latin character in "МАКЕ" is in the table, which is
    exactly what makes it an artifact rather than Russian."""
    assert ic.normalize_lookalikes("3. МАКЕ THE CHICKEN: Place the chicken breasts") == \
        "3. MAKE THE CHICKEN: Place the chicken breasts"


def test_the_table_does_not_carry_the_pair_its_own_comment_rejects():
    """The header says Cyrillic У against Latin Y is "close but not identical" and must not be in
    the table. It was."""
    assert "у" not in ic.LOOKALIKE_LETTERS
    assert "ν" not in ic.LOOKALIKE_LETTERS, "Greek nu is not a Latin v"


def test_a_text_with_no_latin_at_all_is_untouched():
    assert ic.normalize_lookalikes("Борщ") == "Борщ"


# ---- the heading level, and the predicate rule 7 actually wants ---------------------------------

@pytest.mark.parametrize("label", ["Deseed", "Simmer", "Assembly", "Tomatoes"])
def test_a_plain_caption_does_not_name_a_component(label):
    """⚠️ THE QUESTION rule 7 ASKS. It was asking label_level with no context, which since Andy's
    ruling returns SECTION for everything, so its guard was never true and the sweep promoted every
    level-2 heading in the corpus. Measured on a chained copy: level 2 went 112 to 2.

    ⚠️ "30 min cool" LEFT THIS LIST ON 2026-10-08. It still names no component, which the test below
    keeps asserting, and it IS a stage, so its level answer is now SECTION."""
    assert ic.names_a_component(label) is False
    assert ic.label_level(label, section_above=True) == ic.SUBHEADING


def test_a_duration_caption_names_no_component_and_is_still_a_section():
    """The two questions are separate, and "30 min cool" answers them differently: it is not a
    component (rule 7 leaves its text alone) and it IS a stage (its level is 1)."""
    assert ic.names_a_component("30 min cool") is False
    assert ic.names_a_stage("30 min cool") is not None
    assert ic.label_level("30 min cool", section_above=True) == ic.SECTION


@pytest.mark.parametrize("label", ["Make the dough", "For the sauce", "To make the icing",
                                   "If using dried chickpeas",
                                   "While the dough rests, make the filling"])
def test_a_component_name_is_a_section_either_way(label):
    assert ic.names_a_component(label) is True
    assert ic.label_level(label, section_above=True) == ic.SECTION


@pytest.mark.parametrize("label", ["Make the cut shallow",
                                   "While stirring, make sure the heat stays low",
                                   "While cooling, make a note of the time"])
def test_a_caption_that_merely_starts_with_make_is_not_a_component(label):
    """"Make the X" names a component only when X is a thing. These are captions on one step."""
    assert ic.names_a_component(label) is False


# ---- the author's numbering, and the ranges it must refuse --------------------------------------

@pytest.mark.parametrize("steps", [
    ["1 - 2 days ahead, make the stock and chill it.",
     "2 - 3 hours before serving, warm the stock through."],
    ["1 – 2 tablespoons of oil should coat the pan.",
     "2 – 3 minutes per side is enough."],
    ["1: 2 is the ratio of rice to water.", "2 - 3 cups of stock, as needed."],
])
def test_a_range_is_never_read_as_a_list_number(steps):
    """⚠️ A BARE DASH OR COLON AFTER THE NUMBER IS A RANGE, NOT A LIST MARKER. Read as one, the
    first half was stripped and a quantity silently became its top end. A number that opens a list
    is written "1." or "1)"."""
    assert ic.strip_author_numbers(steps) == steps


@pytest.mark.parametrize("steps, first", [
    (["1. Preheat the oven.", "2. Whisk the eggs.", "3. Bake it."], "Preheat the oven."),
    (["1) Preheat the oven.", "2) Whisk the eggs."], "Preheat the oven."),
    (["Step 1 - Preheat the oven.", "Step 2 - Whisk the eggs."], "Preheat the oven."),
    (["Step 1: Preheat the oven.", "Step 2: Whisk the eggs."], "Preheat the oven."),
])
def test_real_author_numbering_still_comes_off(steps, first):
    """The dash and the colon are allowed when the word "Step" says what the number is."""
    assert ic.strip_author_numbers(steps)[0] == first


# ---- first letters ------------------------------------------------------------------------------

def test_an_author_s_letter_list_marker_is_stepped_over_not_capitalized():
    """⚠️ karak-chai's steps 8 to 10 read "a. Bring the pot to a boil" under the author's own
    heading. Capitalizing the marker rewrites their list, which apply_label_rules' rule 6 has always
    refused to do. The letter after it is the one considered."""
    assert ic.capitalize_first_visible("a. Bring the pot to a boil") == "a. Bring the pot to a boil"
    assert ic.capitalize_first_visible("b. remove the pot") == "b. Remove the pot"


def test_an_author_s_number_is_stepped_over_and_a_measurement_is_not():
    assert ic.capitalize_first_visible("1. bring a salted water to a boil") == \
        "1. Bring a salted water to a boil"
    for measurement in ("30 minutes before you start cooking", "180 degrees. This makes",
                        "24 pieces (6 short rows)"):
        assert ic.capitalize_first_visible(measurement) == measurement


# ---- ingredient names, and the library that answers for them ------------------------------------

@pytest.mark.parametrize("name, canonical, want", [
    ("All-Purpose Flour", "all-purpose flour", "all-purpose flour"),
    ("Fennel Seeds", "fennel seeds", "fennel seeds"),
    ("Cream Cheese, softened", "cream cheese", "cream cheese, softened"),
    ("Dried Oregano (Greek or Turkish)", "dried oregano", "dried oregano (Greek or Turkish)"),
    ("Asian pear, finely grated", "Asian pear", "Asian pear, finely grated"),
])
def test_the_library_s_own_capitalization_wins_for_the_part_it_names(name, canonical, want):
    """⚠️ THE LOOKUP READ ingredient_id, WHICH MIGRATION 046 EMPTIED, so this rule never fired once:
    0 of 3,572 lines carry that column and 2,851 carry catalog_id. And taking only the canonical's
    FIRST LETTER would leave "cream Cheese, softened", so the canonical replaces the prefix it
    names and the author's tail is untouched."""
    got, verdict, _why = ic.ingredient_name_case(name, canonical=canonical)
    assert got == want
    assert verdict in (ic.CASE_LINKED, ic.CASE_PROPER)


def test_a_library_entry_that_renames_the_ingredient_decides_nothing():
    """"Crimini Mushrooms" against a canonical of "edible mushroom" is the library answering a
    different question, so the line falls through to the review list rather than being rewritten."""
    got, verdict, _why = ic.ingredient_name_case("Crimini Mushrooms, Sliced",
                                                 canonical="edible mushroom")
    assert got == "Crimini Mushrooms, Sliced"
    assert verdict == ic.CASE_UNCERTAIN


def test_a_title_cased_name_with_no_library_entry_waits_for_a_decision():
    got, verdict, _why = ic.ingredient_name_case("Whole Tellicherry Black Peppercorns",
                                                 lowercase_elsewhere=True)
    assert got == "Whole Tellicherry Black Peppercorns"
    assert verdict == ic.CASE_UNCERTAIN
