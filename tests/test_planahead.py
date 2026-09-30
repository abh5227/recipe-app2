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
    is the honest thing to print.

    ⚠️ THE WORD NOW ARRIVES WITH ITS FIGURE BESIDE IT, which is a decided change and not a drift.
    This asserted a bare "overnight", on the ground above. A cook cannot plan around a word, and the
    480 minutes were already stored, so the figure was being withheld for no gain. The word is still
    there, which is what this test was protecting."""
    assert pa.total_label([{"min_minutes": 480, "max_minutes": None, "label": "overnight"}]) \
        == "8 hr+ (overnight)"
    assert pa.total_label([{"min_minutes": 60, "max_minutes": 60, "label": "about 1 hr"},
                           {"min_minutes": 30, "max_minutes": 30, "label": "30 min"}]) == "1 hr 30 min"


# ---- display_label: an overnight that is the FLOOR reads as a figure (Round A, item 5) -----------

@pytest.mark.parametrize("label, lo, hi, want", [
    # A: the word IS the minimum. 14 stored waits.
    ("overnight", 480, None, "8 hr+ (overnight)"),
    ("at least overnight", 480, None, "8 hr+ (overnight)"),
    ("8 hr or overnight", 480, None, "8 hr+ (overnight)"),
    # ⚠️ THE AUTHOR'S OWN WORD IS KEPT. "the day before" is not "overnight" to someone reading it at
    #    nine in the evening, so it is not normalized to one.
    ("the day before", 480, None, "8 hr+ (the day before)"),
    # B: the word is the CEILING and 4 hr is the floor. Rewriting it would lose the floor.
    ("4 hr \u2013 overnight", 240, 480, "4 hr \u2013 overnight"),
    ("6 hr \u2013 overnight", 360, 480, "6 hr \u2013 overnight"),
    ("3 hr \u2013 overnight", 180, 480, "3 hr \u2013 overnight"),
    # No overnight word at all: untouched, whatever its shape.
    ("8\u201312 hr", 480, 720, "8\u201312 hr"),
    ("2 hr+", 120, None, "2 hr+"),
    ("10 min \u2013 1 hr", 10, 60, "10 min \u2013 1 hr"),
])
def test_display_label(label, lo, hi, want):
    assert pa.display_label({"label": label, "min_minutes": lo, "max_minutes": hi}) == want


def test_display_label_keeps_the_words_when_there_are_no_minutes():
    """A wait whose text carried no duration has nothing to print a figure from."""
    assert pa.display_label({"label": "overnight", "min_minutes": None, "max_minutes": None}) \
        == "overnight"


def test_display_label_never_touches_the_stored_label():
    w = {"label": "overnight", "min_minutes": 480, "max_minutes": None}
    pa.display_label(w)
    assert w["label"] == "overnight"


@pytest.mark.parametrize("m, want", [
    (30, "30 min"), (60, "1 hr"), (90, "1 hr 30 min"), (480, "8 hr"),
    (1440, "1 day"), (2880, "2 days"), (None, ""),
])
def test_fmt_minutes(m, want):
    assert pa.fmt_minutes(m) == want


# ---------------------------------------------------------------------------------------------
# migration 050: only an unconditional wait reaches the total.
# ---------------------------------------------------------------------------------------------

def _w(mn, mx, when="always", label="x"):
    return {"min_minutes": mn, "max_minutes": mx, "when_kind": when, "label": label}


def test_a_wait_with_no_when_counts():
    """Every row written before 050 has no when_kind in hand, and all of them are unconditional."""
    assert pa.counts({"min_minutes": 60}) is True


@pytest.mark.parametrize("when, want", [("always", True), ("optional", False), ("only_if", False)])
def test_counts(when, want):
    assert pa.counts({"when_kind": when}) is want


def test_a_conditional_wait_is_left_out_of_the_total():
    assert pa.total([_w(60, 60), _w(480, 480, "optional")]) == (60, 60)
    assert pa.total([_w(60, 60), _w(45, 60, "only_if")]) == (60, 60)


def test_all_conditional_means_no_total_at_all():
    """Not a total of zero. A recipe that only MIGHT soak has nothing to plan around."""
    assert pa.total([_w(480, 480, "optional")]) == (None, None)
    assert pa.total_label([_w(480, 480, "optional", "8 hr")]) == ""


def test_an_open_ended_conditional_wait_does_not_open_the_total():
    """⚠️ THE BUG THIS GUARDS. A conditional wait with no ceiling would have made a closed total
    open-ended, turning '1 hr 30 min' into '1 hr 30 min+' on the strength of a step a cook skips."""
    assert pa.total([_w(60, 60), _w(120, None, "optional")]) == (60, 60)


def test_one_counted_wait_beside_a_conditional_one_keeps_its_own_words():
    waits = [_w(720, 1080, "always", "12-18 hr"), _w(45, 60, "only_if", "45-60 min")]
    assert pa.total_label(waits) == "12-18 hr"


def test_two_counted_waits_beside_a_conditional_one_show_the_figure():
    waits = [_w(60, 60, "always", "1 hr"), _w(30, 30, "always", "30 min"),
             _w(480, 480, "optional", "8 hr")]
    assert pa.total(waits) == (90, 90)
    assert pa.total_label(waits) == "1 hr 30 min"


# ---------------------------------------------------------------------------------------------
# "up to X" is a CEILING. Found by re-reading the v2 proposals for round 3.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("up to 1 week", (0, 10080)),
    ("up to 3 days", (0, 4320)),
    ("up to 48 hr", (0, 2880)),
    ("no more than 2 hr", (0, 120)),
    ("at most 30 min", (0, 30)),
])
def test_up_to_is_a_ceiling_not_a_floor(text, want):
    """⚠️ THE BUG. 'up to 1 week' read as (10080, 10080), which says a week is REQUIRED where the
    recipe says a week is the most. 22 of the v2 proposal rows carry this shape. All 22 are storage,
    which reaches no total, so nothing shipped wrong and the first wait saying 'chill up to 2 hours'
    would have told a cook to set aside 2 hours for it."""
    assert pa.read_duration(text) == want


def test_both_markers_together_state_a_real_range():
    """'at least 12 hours and up to 48' has a floor AND a ceiling, and neither modifier wins."""
    assert pa.read_duration("at least 12 hr and up to 48 hr") == (720, 2880)


def test_a_ceiling_only_wait_adds_nothing_to_the_minimum_total():
    """A floor of 0 is the point: a wait that may be skipped entirely costs no planning time, and
    the ceiling still sums so a maximum stays honest."""
    assert pa.total([_w(60, 60), _w(0, 120)]) == (60, 180)
