"""recipe_waits and recipe_storage — the shape, and the four things the CHECKs refuse.

⚠️ A WAIT IS NOT STORAGE. "keeps, refrigerated, up to 1 week" is not something to plan around, and
8 of the 32 candidates excluded from the first proposals pass were exactly that. Two tables so the
two can never be summed together.

⚠️ THE EXTENSION NEVER WIDENS THE RANGE. "marinate 10 minutes to an hour (or overnight if time
allows)" has a normal range of 10 to 60 and an extension of 480. Folding the extension in would tell
a cook to allow 8 hours for a 10-minute marinade.
"""
import sqlite3

import pytest


def _wait(kitchen, rid, **kw):
    cols = dict(recipe_id=rid, position=0, kind="rising", label="1 hr rise")
    cols.update(kw)
    with kitchen.conn() as c:
        c.execute(f"INSERT INTO recipe_waits ({','.join(cols)}) "
                  f"VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        c.commit()


def _store(kitchen, rid, **kw):
    cols = dict(recipe_id=rid, position=0, where_kept="fridge", label="up to 1 week")
    cols.update(kw)
    with kitchen.conn() as c:
        c.execute(f"INSERT INTO recipe_storage ({','.join(cols)}) "
                  f"VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        c.commit()


@pytest.fixture
def rid(kitchen):
    return kitchen.client.post("/api/recipes", json={
        "name": "Waits", "ingredients": [], "steps": ["placeholder"]}).get_json()["id"]


def test_a_recipe_can_hold_several_waits(kitchen, rid):
    """⚠️ THE REASON THESE ARE TABLES AND NOT COLUMNS. pepperoni-rolls rises twice and morning-buns
    chills four times. A single pair of columns would have to pick one."""
    _wait(kitchen, rid, position=0, kind="rising", label="1 hr rise", min_minutes=60, max_minutes=60)
    _wait(kitchen, rid, position=1, kind="rising", label="30 min rise", min_minutes=30, max_minutes=30)
    with kitchen.conn() as c:
        got = [r[0] for r in c.execute("SELECT label FROM recipe_waits WHERE recipe_id=? "
                                       "ORDER BY position", (rid,))]
    assert got == ["1 hr rise", "30 min rise"]


def test_an_extension_is_stored_beside_the_range_and_never_inside_it(kitchen, rid):
    _wait(kitchen, rid, kind="marinating", label="10 min – 1 hr", min_minutes=10, max_minutes=60,
          ext_label="or overnight if time allows", ext_min_minutes=480)
    with kitchen.conn() as c:
        r = c.execute("SELECT min_minutes, max_minutes, ext_min_minutes FROM recipe_waits "
                      "WHERE recipe_id=?", (rid,)).fetchone()
    assert (r[0], r[1]) == (10, 60), "the extension widened the normal range"
    assert r[2] == 480


def test_a_shorter_extension_is_the_same_shape(kitchen, rid):
    """chocolate-chip-cookies: at least 12 hours, 'if you're pressed for time, a couple of hours
    will do'. The extension runs DOWNWARD and the column pair holds it without a second concept."""
    _wait(kitchen, rid, kind="chilling", label="12–48 hr", min_minutes=720, max_minutes=2880,
          ext_label="a couple of hours if pressed for time", ext_min_minutes=120, ext_max_minutes=120)
    with kitchen.conn() as c:
        r = c.execute("SELECT min_minutes, ext_min_minutes FROM recipe_waits WHERE recipe_id=?",
                      (rid,)).fetchone()
    assert tuple(r) == (720, 120)


def test_an_open_ended_wait_stores_a_null_max(kitchen, rid):
    """45 of the 72 proposals are open-ended: '2 hr+', 'at least overnight'."""
    _wait(kitchen, rid, kind="marinating", label="2 hr+", min_minutes=120, max_minutes=None)
    with kitchen.conn() as c:
        assert c.execute("SELECT max_minutes FROM recipe_waits WHERE recipe_id=?",
                         (rid,)).fetchone()[0] is None


def test_unparseable_text_keeps_the_words_and_leaves_the_numbers_blank(kitchen, rid):
    _wait(kitchen, rid, kind="other", label="until it smells right", min_minutes=None, max_minutes=None)
    with kitchen.conn() as c:
        assert tuple(c.execute("SELECT label, min_minutes FROM recipe_waits WHERE recipe_id=?",
                               (rid,)).fetchone()) == ("until it smells right", None)


@pytest.mark.parametrize("kw, why", [
    (dict(kind="napping"), "a kind outside the list"),
    (dict(min_minutes=60, max_minutes=30), "a max below its min"),
    (dict(min_minutes=-1), "a negative duration"),
    (dict(ext_min_minutes=480), "an extension with no label"),
    (dict(ext_min_minutes=480, ext_max_minutes=60, ext_label="x"), "an extension max below its min"),
])
def test_the_wait_checks_refuse(kitchen, rid, kw, why):
    with pytest.raises(sqlite3.IntegrityError):
        _wait(kitchen, rid, **kw)


def test_two_waits_cannot_share_a_position(kitchen, rid):
    _wait(kitchen, rid, position=0)
    with pytest.raises(sqlite3.IntegrityError):
        _wait(kitchen, rid, position=0, label="another")


def test_storage_records_where_and_what_it_applies_to(kitchen, rid):
    _store(kitchen, rid, where_kept="freezer", applies_to="the shaped dough",
           label="up to 4 days", max_minutes=5760)
    with kitchen.conn() as c:
        assert tuple(c.execute("SELECT where_kept, applies_to, min_minutes, max_minutes FROM "
                               "recipe_storage WHERE recipe_id=?", (rid,)).fetchone()) == \
               ("freezer", "the shaped dough", None, 5760)


@pytest.mark.parametrize("kw, why", [
    (dict(where_kept="cupboard"), "a place outside the list"),
    (dict(min_minutes=60, max_minutes=30), "a max below its min"),
])
def test_the_storage_checks_refuse(kitchen, rid, kw, why):
    with pytest.raises(sqlite3.IntegrityError):
        _store(kitchen, rid, **kw)


def test_deleting_the_recipe_takes_both_tables_with_it(kitchen, rid):
    _wait(kitchen, rid)
    _store(kitchen, rid)
    with kitchen.conn() as c:
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("DELETE FROM recipes WHERE id=?", (rid,))
        c.commit()
        assert c.execute("SELECT COUNT(*) FROM recipe_waits WHERE recipe_id=?", (rid,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM recipe_storage WHERE recipe_id=?", (rid,)).fetchone()[0] == 0


# --------------------------------------------------------------------------------------------- #
# The save path reads the numbers out of what a person typed
# --------------------------------------------------------------------------------------------- #
def _save(kitchen, rid, waits=None, storage=None):
    return kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Waits", "ingredients": [], "steps": ["placeholder"],
        "waits": waits or [], "storage": storage or []})


def test_the_save_reads_minutes_out_of_the_typed_text(kitchen, rid):
    assert _save(kitchen, rid, waits=[{"kind": "rising", "label": "1 hr rise"}]).status_code == 200
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert [(w["label"], w["min_minutes"], w["max_minutes"]) for w in got["waits"]] == \
           [("1 hr rise", 60, 60)]
    assert got["wait_total"] == {"min_minutes": 60, "max_minutes": 60, "label": "1 hr rise"}


def test_an_extension_is_read_separately_and_never_widens_the_range(kitchen, rid):
    """⚠️ THE WHOLE REASON THE EDITOR HAS TWO BOXES. One box would make this a 10 minute to 8 hour
    marinade, which is a promise the recipe never made."""
    _save(kitchen, rid, waits=[{"kind": "marinating", "label": "10 min - 1 hr",
                                "ext_label": "or overnight if time allows"}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert (w["min_minutes"], w["max_minutes"]) == (10, 60)
    assert (w["ext_label"], w["ext_min_minutes"]) == ("or overnight if time allows", 480)


def test_unreadable_text_keeps_its_words_and_leaves_the_numbers_blank(kitchen, rid):
    _save(kitchen, rid, waits=[{"kind": "other", "label": "until it smells right"}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert (w["label"], w["min_minutes"], w["max_minutes"]) == ("until it smells right", None, None)


def test_several_waits_total_and_one_open_end_opens_the_total(kitchen, rid):
    _save(kitchen, rid, waits=[{"kind": "rising", "label": "about 1 hr"},
                               {"kind": "resting", "label": "30 min"}])
    assert kitchen.client.get(f"/api/recipes/{rid}").get_json()["wait_total"] == \
           {"min_minutes": 90, "max_minutes": 90, "label": "1 hr 30 min"}
    _save(kitchen, rid, waits=[{"kind": "marinating", "label": "at least 2 hours"},
                               {"kind": "resting", "label": "30 min"}])
    assert kitchen.client.get(f"/api/recipes/{rid}").get_json()["wait_total"] == \
           {"min_minutes": 150, "max_minutes": None, "label": "2 hr 30 min+"}


def test_storage_never_reaches_the_wait_total(kitchen, rid):
    """⚠️ THE SEPARATION, END TO END. A week of fridge life must not read as a week of planning."""
    _save(kitchen, rid, waits=[{"kind": "chilling", "label": "30 min"}],
          storage=[{"where_kept": "fridge", "applies_to": "the dough", "label": "up to 1 week"}])
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert got["wait_total"]["min_minutes"] == 30
    assert got["storage"][0]["max_minutes"] == 10080


def test_a_blank_row_is_dropped_and_a_bad_kind_falls_back(kitchen, rid):
    _save(kitchen, rid, waits=[{"kind": "napping", "label": "30 min"}, {"kind": "rising", "label": "  "}])
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"]
    assert len(got) == 1 and got[0]["kind"] == "other"


def test_waits_show_up_in_your_changes_the_same_way_prep_time_does(kitchen, rid):
    """⚠️ THE RULING, ASSERTED. prep_time is captured in the snapshot and diffed as a field, and a
    wait is treated identically: a fact a person typed that no step edit updates for them."""
    _save(kitchen, rid)                                    # settle the baseline
    before = kitchen.client.get(f"/api/recipes/{rid}").get_json()["annotations"]
    _save(kitchen, rid, waits=[{"kind": "rising", "label": "1 hr rise"}])
    after = kitchen.client.get(f"/api/recipes/{rid}").get_json()["annotations"]
    kinds = [a["kind"] for a in after if a not in before]
    assert "wait" in kinds, after


def test_a_recipe_with_no_waits_serializes_exactly_as_it_did_before(kitchen, rid):
    """⚠️ THE BYTE-EQUAL SHORT-CIRCUIT. All 306 live baselines were written before these keys
    existed, so emitting "waits":[] on every recipe would make every one of them differ from its
    baseline and force the diff to run 300 times to return the same answer."""
    import snapshot_serialize as ss
    assert ss.content_blob({"name": "x"}, [], []) == ss.content_blob({"name": "x"}, [], [], [], [])


# ---------------------------------------------------------------------------------------------
# migration 050: a wait can be conditional, and only an unconditional one counts.
# ---------------------------------------------------------------------------------------------

def test_an_existing_wait_defaults_to_always(kitchen, rid):
    """⚠️ THE DEFAULT IS THE MIGRATION'S WHOLE SAFETY ARGUMENT. Every wait written before 050 was
    read from a recipe that states it flatly, so 'always' is the correct value for all of them and
    no backfill is needed."""
    _wait(kitchen, rid)
    with kitchen.conn() as c:
        assert c.execute("SELECT when_kind, when_label FROM recipe_waits").fetchone()[:2] == \
               ("always", None)


@pytest.mark.parametrize("kw, why", [
    (dict(when_kind="maybe"), "a when outside the list"),
    (dict(when_kind="only_if"), "only_if with no condition after it"),
])
def test_the_when_checks_refuse(kitchen, rid, kw, why):
    with pytest.raises(sqlite3.IntegrityError):
        _wait(kitchen, rid, **kw)


def test_an_only_if_wait_stores_its_condition(kitchen, rid):
    _wait(kitchen, rid, when_kind="only_if", when_label="chilled")
    with kitchen.conn() as c:
        assert c.execute("SELECT when_kind, when_label FROM recipe_waits").fetchone()[:2] == \
               ("only_if", "chilled")


def test_a_conditional_wait_never_reaches_the_total(kitchen, rid):
    """⚠️ no-knead-bread rests 45 to 60 minutes ONLY IF the dough was chilled. Summing it tells a
    cook to block out an hour for something the recipe told them to skip."""
    assert _save(kitchen, rid, waits=[
        {"kind": "rising", "label": "12 hr"},
        {"kind": "resting", "label": "1 hr", "when_kind": "only_if", "when_label": "chilled"},
    ]).status_code == 200
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert len(got["waits"]) == 2                       # both are stored and both are shown
    assert got["wait_total"]["min_minutes"] == 720      # only the rise is counted
    assert got["wait_total"]["label"] == "12 hr"        # one counted wait keeps its own words


def test_an_optional_wait_is_the_same(kitchen, rid):
    assert _save(kitchen, rid, waits=[
        {"kind": "rising", "label": "1 hr"},
        {"kind": "soaking", "label": "8 hr", "when_kind": "optional"},
    ]).status_code == 200
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert got["wait_total"]["min_minutes"] == 60


def test_a_recipe_whose_waits_are_all_conditional_has_no_total(kitchen, rid):
    """The truthful answer is no plan-ahead figure at all, not a figure of zero."""
    assert _save(kitchen, rid, waits=[
        {"kind": "soaking", "label": "8 hr", "when_kind": "optional"}]).status_code == 200
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert got["wait_total"] == {"min_minutes": None, "max_minutes": None, "label": ""}
    assert len(got["waits"]) == 1                       # still stored, still shown


def test_only_if_with_no_condition_falls_back_to_always_rather_than_500ing(kitchen, rid):
    """⚠️ THE CHECK WOULD REJECT THE ROW. A half-filled picker must not lose the save."""
    assert _save(kitchen, rid, waits=[
        {"kind": "rising", "label": "1 hr", "when_kind": "only_if", "when_label": "  "}]).status_code == 200
    got = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert (got["waits"][0]["when_kind"], got["waits"][0]["when_label"]) == ("always", None)


def test_a_bad_when_falls_back_to_always(kitchen, rid):
    assert _save(kitchen, rid, waits=[
        {"kind": "rising", "label": "1 hr", "when_kind": "whenever"}]).status_code == 200
    assert kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]["when_kind"] == "always"


def test_a_condition_is_dropped_when_the_wait_is_not_conditional(kitchen, rid):
    """Switching the picker back to always must not leave the old condition behind to resurface."""
    assert _save(kitchen, rid, waits=[
        {"kind": "rising", "label": "1 hr", "when_kind": "always", "when_label": "chilled"}]).status_code == 200
    assert kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]["when_label"] is None


def test_turning_a_wait_optional_shows_in_your_changes(kitchen, rid):
    """⚠️ SAME TREATMENT AS prep_time, which is the round-2 ruling. The qualifier is part of the
    line, so the entry does not read as the same words twice."""
    import snapshot_diff
    old = {"waits": [{"position": 0, "label": "8 hr", "kind": "soaking", "when_kind": "always"}]}
    new = {"waits": [{"position": 0, "label": "8 hr", "kind": "soaking", "when_kind": "optional"}]}
    changes = snapshot_diff._diff_rows("wait", old["waits"], new["waits"], snapshot_diff.WAIT_LABEL)
    assert len(changes) == 1
    assert "(optional)" in str(changes[0])


# ---------------------------------------------------------------------------------------------
# migration 051: a step pointer that refuses to point at the wrong step.
# ---------------------------------------------------------------------------------------------

def _save_steps(kitchen, rid, steps, waits):
    return kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Waits", "ingredients": [], "steps": steps, "waits": waits, "storage": []})


def test_a_linked_wait_reports_the_step_number_the_page_prints(kitchen, rid):
    _save_steps(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert w["step_no"] == 2 and w["step_ok"] is True
    assert w["step_check"] == "wrap in plastic and refrigerate overnight."


def test_inserting_a_step_above_a_linked_one_DROPS_the_link_instead_of_shifting_it(kitchen, rid):
    """⚠️ THE WHOLE REASON 051 EXISTS.

    write_recipe_rows reassigns every step position by enumeration on each save, so inserting a
    step shifts everything below it. With a bare step_position the wait would keep pointing at
    slot 1 and silently start describing the NEW step. The stored snippet no longer matches, so
    the link is dropped and the wait reads with no step number at all."""
    _save_steps(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1}])
    before = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert before["step_no"] == 2

    # the client sends the draft back: a new step in the middle, the wait untouched
    _save_steps(kitchen, rid,
                ["Mix the dough.", "A BRAND NEW STEP.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1,
                  "step_check": before["step_check"]}])
    after = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert after["step_position"] == 1          # the pointer is still stored, untouched
    assert after["step_no"] is None             # but it does NOT link
    assert after["step_ok"] is False            # and the editor is told why
    assert after["label"] == "overnight"        # the wait itself still reads correctly


def test_the_picker_repairs_the_link_by_clearing_the_check(kitchen, rid):
    """A fresh pick sends a null check, which is the one thing that makes the server read the
    snippet off the step again."""
    _save_steps(kitchen, rid,
                ["Mix the dough.", "A BRAND NEW STEP.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 2,
                  "step_check": None}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert w["step_no"] == 3 and w["step_ok"] is True


def test_deleting_the_linked_step_drops_the_link(kitchen, rid):
    _save_steps(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1}])
    check = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]["step_check"]
    _save_steps(kitchen, rid, ["Mix the dough."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1,
                  "step_check": check}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert w["step_position"] is None and w["step_no"] is None


def test_reformatting_a_step_keeps_the_link(kitchen, rid):
    """The check compares NORMALIZED text, so markup and spacing changes are not a re-wording."""
    _save_steps(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1}])
    check = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]["step_check"]
    _save_steps(kitchen, rid,
                ["Mix the dough.", "Wrap in   plastic and <b>refrigerate</b>  overnight."],
                [{"kind": "chilling", "label": "overnight", "step_position": 1,
                  "step_check": check}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert w["step_no"] == 2 and w["step_ok"] is True


def test_a_wait_with_no_step_has_no_number_and_is_not_an_error(kitchen, rid):
    _save_steps(kitchen, rid, ["Mix the dough."],
                [{"kind": "chilling", "label": "overnight"}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert (w["step_position"], w["step_no"], w["step_ok"]) == (None, None, True)
