"""An author's total cannot contain waits that alone take longer than it.

⚠️ THE CASE ANDY FOUND ON :8005. earl-grey-tea-cake states "Total 1 hr" and carries a rest of
1 hr 30 min that always applies, so the page printed "Total 1 hr" with "Plan ahead 1 hr 30 min+"
directly under it. Two figures that cannot both describe the same recipe.

⚠️ AND IT IS THE ONLY THING THE PAGE MAY SETTLE ON ITS OWN, WHICH IS WHY THE RULE HAS THREE
ANSWERS AND NOT TWO. A stated total long enough to hold the waits may or may not have counted
them, and nothing on the page can tell. The author's figure stands there and the recipe goes on a
list for a person. A rule that guessed would silently rewrite a figure the author got right.

Measured over live's 300, read only: 1 excludes, 1 unclear, 1 includes, 1 already decided by
recipes.total_includes_waits, and 296 with no question to answer.
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import planahead                                                               # noqa: E402


def _w(minutes, **kw):
    base = {"kind": "resting", "label": "", "min_minutes": minutes, "max_minutes": None,
            "when_kind": "always", "when_label": None, "ext_label": None}
    base.update(kw)
    return base


def _r(**kw):
    base = {"prep_time": None, "cook_time": None, "total_time": None,
            "total_includes_waits": None}
    base.update(kw)
    return base


# ---- case a: the stated total is shorter than the waits that always apply ----------------------

EARL_GREY = (_r(total_time="1 hr"), [_w(90)])


def test_a_total_shorter_than_its_own_waits_excludes_them():
    verdict, stated, waits = planahead.stated_total_verdict(*EARL_GREY)
    assert (verdict, stated, waits) == (planahead.STATED_EXCLUDES, 60, 90)


def test_the_page_adds_the_waits_and_says_so():
    assert planahead.recipe_total(*EARL_GREY) == ("2 hr 30 min+", planahead.INCLUDES_WAITS_NOTE)


def test_the_author_s_own_figure_stays_on_the_page():
    assert planahead.author_total_note(*EARL_GREY) == "Author's total: 1 hr, before the waits"


def test_the_author_s_line_appears_in_no_other_case():
    """⚠️ THE LINE IS THE FOOTNOTE TO AN OVERRULED TOTAL AND NOTHING ELSE. On a recipe whose total
    was never touched it would be telling the cook that a figure differs from itself."""
    for recipe, waits in (
            (_r(total_time="3 hr"), [_w(90)]),                       # includes, by the waits alone
            (_r(total_time=None, prep_time="10 min", cook_time="20 min"), [_w(90)]),   # computed
            (_r(total_time="1 hr"), []),                             # no waits at all
            (_r(total_time="1 hr"), [_w(90, when_kind="optional")]),  # a wait that may be skipped
    ):
        assert planahead.author_total_note(recipe, waits) is None, (recipe, waits)


def test_an_open_ended_stated_total_keeps_its_open_end():
    """⚠️ A TRAILING "+" IS THE OPEN END AND clock_minutes CANNOT SEE IT, which is the rule the
    second Total already follows. Reading the label back has to preserve it or the new figure
    states a ceiling the recipe never had."""
    label, note = planahead.recipe_total(_r(total_time="1 hr+"), [_w(90)])
    assert label == "2 hr 30 min+" and note == planahead.INCLUDES_WAITS_NOTE


def test_only_the_waits_that_always_apply_are_added():
    """An optional soak is not time a cook has to set aside, so it cannot make a stated total
    impossible either. planahead.counts is the one rule for that and this reads it."""
    # An optional 90 min wait beside a 30 min one that always applies. prep and cook are stated so
    # the verdict is a definite one rather than the unanswerable middle.
    recipe = _r(total_time="1 hr", prep_time="10 min", cook_time="5 min")
    waits = [_w(90, when_kind="optional"), _w(30)]
    assert planahead.stated_total_verdict(recipe, waits) == (planahead.STATED_INCLUDES, 60, 30)
    assert planahead.recipe_total(recipe, waits) == ("1 hr", None)
    # ⚠️ AND THE OPTIONAL ONE ALONE CANNOT MAKE A TOTAL IMPOSSIBLE. Counting it here would read
    #    2 hr 30 min of waits against a stated 1 hr and overrule a figure that is perfectly right.
    only_optional = _r(total_time="1 hr", prep_time="10 min", cook_time="5 min")
    assert planahead.stated_total_verdict(only_optional, [_w(90, when_kind="optional")])[0] \
        == planahead.STATED_NO_QUESTION


# ---- case b: long enough to hold them, short enough that it might not --------------------------

def test_a_total_between_the_waits_and_prep_plus_cook_plus_waits_is_unclear():
    recipe = _r(total_time="25 min", prep_time="15 min", cook_time="10 min")
    waits = [_w(15)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_UNCLEAR
    # unchanged, and no author's line, because nothing was overruled
    assert planahead.recipe_total(recipe, waits) == ("25 min", None)
    assert planahead.author_total_note(recipe, waits) is None


def test_a_missing_prep_or_cook_is_unclear_and_never_settled():
    """⚠️ UNANSWERABLE IS THE UNCLEAR ANSWER, NEVER THE SETTLED ONE, which is the direction every
    other guard in this repo fails in. all-butter-pie-crust states 1 hr 15 min with a 1 hr chill
    and no cook time, so the upper bound cannot be computed at all."""
    recipe = _r(total_time="1 hr 15 min", prep_time="15 min", cook_time=None)
    waits = [_w(60)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_UNCLEAR
    assert planahead.recipe_total(recipe, waits) == ("1 hr 15 min", None)


# ---- case c, and the decision that ends the question -------------------------------------------

def test_a_total_that_fits_prep_plus_cook_plus_waits_is_left_alone():
    recipe = _r(total_time="2 hr 45 min", prep_time="5 min", cook_time="40 min")
    waits = [_w(120)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_INCLUDES
    assert planahead.recipe_total(recipe, waits) == ("2 hr 45 min", None)


@pytest.mark.parametrize("ruling", [0, 1])
def test_a_recorded_decision_ends_the_question_in_both_directions(ruling):
    """⚠️ total_includes_waits IS A PERSON'S ANSWER TO EXACTLY THIS. A recipe carrying one is never
    re-derived and never put on a list asking for a decision that already exists. miso-tofu-recipe
    is the one row in the 300 that has one, a 0, which is why its Total has read
    "40 min+ (incl. plan ahead)" since migration 058."""
    recipe = _r(total_time="25 min", prep_time="15 min", cook_time="10 min",
                total_includes_waits=ruling)
    waits = [_w(15)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_NO_QUESTION
    assert planahead.author_total_note(recipe, waits) is None


def test_an_explicit_ruling_of_one_holds_a_total_that_could_not_contain_its_waits():
    """The sharp corner of the rule above: a person has said the author counted the waits, and
    arithmetic disagrees. The person wins, because the column exists to be the answer."""
    recipe = _r(total_time="1 hr", total_includes_waits=1)
    assert planahead.recipe_total(recipe, [_w(90)]) == ("1 hr", None)


# ---- the survey that hands the unclear ones over ------------------------------------------------

def test_the_survey_lists_the_unclear_case_and_nothing_else(tmp_path, monkeypatch):
    """⚠️ RUN, NOT READ. tests/test_corpus_passes.py's lesson: a check that does not execute the
    script cannot see the script."""
    import sqlite3
    sys.path.insert(0, str(BASE / "scripts"))
    import migrate as migrate_mod
    import scan_total_vs_waits

    db = tmp_path / "totals.db"
    migrate_mod.migrate(verbose=False, db=db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = OFF")
    rows = [
        # (id, total, prep, cook, ruling, wait minutes) -> expected verdict
        ("excl", "1 hr", None, None, None, 90),                     # excludes
        ("unclear", "25 min", "15 min", "10 min", None, 15),        # unclear
        ("nocook", "1 hr 15 min", "15 min", None, None, 60),        # unclear, unanswerable
        ("incl", "2 hr 45 min", "5 min", "40 min", None, 120),      # includes
        ("decided", "25 min", "15 min", "10 min", 0, 15),           # no question
        ("nowaits", "1 hr", None, None, None, None),                # no question
    ]
    for rid, tot, prep, cook, ruling, mins in rows:
        con.execute("INSERT INTO recipes (id, name, source, total_time, prep_time, cook_time,"
                    " total_includes_waits) VALUES (?,?,'app',?,?,?,?)",
                    (rid, rid.title(), tot, prep, cook, ruling))
        if mins is not None:
            con.execute("INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes,"
                        " when_kind) VALUES (?,0,'resting','a rest',?,'always')", (rid, mins))
    con.commit()
    con.close()

    monkeypatch.setenv("RECIPE_APP_REPORTS", str(tmp_path))
    got = scan_total_vs_waits.run(str(db))
    assert sorted(r["recipe_id"] for r in got) == ["nocook", "unclear"], got
    assert {r["why"] for r in got} == {
        "prep or cook is missing, so the upper bound cannot be computed",
        "the stated total sits between the waits alone and prep + cook + waits"}


def test_the_survey_writes_nothing_to_the_recipe_data(tmp_path):
    import sqlite3
    sys.path.insert(0, str(BASE / "scripts"))
    import migrate as migrate_mod
    import scan_total_vs_waits

    db = tmp_path / "ro.db"
    migrate_mod.migrate(verbose=False, db=db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO recipes (id, name, source, total_time) VALUES "
                "('r','R','app','1 hr')")
    con.execute("INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes,"
                " when_kind) VALUES ('r',0,'resting','a rest',90,'always')")
    con.commit()
    before = [tuple(r) for r in con.execute("SELECT * FROM recipes")]
    con.close()
    scan_total_vs_waits.run(str(db))
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    assert [tuple(r) for r in con.execute("SELECT * FROM recipes")] == before
    con.close()
