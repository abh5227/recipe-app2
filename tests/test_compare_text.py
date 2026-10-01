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
