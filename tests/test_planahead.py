"""planahead.read_duration and planahead.total — the two rules a wait total has to hold.

⚠️ AN EXTENSION NEVER ENTERS A TOTAL. It is not in the input to total() at all, which is the point
of the column pair: the page can offer "or overnight if time allows" without ever telling a cook to
allow 8 hours for a 10-minute marinade.

⚠️ A MAXIMUM EXISTS ONLY IF EVERY WAIT HAS ONE. Treating a missing max as equal to the minimum
turns "at least 2 hours" into a promise of exactly 2.
"""
import pytest

import planahead as pa


@pytest.mark.parametrize("text, want", [
    ("1 hr rise", (60, 60)),
    ("30 min", (30, 30)),
    ("8-12 hr cold proof", (480, 720)),
    ("15-20 minutes", (15, 20)),
    ("1 hr 30 min", (90, 90)),
    ("2 days", (2880, 2880)),
    ("1 week", (10080, 10080)),
    # open-ended, said three different ways
    ("at least 2 hours", (120, None)),
    ("2 hr+", (120, None)),
    ("30 min or longer", (30, None)),
    # a word that names a duration and carries no number
    ("overnight", (480, None)),
    ("over night", (480, None)),
    ("the day before", (480, None)),
    # ⚠️ NOT A DURATION. The words are kept by the caller and the numbers stay blank.
    ("until it smells right", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_read_duration(text, want):
    assert pa.read_duration(text) == want


@pytest.mark.parametrize("text, want", [
    # ⚠️ A RANGE ACROSS TWO UNITS. _TIME_SEG_RE's `hi` group only catches a bare number, so before
    #    this was handled "10 min - 1 hr" read as a flat 10 minutes and silently halved a marinade.
    ("10 min - 1 hr", (10, 60)),
    ("10 min \u2013 1 hr", (10, 60)),
    ("12 hr - 2 days", (720, 2880)),
    # the high end can be a WORD. 3 of the 72 proposals say "6 hr - overnight".
    ("6 hr \u2013 overnight", (360, 480)),
    ("4 hr \u2013 overnight", (240, 480)),
    # ⚠️ AND THE SAME SHAPE WITHOUT A SEPARATOR IS ADDITIVE, NOT A RANGE.
    ("1 hr 30 min", (90, 90)),
    ("2 hr 15 min", (135, 135)),
    # "or overnight" is an open end, not a ceiling
    ("8 hr or overnight", (480, None)),
])
def test_a_range_may_cross_units(text, want):
    assert pa.read_duration(text) == want


def test_a_range_keeps_both_ends():
    """Collapsing '8-12 hr' to either end invents precision the author did not write."""
    assert pa.read_duration("8-12 hr")[0] != pa.read_duration("8-12 hr")[1]


def test_the_total_is_the_sum_of_the_normal_minimums():
    """pepperoni-rolls: about 1 hr, then 30 min."""
    waits = [{"min_minutes": 60, "max_minutes": 60}, {"min_minutes": 30, "max_minutes": 30}]
    assert pa.total(waits) == (90, 90)


def test_one_open_ended_wait_makes_the_whole_total_open_ended():
    waits = [{"min_minutes": 480, "max_minutes": None}, {"min_minutes": 60, "max_minutes": 60}]
    assert pa.total(waits) == (540, None)
    assert pa.total_label(waits) == "9 hr+"


def test_a_wait_with_no_numbers_is_skipped_rather_than_counted_as_zero():
    waits = [{"min_minutes": 60, "max_minutes": 60}, {"min_minutes": None, "max_minutes": None}]
    assert pa.total(waits) == (60, None), "the unparsed row must not close the ceiling either"


def test_no_waits_and_no_numbers_give_no_total():
    assert pa.total([]) == (None, None)
    assert pa.total([{"min_minutes": None, "max_minutes": None}]) == (None, None)


def test_one_wait_shows_its_own_words_and_several_show_the_figure():
    """⚠️ 'overnight' MUST SURVIVE TO THE PAGE. Nobody wants to read 'Plan ahead 8 hr' on a recipe
    whose step says overnight. With several waits no one wrote the summed sentence, so the figure
    is the honest thing to print."""
    assert pa.total_label([{"min_minutes": 480, "max_minutes": None, "label": "overnight"}]) == "overnight"
    assert pa.total_label([{"min_minutes": 60, "max_minutes": 60, "label": "about 1 hr"},
                           {"min_minutes": 30, "max_minutes": 30, "label": "30 min"}]) == "1 hr 30 min"


@pytest.mark.parametrize("m, want", [
    (30, "30 min"), (60, "1 hr"), (90, "1 hr 30 min"), (480, "8 hr"),
    (1440, "1 day"), (2880, "2 days"), (None, ""),
])
def test_fmt_minutes(m, want):
    assert pa.fmt_minutes(m) == want
