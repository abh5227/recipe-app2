"""An author's total cannot contain waits that alone take longer than it.

⚠️ THE CASE ANDY FOUND ON :8005. earl-grey-tea-cake states "Total 1 hr" and carries a rest of
1 hr 30 min that always applies, so the page printed "Total 1 hr" with "Plan ahead 1 hr 30 min+"
directly under it. Two figures that cannot both describe the same recipe.

⚠️ AND IT IS THE ONLY THING THE PAGE MAY SETTLE ON ITS OWN, WHICH IS WHY THE RULE HAS THREE
ANSWERS AND NOT TWO. A stated total long enough to hold the waits may or may not have counted
them, and nothing on the page can tell. The author's figure stands there and the recipe goes on a
list for a person. A rule that guessed would silently rewrite a figure the author got right.

Measured over live's 300, read only, after Andy's ruling on all-butter-pie-crust: 1 excludes,
0 unclear, 1 includes, 2 decided by recipes.total_includes_waits, and 296 with no stated total or
no waits that always apply. The survey finds nothing to review and writes no list.
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import planahead                                                               # noqa: E402
from sqlalchemy import text as _sa_text                                        # noqa: E402


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


def test_clock_minutes_reads_an_open_end_as_a_ceiling_and_stated_minutes_does_not():
    """⚠️ THE PARSE THE WHOLE RULE RESTS ON, AND THE DEFECT IT HID.

    normalize_time rewrites a trailing "+" into " (+)", so clock_minutes answers "1 hr+" with
    (60, 60) and the one shape that says "at least" comes back claiming "exactly". A rule that
    overrules an author on the strength of an upper bound cannot be handed a made-up one.

    The first version read the "+" off the ALREADY NORMALIZED text, where it is no longer a "+",
    so the test was False for every form there is and the branch behind it never ran. This asserts
    the two answers differ, which is the thing a reader would otherwise have to rediscover.
    """
    assert planahead.clock_minutes(planahead.normalize_time("1 hr+")) == (60, 60)
    assert planahead.stated_minutes("1 hr+") == (60, None)
    assert planahead.stated_minutes("1 hr") == (60, 60)
    assert planahead.stated_minutes("1 to 2 hr") == (60, 120)
    assert planahead.stated_minutes("about an hour") == (None, None)
    assert planahead.stated_minutes("") == (None, None)
    assert planahead.stated_minutes(None) == (None, None)


def test_an_open_ended_stated_total_is_never_declared_impossible():
    """⚠️ "AT LEAST 1 HR" CAN HOLD ANYTHING, SO THE ARITHMETIC PROVES NOTHING. The page may
    overrule an author only where the total CANNOT contain the waits, and an open end has no
    ceiling to be below them. So this is the middle case: the author's figure stands and the recipe
    goes on the list for a person.

    This used to read EXCLUDES and print "2 hr 30 min+", a figure built by adding waits to a total
    that may already have counted them.
    """
    recipe, waits = _r(total_time="1 hr+"), [_w(90, max_minutes=90)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_UNCLEAR
    assert planahead.recipe_total(recipe, waits) == ("1 hr", "+")
    assert planahead.author_total_note(recipe, waits) is None


def test_a_range_is_judged_by_its_own_upper_end():
    """⚠️ THE SAME DEFECT IN THE SHAPE NOBODY LOOKED AT. The rule read the FLOOR of the stated
    total, so "1 to 2 hr" was declared unable to hold 2 hr of waits, which its own upper end holds
    exactly. A range only becomes impossible when the top of it is still short."""
    can_hold = _r(total_time="1 to 2 hr")
    assert planahead.stated_total_verdict(can_hold, [_w(120, max_minutes=120)])[0] \
        == planahead.STATED_UNCLEAR
    cannot = _r(total_time="1 to 2 hr")
    assert planahead.stated_total_verdict(cannot, [_w(150, max_minutes=150)])[0] \
        == planahead.STATED_EXCLUDES
    # Both ends carried through: 60 + 150 to 120 + 150, printed as the floor and a "+".
    assert planahead.recipe_total(cannot, [_w(150, max_minutes=150)]) \
        == ("3 hr 30 min+", planahead.INCLUDES_WAITS_NOTE)


def test_a_closed_total_and_a_closed_wait_add_up_to_a_closed_figure():
    """⚠️ THE ANTI-VACUITY CASE, AND THE REASON IT IS WRITTEN THIS WAY. The test that used to sit
    here asserted a "+" while passing a wait whose max_minutes was None, so the "+" came from the
    WAIT's open end and the assertion held with the stated total's handling deleted outright.
    Measured: both lines of it removed, test still green.

    Every end here is closed, so a "+" could only come from the stated total, and there must not be
    one. The open-ended wait is the line below, where the "+" can only come from the wait.
    """
    recipe = _r(total_time="1 hr")
    assert planahead.recipe_total(recipe, [_w(90, max_minutes=90)]) \
        == ("2 hr 30 min", planahead.INCLUDES_WAITS_NOTE)
    assert planahead.recipe_total(recipe, [_w(90)]) \
        == ("2 hr 30 min+", planahead.INCLUDES_WAITS_NOTE)


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

    # ⚠️ THIS LINE USED TO BE DECORATIVE. corpus_guard.report_target had never heard of
    #    $RECIPE_APP_REPORTS, so the list below was written into the REPO's reports/ on every run,
    #    under the real name, listing these fixture ids. It reads the variable now, conftest sets it
    #    for every test, and the assertion two lines down is what keeps this honest.
    monkeypatch.setenv("RECIPE_APP_REPORTS", str(tmp_path))
    got = scan_total_vs_waits.run(str(db))
    assert (tmp_path / "total-vs-waits.csv").is_file(), "the list did not land where it was sent"
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


# ---- the two recorded decisions ----------------------------------------------------------------

def test_the_recorded_rulings_are_the_two_a_person_actually_made():
    """⚠️ A RULING IS DATA, AND scripts/add_missed_waits.py IS THE ONE PLACE IT LIVES.

    Pinned so a third entry has to be deliberate. Each of these is a recipe a RULE put on a review
    list and a person then answered, which is the only shape a one-off row write takes here. A
    ruling invented to make a page look right would be a hand edit wearing a dict's clothes.
    """
    sys.path.insert(0, str(BASE / "scripts"))
    import add_missed_waits
    assert add_missed_waits.TOTAL_RULINGS == {"miso-tofu-recipe": 0, "all-butter-pie-crust": 1}


@pytest.mark.parametrize("ruling,total,prep,cook,wait,expect_total,expect_note", [
    # miso-tofu's shape: the author did not count the wait, so the page adds it.
    # "+" because _w leaves the wait open-ended, which is what live's miso-tofu shows: "40 min+".
    (0, "25 min", "15 min", "10 min", 15, "40 min+", planahead.INCLUDES_WAITS_NOTE),
    # all-butter-pie-crust's shape: the author DID count it, so the page leaves the figure alone.
    # ⚠️ cook is None, which is why the rule could not settle this one for itself. It has no
    #    prep + cook + waits upper bound to compare 1 hr 15 min against, so it said "unclear"
    #    rather than guessing, and Andy read the recipe and answered it.
    (1, "1 hr 15 min", "15 min", None, 60, "1 hr 15 min", None),
])
def test_a_ruling_ends_the_question_in_the_direction_it_states(
        ruling, total, prep, cook, wait, expect_total, expect_note):
    recipe = _r(total_time=total, prep_time=prep, cook_time=cook, total_includes_waits=ruling)
    waits = [_w(wait)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_NO_QUESTION
    assert planahead.recipe_total(recipe, waits) == (expect_total, expect_note)
    assert planahead.author_total_note(recipe, waits) is None


def test_the_pie_crusts_ruling_changes_no_figure_and_only_ends_the_question():
    """⚠️ THE WHOLE POINT OF THAT ONE. The Total reads the same either way, so the go-live writes a
    cell that moves no pixel. What it buys is that the recipe stops being asked about on every
    survey. A reviewer who checks only the rendered page would see nothing and conclude the write
    was pointless, so the difference is stated here instead."""
    shape = dict(total_time="1 hr 15 min", prep_time="15 min", cook_time=None)
    waits = [_w(60)]
    undecided = _r(**shape)
    decided = _r(**shape, total_includes_waits=1)
    assert planahead.recipe_total(undecided, waits) == planahead.recipe_total(decided, waits)
    assert planahead.stated_total_verdict(undecided, waits)[0] == planahead.STATED_UNCLEAR
    assert planahead.stated_total_verdict(decided, waits)[0] == planahead.STATED_NO_QUESTION


# ---- the key the client reads --------------------------------------------------------------------

def test_the_payload_key_and_the_client_that_reads_it_are_the_same_string():
    """⚠️ NOTHING ELSE TIES THESE TWO TOGETHER. app.py emits "author_total" and static/app.js reads
    `(view.data || {}).author_total`. The Python tests exercise author_total_note directly and the
    JS tests render from a hand-written `author_total:` in their own harness, so renaming the key on
    either side leaves BOTH suites green while the author's figure silently stops printing.

    Same shape as tests/js/factor-sync.test.js, which exists because scaler.js mirrors weights.py
    and nothing but a comparison keeps them agreeing.
    """
    key = "author_total"
    server = (BASE / "app.py").read_text()
    client = (BASE / "static" / "app.js").read_text()
    harness = (BASE / "tests" / "js" / "time-block-harness.js").read_text()
    assert f'"{key}": planahead.author_total_note' in server, \
        f"app.py no longer emits {key!r} from planahead.author_total_note"
    assert f".{key}" in client, f"static/app.js no longer reads {key!r}"
    assert key in harness, f"the JS harness no longer feeds {key!r}, so its tests prove nothing"


def test_the_route_actually_sends_the_authors_figure(kitchen):
    """And the end to end half, because the pin above only compares strings.

    A recipe stating 1 hr with a 1 hr 30 min rest that always applies is earl-grey-tea-cake's
    shape, which is the one recipe of the 300 this rule changes.
    """
    import json as _json
    rid = "stated-short"
    with kitchen.session() as s:
        s.execute(_sa_text(
            "INSERT INTO recipes (id, name, source, total_time) VALUES (:i,:n,'app','1 hr')"),
            {"i": rid, "n": "Stated Short"})
        s.execute(_sa_text(
            "INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes, max_minutes,"
            " when_kind) VALUES (:i, 0, 'resting', '1 hr 30 min', 90, NULL, 'always')"), {"i": rid})
        s.commit()

    r = kitchen.client.get(f"/api/recipes/{rid}")
    assert r.status_code == 200, r.data[:400]
    body = _json.loads(r.data)
    assert body["author_total"] == "Author's total: 1 hr, before the waits", body.get("author_total")
    assert body["total"] == {"label": "2 hr 30 min+", "note": planahead.INCLUDES_WAITS_NOTE}, \
        body.get("total")


def test_a_stated_total_that_carries_its_own_note_is_never_declared_impossible():
    """⚠️ THE AUTHOR ANSWERED IT IN WORDS, SO THE ARITHMETIC DOES NOT GET TO DISAGREE.
    "35 min (plus 1 hr soaking)" parses to 35 minutes, which is shorter than a 1 hr soak, and the
    old rule therefore printed "Author's total: 35 min, before the waits" against an author who
    had just written that the soaking is on top. That is not information dropped, it is a
    contradiction attributed to them. 0 of live's 14 stated totals carry a parenthetical today.
    """
    recipe = _r(total_time="35 min (plus 1 hr soaking)")
    waits = [_w(60, kind="soaking", max_minutes=60)]
    assert planahead.stated_total_verdict(recipe, waits)[0] == planahead.STATED_UNCLEAR
    assert planahead.recipe_total(recipe, waits) == ("35 min", "plus 1 hr soaking")
    assert planahead.author_total_note(recipe, waits) is None
    # The bare form of the same figures still reaches the arithmetic, so this is the note doing the
    # work rather than the parse quietly failing.
    bare = _r(total_time="35 min")
    assert planahead.stated_total_verdict(bare, waits)[0] == planahead.STATED_EXCLUDES
