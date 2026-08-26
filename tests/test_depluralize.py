"""depluralize is the library build's only stemmer and the resolver's last resort, so a
word it mangles is a name nothing can reach.

The -ves case shipped as a blanket "ves" -> "f" and was wrong two ways at once. A word
whose singular ends in -fe took -f (knives -> 'knif'), and a word that is simply an -s
plural was cut three letters short (cloves -> 'clof', olives -> 'olif'). Measured cost on
the recipe corpus: 46 lines reading 'garlic cloves' reached no row at all, the single
largest miss, while 'garlic clove' sits on Q28966859.
"""
import pytest

import build_library


# (plural, singular) — the -ves words that really are -f or -fe plurals. These were already
# right for the -f half and must stay right.
VES_TO_F = [
    ("leaves", "leaf"), ("halves", "half"), ("loaves", "loaf"), ("shelves", "shelf"),
    ("calves", "calf"), ("wolves", "wolf"), ("elves", "elf"), ("thieves", "thief"),
    ("hooves", "hoof"), ("scarves", "scarf"),
]

# The -fe half, which the blanket rule truncated: knives -> 'knif', not 'knife'.
VES_TO_FE = [("knives", "knife"), ("lives", "life"), ("wives", "wife")]

# Words where "ves" is not a pluralized -f/-fe at all. These just drop the s, and the
# blanket rule mangled every one of them.
VES_ORDINARY = [
    ("cloves", "clove"), ("gloves", "glove"), ("olives", "olive"), ("chives", "chive"),
    ("doves", "dove"), ("stoves", "stove"), ("sleeves", "sleeve"),
]

# Endings the rule never touched, kept here so a change to the -ves branch cannot move them.
UNTOUCHED = [
    ("tomatoes", "tomato"), ("potatoes", "potato"), ("onions", "onion"),
    ("berries", "berry"), ("dishes", "dish"), ("glasses", "glass"), ("boxes", "box"),
]


@pytest.mark.parametrize("plural,singular", VES_TO_F + VES_TO_FE + VES_ORDINARY + UNTOUCHED)
def test_depluralize_reaches_the_real_singular(plural, singular):
    assert build_library.depluralize(plural) == singular


@pytest.mark.parametrize("plural,singular", [
    # The suffix is matched on the LAST WORD, so a compound name stems too. 'garlic cloves'
    # is the one that cost 46 recipe lines.
    ("garlic cloves", "garlic clove"), ("bay leaves", "bay leaf"),
    ("curry leaves", "curry leaf"), ("kaffir lime leaves", "kaffir lime leaf"),
    ("black olives", "black olive"),
])
def test_depluralize_stems_the_last_word_of_a_compound(plural, singular):
    assert build_library.depluralize(plural) == singular


@pytest.mark.parametrize("word", ["asparagus", "bus", "analysis", "ss"])
def test_depluralize_declines_a_word_that_is_not_a_plural(word):
    assert build_library.depluralize(word) is None


def test_every_ves_singular_entry_really_ends_in_f_or_fe():
    """The table exists because shape cannot separate cloves from wolves. Membership is the
    rule, so an entry that does not end in -f or -fe would be a typo rather than a plural."""
    wrong = {p: s for p, s in build_library.VES_SINGULAR.items() if not s.endswith(("f", "fe"))}
    assert wrong == {}


def test_every_ves_singular_key_ends_in_ves():
    wrong = [p for p in build_library.VES_SINGULAR if not p.endswith("ves")]
    assert wrong == []
