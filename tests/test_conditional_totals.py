"""The second Total: what a recipe costs if you take a conditional path.

⚠️ THE MAIN TOTAL IS UNCHANGED, WHICH IS THE POINT. An optional soak is not time a cook has to set
aside, so planahead.counts keeps it out of the figure. A cook who IS going to soak the beans still
has to know what that costs, and working it out from a Total and a bullet is arithmetic the page can
do for them.

tests/fixtures/conditional-total-cases.json is the shared half: this file asserts the FIGURES and
tests/js/conditional-total.test.js asserts the markup the client builds from them, so the one
implementation and its rendering cannot drift apart.
"""
import json
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import planahead  # noqa: E402

FIX = json.loads((BASE / "tests" / "fixtures" / "conditional-total-cases.json").read_text())


@pytest.mark.parametrize("case", FIX["cases"], ids=[c["name"] for c in FIX["cases"]])
def test_the_fixture_is_what_planahead_actually_produces(case):
    got = planahead.conditional_totals(case["recipe"], case["waits"])
    assert got == case["expected"]


def _w(**kw):
    base = {"kind": "soaking", "label": "", "min_minutes": None, "max_minutes": None,
            "when_kind": "always", "when_label": None, "ext_label": None}
    base.update(kw)
    return base


RECIPE = {"prep_time": "20 min", "cook_time": "1 hr", "total_time": None}


def test_the_main_total_does_not_move():
    """⚠️ THE RULE THIS FEATURE MUST NOT BREAK. The conditional wait is still excluded from the
    Total, which is what planahead.counts has always said."""
    waits = [_w(min_minutes=480, max_minutes=600, when_kind="optional", label="8-10 hr")]
    assert planahead.recipe_total(RECIPE, waits) == planahead.recipe_total(RECIPE, [])


def test_an_optional_wait_is_named_by_its_kind():
    got = planahead.conditional_totals(RECIPE, [
        _w(kind="soaking", min_minutes=480, max_minutes=600, when_kind="optional")])
    assert got == [{"label": "9 hr 20 min+", "when": "if you soak"}]


def test_an_only_if_wait_is_named_by_the_author_s_own_words():
    """⚠️ NOTHING A RULE INVENTS BEATS THE AUTHOR'S CONDITION. when_label was written for this exact
    recipe, so it is printed as written."""
    got = planahead.conditional_totals(RECIPE, [
        _w(kind="resting", min_minutes=30, max_minutes=30, when_kind="only_if",
           when_label="the dough was refrigerated ahead")])
    assert got == [{"label": "1 hr 50 min", "when": "if the dough was refrigerated ahead"}]


def test_an_only_if_with_no_condition_still_reads_as_a_sentence():
    got = planahead.conditional_totals(RECIPE, [
        _w(min_minutes=30, max_minutes=30, when_kind="only_if", when_label=None)])
    assert got == [{"label": "1 hr 50 min", "when": "on that path"}]


def test_two_conditionals_give_two_lines_not_four_combinations():
    """⚠️ ONE LINE PER CONDITIONAL WAIT. Measured over the 300: exactly one recipe carries two
    (no-knead-bread), and two lines read as two choices a cook makes one at a time, which is what
    they are. A combined line would be a third figure for a path nobody described."""
    got = planahead.conditional_totals(RECIPE, [
        _w(kind="soaking", min_minutes=480, max_minutes=480, when_kind="optional"),
        _w(kind="resting", min_minutes=30, max_minutes=30, when_kind="only_if",
           when_label="chilled")])
    assert [g["when"] for g in got] == ["if you soak", "if chilled"]


def test_an_alongside_wait_is_not_a_conditional_path():
    """It is the same path with something happening next to it, not a longer one."""
    assert planahead.conditional_totals(RECIPE, [
        _w(min_minutes=60, max_minutes=60, when_kind="alongside")]) == []


def test_a_counted_wait_is_in_the_base_the_conditional_is_added_to():
    """The second total has to agree with the first about everything except the condition."""
    waits = [_w(kind="soaking", min_minutes=480, when_kind="always", label="overnight"),
             _w(kind="resting", min_minutes=60, max_minutes=60, when_kind="optional")]
    got = planahead.conditional_totals({"prep_time": "10 min", "cook_time": "2 hr",
                                        "total_time": None}, waits)
    assert got == [{"label": "11 hr 10 min+", "when": "if you rest"}]


def test_a_zero_floor_conditional_gets_no_line():
    """⚠️ SAYING NOTHING BEATS SAYING EITHER ANSWER. no-knead-bread's optional cold rise is stored
    0 to 4320 ("up to 3 days"), so the floor form would print the Total again and the ceiling form
    "73 hr 10 min". The wait is still in the plan-ahead breakdown in the author's own words."""
    assert planahead.conditional_totals(RECIPE, [
        _w(kind="rising", min_minutes=0, max_minutes=4320, when_kind="optional")]) == []


def test_no_prep_or_cook_means_no_second_total():
    assert planahead.conditional_totals({"prep_time": None, "cook_time": "30 min"}, [
        _w(min_minutes=120, max_minutes=120, when_kind="optional")]) == []


def test_the_base_is_the_figure_the_page_prints():
    """⚠️ A READER SUBTRACTS ONE LINE FROM THE OTHER. The second Total reads as "the Total, plus
    this", so it has to be anchored to whatever the Total actually shows. no-knead-bread STATES
    2 hr 45 min and that figure already includes its rise, so computing from prep + cook instead
    would put two figures on the page whose difference is not the wait."""
    recipe = {"prep_time": "5 min", "cook_time": "40 min", "total_time": "2 hr 45 min"}
    waits = [_w(kind="resting", min_minutes=45, max_minutes=60, when_kind="only_if",
                when_label="chilled")]
    assert planahead.recipe_total(recipe, waits)[0] == "2 hr 45 min"
    assert planahead.conditional_totals(recipe, waits) == [
        {"label": "3 hr 30 min+", "when": "if chilled"}]
