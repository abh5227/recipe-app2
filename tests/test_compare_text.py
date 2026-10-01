"""units.compare_text — the question "did the cook change this", for a name, a note, a step or a
heading.

⚠️ CASE AND PUNCTUATION ARE IGNORED FOR THE MARK, NOT FOR THE SAVE. The edit is stored exactly as
typed either way. This decides only whether the recipe page says the cook changed something, and
capitalizing a sentence or adding a full stop is not a change to the recipe.

⚠️ PUNCTUATION INSIDE A NUMBER ALWAYS COUNTS, which is why this is not a one-line strip. The closest
pair in the corpus is spiced-scallops' "simmer for 4 6 minutes" becoming "simmer for 4-6 minutes", a
real correction that turns two loose numbers into a range.
"""
import pytest

import units


def same(a, b):
    return units.compare_text(a) == units.compare_text(b)


@pytest.mark.parametrize("a, b", [
    ("Mix well", "mix well"),                       # case
    ("Mix well", "Mix well."),                      # a terminal full stop
    ("Mix well!", "Mix well?"),                     # swapped terminal punctuation
    ("Add salt, to taste", "Add salt to taste"),    # a comma between words
    ("sugar (packed)", "sugar packed"),             # brackets
    ("skin-on and bone-in", "skin on and bone in"),  # hyphens between WORDS
    ("don't", "dont"),                              # an apostrophe is dropped, never spaced
    ("don\u2019t", "don't"),                         # a curly apostrophe for a straight one
    ("a  b", "A B"),                                # whitespace and case together
    ("  padded  ", "padded"),
    (None, ""),                                     # null is not an edit of empty
    ("1,000 g", "1000 g"),                          # a thousands comma is the same quantity
    ("Finish with COLD butter", "finish with cold butter"),
])
def test_these_are_not_changes(a, b):
    assert same(a, b)


@pytest.mark.parametrize("a, b", [
    ("1.5 cups", "15 cups"),                        # a decimal point
    ("1/2 cup", "12 cup"),                          # a fraction slash
    ("2-3 min", "23 min"),                          # a range dash
    ("2–3 min", "23 min"),                     # an en dash range
    ("350°F", "350F"),                         # a degree sign
    ("simmer for 4 6 minutes", "simmer for 4-6 minutes"),   # the real corpus case
    ("Mix well", "Mix badly"),                      # an actual word change
    ("chicken thigh fillets", "chicken thigh"),     # a dropped word
    ("", "something"),
])
def test_these_ARE_changes(a, b):
    assert not same(a, b)


def test_an_amount_is_not_compared_by_this_function():
    """⚠️ AMOUNTS KEEP THEIR STRICT COMPARISON. compare_key is what answers "did the amount change",
    through canon_unit_str + normalize_fractions, and loosening text must not have reached it. A
    half is not a twelve on either path, but it is compare_key that guards the ledger column."""
    assert units.compare_key("1/2 cup") != units.compare_key("12 cup")
    assert units.compare_key("1 teaspoon") == units.compare_key("1 tsp")


def test_the_loosening_is_idempotent():
    """A comparison form that is not stable under a second pass would make two equal strings
    disagree depending on which side had already been normalized."""
    for s in ["Mix well.", "1.5 cups", "350°F", "a, b; c", "1,000 g", "2-3 min"]:
        once = units.compare_text(s)
        assert units.compare_text(once) == once, s


@pytest.mark.parametrize("dash", ["-", "‐", "‑", "‒", "–", "—",
                                  "―", "−", "－"])
def test_every_dash_a_paste_produces_keeps_a_range_apart_from_two_loose_numbers(dash):
    """⚠️ THE EXCEPTION IS ONLY WORTH ANYTHING IF IT COVERS THE CHARACTER THAT ARRIVES.

    Three dashes were listed and six were not. With any of the six, "simmer for 4-6 minutes" compared
    equal to "simmer for 4 6 minutes", which is the exact spiced-scallops correction the number
    exception exists to save, undone by one character nobody can see. A PDF, a Word document and
    several web pages emit these. 0 of the 13,708 text values in the corpus carry one today, so this
    is the importer's path rather than the corpus's.
    """
    assert units.compare_text(f"simmer for 4{dash}6 minutes") != units.compare_text("simmer for 4 6 minutes")
    # and the same dash BETWEEN WORDS still folds, because there it does separate them
    assert units.compare_text(f"skin{dash}on") == units.compare_text("skin on")


def test_a_decimal_point_counts_even_with_no_digit_in_front_of_it():
    """⚠️ A TENFOLD QUANTITY CHANGE WAS GOING UNMARKED. The test needed a digit on BOTH sides, so at
    index 0 `prev` was the empty string and ".5 cup" compared equal to "5 cup". The same held after
    any non-digit, so "add .5 tsp" equalled "add 5 tsp"."""
    assert units.compare_text(".5 cup") != units.compare_text("5 cup")
    assert units.compare_text("add .5 tsp of salt") != units.compare_text("add 5 tsp of salt")
    assert units.compare_text(".5") != units.compare_text("5")
    # a full stop that ENDS a sentence is never followed by a digit with no space, so it still folds
    assert units.compare_text("Serve now. 5 minutes later") == units.compare_text("Serve now 5 minutes later")
    assert units.compare_text("Mix it.") == units.compare_text("mix it")
