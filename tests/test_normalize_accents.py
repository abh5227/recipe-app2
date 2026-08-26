"""weights.normalize is the lookup key for the weight chart and the first reduction the
library resolver runs, so a letter it deletes is an ingredient nothing can reach.

The punctuation strip is [^a-z0-9 ], which put every accented letter outside the class and
replaced it with a space: jalapeño -> 'jalape o', purée -> 'pur e', crème -> 'cr me',
café -> 'caf'. The library index carries both the accented and the plain spelling for those
words, so the accented line missed while the plain one would have matched.

⚠️ NFD, not NFKD. The compatibility forms decompose a vulgar fraction too, so NFKD reads
"juice of ½ lemon" as "juice of 1⁄2 lemon" and three currently-matching lines went to a miss
when that was measured. The fraction cases below pin that.
"""
import pytest

import build_db
import weights


@pytest.mark.parametrize("raw,expected", [
    ("jalapeño", "jalapeno"), ("jalapeños", "jalapenos"), ("Jalapeño", "jalapeno"),
    ("purée", "puree"), ("crème", "creme"), ("sauté", "saute"), ("café", "cafe"),
    ("crème fraîche", "creme fraiche"), ("piña colada", "pina colada"),
    ("açaí", "acai"), ("Gruyère", "gruyere"), ("jalapeño, seeded", "jalapeno"),
])
def test_accents_fold_to_the_base_letter(raw, expected):
    assert weights.normalize(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("garlic", "garlic"), ("olive oil, divided", "olive oil"),
    ("Sugar (granulated white)", "sugar granulated white"),
    ("all-purpose flour", "all purpose flour"), ("", ""),
])
def test_plain_names_are_unchanged(raw, expected):
    assert weights.normalize(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    # NFKD would decompose these into "1/2" and friends and change the key. NFD must not.
    ("juice of ½ lemon", "juice of lemon"), ("1½ tbsp sugar", "1 tbsp sugar"),
    ("¼ cup milk", "cup milk"), ("⅓ cup oil", "cup oil"),
])
def test_vulgar_fractions_are_not_decomposed(raw, expected):
    assert weights.normalize(raw) == expected


def test_base_name_inherits_the_fold():
    """base_name calls normalize, so the fold has to reach it without a second rule."""
    assert weights.base_name("Purée (canned)") == "puree"
    assert weights.base_name("jalapeño (fresh)") == "jalapeno"


def test_fold_leaves_letters_that_carry_no_combining_mark():
    """o-slash, ae and eszett decompose to nothing under NFD, so they keep falling through
    to the punctuation strip exactly as before. Pinned so a later switch to NFKD is loud."""
    assert weights.fold_accents("ø") == "ø"
    assert weights.fold_accents("æ") == "æ"
    assert weights.fold_accents("ß") == "ß"


def test_the_weight_chart_has_no_accented_name():
    """⚠️ THE INVARIANT THAT MAKES THIS FIX SAFE. build_db writes normalize(display_name)
    into ingredient_weights.lookup_key, so a key STORED by the old function is queried by
    the new one. That only holds while no chart name carries an accent. If a later chart
    row does, recipes.db has to be rebuilt or the row stops matching."""
    if not build_db.WEIGHTS_CSV.exists():
        pytest.skip("king-arthur-staples-v2.csv not present")
    text = build_db.WEIGHTS_CSV.read_text(encoding="utf-8")
    assert [c for c in text if ord(c) > 127] == []
