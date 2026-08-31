"""build_library.mark_commonality — the tier that lets the app lead with salt and tuck epazote away.

Like the other build_library tests this cannot run the real pipeline (a rowset needs join.db at
894 MB and sources.db at 5.18 GB, neither committed nor in CI), so it tests rows in, tiers out.

⚠️ THE TWO TESTS THAT MATTER ARE THE FLOOR DIRECTION AND THE STAPLE INVERSION. A floor that could
LOWER a tier would quietly demote common ingredients that happen to be on the weight chart, and the
authored staples (salt, sugar, water) carry 0 to 1 variations, so without the explicit list the
gradient files the most ordinary things in the world with the most obscure.
"""
import build_library
from build_library import (COMMONALITY_TIERS, HAND_FLOOR, STAPLE_BASICS,
                           load_king_arthur, mark_commonality)


def _row(canonical, n_variations=0, cut_by=None):
    return {"canonical": canonical, "n_variations": n_variations, "cut_by": cut_by or []}


def _tier(canonical, n, ka=frozenset()):
    row = _row(canonical, n)
    mark_commonality([row], ka)
    return row["commonality"]


def test_the_gradient_thresholds():
    assert _tier("x", 100) == "common"
    assert _tier("x", 400) == "common"
    assert _tier("x", 99) == "everyday"
    assert _tier("x", 40) == "everyday"
    assert _tier("x", 39) == "speciality"
    assert _tier("x", 10) == "speciality"
    assert _tier("x", 9) == "obscure"
    assert _tier("x", 0) == "obscure"


def test_king_arthur_raises_a_tier():
    """water carries 0 variations and would read obscure on the gradient alone."""
    assert _tier("cake flour", 0) == "obscure", "without the chart it is obscure"
    assert _tier("cake flour", 0, frozenset({"cake flour"})) == "everyday"


def test_king_arthur_never_lowers_a_tier():
    """⚠️ THE FLOOR IS ONE-WAY. butter is on the chart AND carries 417 names."""
    assert _tier("butter x", 417, frozenset({"butter x"})) == "common", "must stay common, not drop to everyday"
    assert _tier("butter x", 60, frozenset({"butter x"})) == "everyday", "already everyday, unchanged"


def test_the_hand_floor_catches_what_the_chart_misses():
    """You count eggs rather than cupping them, so the weight chart has no row for one."""
    for name in HAND_FLOOR:
        assert name in ("egg", "oil", "pepper", "heavy cream")
        row = _row(name, 0)
        mark_commonality([row], frozenset())
        assert row["commonality"] != "obscure", f"{name} must be floored"


def test_the_staple_list_beats_a_low_gradient():
    """⚠️ salt is an authored row holding one name. No signal distinguishes it from teuk trey."""
    assert _tier("salt", 1) == "staple"
    assert _tier("water", 0) == "staple"
    assert _tier("sugar", 0) == "staple"
    assert _tier("teuk trey", 0) == "obscure", "a genuinely obscure authored row stays obscure"


def test_a_staple_stays_a_staple_when_the_gradient_is_high():
    assert _tier("milk", 510) == "staple", "the list wins over the gradient in both directions"


def test_every_kept_row_gets_a_tier_and_cut_rows_get_none():
    rows = [_row("a", 500), _row("b", 50), _row("c", 20), _row("d", 0),
            _row("gone", 999, cut_by=["hand"])]
    mark_commonality(rows, frozenset())
    assert all(r["commonality"] in COMMONALITY_TIERS for r in rows if not r["cut_by"])
    assert rows[-1]["commonality"] == "", "a cut row is not in the list, so it carries no tier"


def test_counts_are_returned_and_sum_to_the_kept_rows():
    rows = [_row("a", 500), _row("b", 50), _row("c", 20), _row("d", 0), _row("x", 9, cut_by=["hand"])]
    counts = mark_commonality(rows, frozenset())
    assert sum(counts.values()) == 4, "the cut row is not counted"


def test_matching_is_normalised_not_literal():
    """'Garlic (minced)' in the chart has to reach the 'garlic' row."""
    assert _tier("Cake Flour", 0, frozenset({"cake flour"})) == "everyday"


def test_the_real_chart_loads_and_carries_the_expected_names():
    ka = load_king_arthur()
    if not ka:
        import pytest
        pytest.skip("king-arthur-staples-v2.csv not present")
    # ⚠️ the chart's names arrive NORMALISED, so the hyphen in "All-Purpose Flour" is a space
    for name in ("water", "salt", "all purpose flour", "onion", "garlic"):
        assert name in ka, f"{name} should come off the chart"
    assert "egg" not in ka, "⚠️ eggs are counted, not cupped, which is why HAND_FLOOR exists"


def test_the_lists_are_normalised_so_they_can_actually_match():
    """⚠️ REGRESSION. A literal 'all-purpose flour' in STAPLE_BASICS normalises to
    'all purpose flour' at lookup time and would never match its own entry."""
    from build_library import norm_name
    for entry in STAPLE_BASICS | HAND_FLOOR:
        assert norm_name(entry) == entry, f"{entry!r} is not in normalised form"
    assert "all purpose flour" in STAPLE_BASICS
    assert "all-purpose flour" not in STAPLE_BASICS
    assert _tier("all-purpose flour", 7) == "staple", "the real canonical must reach the list"


def test_the_tier_order_is_the_ranking():
    assert COMMONALITY_TIERS.index("staple") < COMMONALITY_TIERS.index("common")
    assert COMMONALITY_TIERS.index("common") < COMMONALITY_TIERS.index("obscure")
    assert set(STAPLE_BASICS) & set(HAND_FLOOR) == set(HAND_FLOOR), \
        "everything hand-floored is also a stated basic, so the two lists cannot disagree"
