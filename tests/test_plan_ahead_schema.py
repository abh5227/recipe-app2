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
# migration 053: a wait points at a step ROW. step_position and step_check are retired.
#
# ⚠️ THESE REPLACE THE 051 TESTS, AND ONE OF THEM INVERTS. Under 051 a wait was a slot number plus a
# snippet of the step's text, and inserting a step above a linked one DROPPED the link, because every
# save renumbered the slots and the snippet existed to notice. The id does not move when the slots do,
# so that same edit now KEEPS the link and the printed number follows the step. The old behaviour was
# the best available answer to a pointer that could not be trusted, not a thing anyone wanted.
# ---------------------------------------------------------------------------------------------

def _save_steps(kitchen, rid, steps, waits):
    return kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Waits", "ingredients": [], "steps": steps, "waits": waits, "storage": []})


def _steps(kitchen, rid):
    """The step rows as the client would read them, in printed order."""
    return kitchen.client.get(f"/api/recipes/{rid}").get_json()["steps"]


def _waits(kitchen, rid):
    return kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"]


def _linked(kitchen, rid, steps, which=1, label="overnight"):
    """Save `steps`, then link one wait to the step at index `which` BY ITS ID, as the picker does."""
    _save_steps(kitchen, rid, steps, [])
    sid = _steps(kitchen, rid)[which]["id"]
    _save_steps(kitchen, rid, [{"id": s["id"], "text": s["text"]} for s in _steps(kitchen, rid)],
                [{"kind": "chilling", "label": label, "step_id": sid}])
    return sid


def test_a_linked_wait_reports_the_step_number_the_page_prints(kitchen, rid):
    sid = _linked(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."])
    w = _waits(kitchen, rid)[0]
    assert (w["step_id"], w["step_no"], w["step_ok"]) == (sid, 2, True)


def test_inserting_a_step_above_a_linked_one_KEEPS_the_link_and_the_number_follows(kitchen, rid):
    """⚠️ THE INVERSION, AND THE WHOLE POINT OF 053. A save renumbers every step, so under 051 the
    pointer said slot 1 while the step had moved to slot 2, and the snippet check dropped the link to
    avoid describing the wrong step. The id is not a slot. The wait stays attached and its printed
    number moves from 2 to 3, which is what the reader sees on the page."""
    sid = _linked(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."])
    assert _waits(kitchen, rid)[0]["step_no"] == 2
    rows = _steps(kitchen, rid)
    _save_steps(kitchen, rid,
                [{"id": rows[0]["id"], "text": rows[0]["text"]},
                 {"id": None, "text": "A BRAND NEW STEP."},
                 {"id": rows[1]["id"], "text": rows[1]["text"]}],
                [{"kind": "chilling", "label": "overnight", "step_id": sid}])
    w = _waits(kitchen, rid)[0]
    assert w["step_id"] == sid, "the same row, so the same id"
    assert w["step_no"] == 3, "and the printed number followed it down the list"
    assert w["step_ok"] is True


def test_reordering_the_steps_carries_the_links_with_them(kitchen, rid):
    """Two linked waits, the steps reversed in one save. Each link follows its own step."""
    _save_steps(kitchen, rid, ["Mix the dough.", "Rest overnight.", "Bake."], [])
    rows = _steps(kitchen, rid)
    a, b = rows[1]["id"], rows[2]["id"]
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": a},
                 {"kind": "other", "label": "20 min", "step_id": b}])
    assert [(w["step_id"], w["step_no"]) for w in _waits(kitchen, rid)] == [(a, 2), (b, 3)]
    # now reverse them, sending the SAME ids in a new order, exactly as a drag does
    rev = list(reversed(_steps(kitchen, rid)))
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rev],
                [{"kind": "chilling", "label": "overnight", "step_id": a},
                 {"kind": "other", "label": "20 min", "step_id": b}])
    assert [(w["step_id"], w["step_no"]) for w in _waits(kitchen, rid)] == [(a, 2), (b, 1)]


def test_deleting_a_linked_step_clears_ONLY_that_waits_link(kitchen, rid):
    """The brief's case. The editor still holds the wait pointing at a step the save is removing, so
    write_plan_ahead drops an id that names no step of this recipe. The other wait is untouched."""
    _save_steps(kitchen, rid, ["Mix the dough.", "Rest overnight.", "Bake."], [])
    rows = _steps(kitchen, rid)
    a, b = rows[1]["id"], rows[2]["id"]
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": a},
                 {"kind": "other", "label": "20 min", "step_id": b}])
    # drop the middle step, keeping both waits as the editor would still be holding them
    _save_steps(kitchen, rid,
                [{"id": rows[0]["id"], "text": rows[0]["text"]},
                 {"id": rows[2]["id"], "text": rows[2]["text"]}],
                [{"kind": "chilling", "label": "overnight", "step_id": a},
                 {"kind": "other", "label": "20 min", "step_id": b}])
    got = _waits(kitchen, rid)
    assert got[0]["step_id"] is None and got[0]["step_no"] is None, "its step is gone"
    assert got[0]["label"] == "overnight", "and the wait itself still reads correctly"
    assert (got[1]["step_id"], got[1]["step_no"]) == (b, 2), "the other wait kept its link"


def test_a_deleted_step_row_cannot_leave_a_dangling_pointer(kitchen, rid):
    """⚠️ THE DATABASE'S OWN BACKSTOP, underneath the save path. ON DELETE SET NULL means a step row
    removed by ANY route clears the waits that named it, not only one that came through the editor.
    Tested on both dialects before migration 053 was written."""
    sid = _linked(kitchen, rid, ["Mix the dough.", "Rest overnight."])
    with kitchen.conn() as c:
        c.execute("PRAGMA foreign_keys = ON")
        assert c.execute("SELECT step_id FROM recipe_waits").fetchone()[0] == sid
        c.execute("DELETE FROM recipe_steps WHERE id=?", (sid,))
        c.commit()
        assert c.execute("SELECT step_id FROM recipe_waits").fetchone()[0] is None


def test_a_step_id_from_another_recipe_is_refused(kitchen, rid):
    """The id set is scoped to this recipe, so a stray id becomes null rather than linking across."""
    other = kitchen.client.post("/api/recipes", json={
        "name": "Other", "ingredients": [], "steps": ["Not this recipe."]}).get_json()["id"]
    stolen = _steps(kitchen, other)[0]["id"]
    _save_steps(kitchen, rid, ["Mix the dough."],
                [{"kind": "chilling", "label": "overnight", "step_id": stolen}])
    assert _waits(kitchen, rid)[0]["step_id"] is None


def test_rewording_a_linked_step_keeps_the_link(kitchen, rid):
    """⚠️ 051 BROKE HERE, AND THAT WAS THE COST OF ITS MECHANISM. The check compared the FRONT of the
    step, so rewording the opening of a step nobody meant to unlink dropped the link silently. The id
    does not care what the step says."""
    sid = _linked(kitchen, rid, ["Mix the dough.", "Wrap in plastic and refrigerate overnight."])
    rows = _steps(kitchen, rid)
    _save_steps(kitchen, rid,
                [{"id": rows[0]["id"], "text": rows[0]["text"]},
                 {"id": sid, "text": "Chill it right through the night, wrapped well."}],
                [{"kind": "chilling", "label": "overnight", "step_id": sid}])
    w = _waits(kitchen, rid)[0]
    assert (w["step_id"], w["step_no"], w["step_ok"]) == (sid, 2, True)


def test_a_link_to_a_heading_is_STORED_and_never_printed(kitchen, rid):
    """⚠️ THE RULE CHANGED WHEN THE STEP ROW MENU LEARNED TO CONVERT, and the old one is worth
    stating because this test used to pin it. write_plan_ahead validated against is_heading=0 rows
    only, so a heading's id was dropped exactly like a deleted step's. That was right while nothing
    could convert a step: an id could only arrive that way by mistake.

    A cook can convert a linked step to a heading now, and clearing the pointer would make the
    conversion one-way — the id lives nowhere else, so converting back could not restore it. The
    link is kept, and resolve_steps still hands back no number, so it is held without ever being
    printed as "(step N)". Storing and printing are different questions.

    step_ok therefore becomes REACHABLE through the API, which is the honest form of what the old
    docstring claimed was impossible."""
    _save_steps(kitchen, rid, [{"heading": "PREP"}, "Mix the dough."], [])
    rows = _steps(kitchen, rid)
    head = rows[0]
    assert head["is_heading"]
    _save_steps(kitchen, rid,
                [{"id": r["id"], **({"heading": r["text"]} if r["is_heading"] else {"text": r["text"]})}
                 for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": head["id"]}])
    w = _waits(kitchen, rid)[0]
    assert w["step_id"] == head["id"], "the link is what a convert-back has to restore"
    assert (w["step_no"], w["step_ok"]) == (None, False), "and it is never printed as a number"


def test_a_converted_step_keeps_its_wait_link_and_gets_it_back(kitchen, rid):
    """The round trip the menu item exists for. The row id is the link, so a conversion that keeps
    the id keeps the link, and converting back prints the number again with nothing re-entered."""
    _save_steps(kitchen, rid, ["Soak the beans overnight.", "Drain and rinse."], [])
    rows = _steps(kitchen, rid)
    soak = rows[0]
    as_is = [{"id": r["id"], "text": r["text"]} for r in rows]
    wait = [{"kind": "soaking", "label": "8 hr", "step_id": soak["id"]}]
    _save_steps(kitchen, rid, as_is, wait)
    assert _waits(kitchen, rid)[0]["step_no"] == 1

    to_heading = [dict(x) for x in as_is]
    to_heading[0] = {"id": soak["id"], "heading": soak["text"]}
    _save_steps(kitchen, rid, to_heading, wait)
    w = _waits(kitchen, rid)[0]
    assert (w["step_id"], w["step_no"]) == (soak["id"], None)

    _save_steps(kitchen, rid, as_is, [{"kind": "soaking", "label": "8 hr", "step_id": w["step_id"]}])
    assert _waits(kitchen, rid)[0]["step_no"] == 1, "the link came back with the step"


def test_a_deleted_steps_id_is_still_dropped(kitchen, rid):
    """⚠️ THE HALF THAT DID NOT CHANGE, and the reason the set is still filtered at all. A heading is
    a row this recipe HAS. A deleted step is not, and neither is a step of another recipe, so both
    still become NULL rather than reaching a foreign key that would refuse the whole save."""
    _save_steps(kitchen, rid, ["Mix.", "Rest."], [])
    rows = _steps(kitchen, rid)
    gone = rows[1]
    _save_steps(kitchen, rid, [{"id": rows[0]["id"], "text": rows[0]["text"]}],
                [{"kind": "resting", "label": "1 hr", "step_id": gone["id"]}])
    assert _waits(kitchen, rid)[0]["step_id"] is None
    _save_steps(kitchen, rid, [{"id": rows[0]["id"], "text": rows[0]["text"]}],
                [{"kind": "resting", "label": "1 hr", "step_id": 999999}])
    assert _waits(kitchen, rid)[0]["step_id"] is None


def test_resolve_steps_still_refuses_a_heading_it_is_handed_directly():
    """The defensive branch, reached as a unit rather than through the API. resolve_steps is a pure
    function with other callers (the scripts), so it answers honestly for a row the save would never
    have stored: a link naming a heading, or naming nothing in this recipe, gets no number."""
    import planahead
    steps = [{"id": 10, "is_heading": 1, "text": "PREP"},
             {"id": 11, "is_heading": 0, "text": "Mix."},
             {"id": 12, "is_heading": 0, "text": "Rest."}]
    got = planahead.resolve_steps(
        [{"step_id": 12}, {"step_id": None}, {"step_id": 10}, {"step_id": 999}], steps)
    assert [(w["step_no"], w["step_ok"]) for w in got] == [
        (2, True),          # the second ordinary step, heading excluded
        (None, True),       # no link is not an error
        (None, False),      # a heading has no number
        (None, False),      # unknown to this recipe
    ]


def test_a_wait_with_no_step_has_no_number_and_is_not_an_error(kitchen, rid):
    _save_steps(kitchen, rid, ["Mix the dough."],
                [{"kind": "chilling", "label": "overnight"}])
    w = kitchen.client.get(f"/api/recipes/{rid}").get_json()["waits"][0]
    assert (w["step_id"], w["step_no"], w["step_ok"]) == (None, None, True)


# ---------------------------------------------------------------------------------------------
# migration 054: the old pointer is gone.
# ---------------------------------------------------------------------------------------------

def test_the_old_step_pointer_columns_are_gone(kitchen):
    """⚠️ 053 LEFT THEM IN PLACE TO STAY ADDITIVE AND 054 REMOVES THEM. Live held 0 recipe_waits rows,
    so both columns were empty everywhere and this was the cheapest moment they will ever be."""
    with kitchen.conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(recipe_waits)")]
    assert "step_position" not in cols
    assert "step_check" not in cols
    assert "step_id" in cols


def test_the_table_rebuilds_kept_every_index_key_and_guard(kitchen):
    """⚠️ SQLITE REWRITES THE WHOLE TABLE to drop a column (054) or change a CHECK (056), so what came
    along for the ride is worth asserting rather than assuming.

    ⚠️ THIS USED TO COUNT THE CHECKS AND THE COUNT BROKE THE MOMENT 056 ADDED TWO. A count says nothing
    about WHICH guard survived, which is the only thing worth knowing, so each one is named."""
    with kitchen.conn() as c:
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name='recipe_waits'").fetchone()[0]
        idx = sorted(r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='recipe_waits'"))
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert idx == ["idx_recipe_waits_min", "idx_recipe_waits_recipe", "idx_recipe_waits_when",
                   "sqlite_autoindex_recipe_waits_1"]
    assert "UNIQUE (recipe_id, position)" in sql
    # ⚠️ NAMED, NOT COUNTED, for the reason in this test's own docstring. The count was 2 and 057
    #    made it 3, which is the second time a tally here broke on an addition that was correct.
    for col in ("step_id", "alongside_step_id", "ext_step_id"):
        assert f"{col}" in sql and "ON DELETE SET NULL" in sql, f"{col} lost its FK"
    assert sql.count("ON DELETE SET NULL") == 3, "step_id, alongside_step_id AND ext_step_id"
    assert "ON DELETE CASCADE" in sql, "the recipe_id cascade"
    for guard in (
            "when_kind IN ('always','optional','only_if','alongside')",
            "when_kind <> 'only_if' OR when_label IS NOT NULL",
            "alongside_step_id IS NULL OR alongside_step_id <> step_id",
            "kind IN ('marinating','chilling','rising','soaking','resting','freezing','brining','other')",
            "min_minutes IS NULL OR min_minutes >= 0",
            "max_minutes IS NULL OR min_minutes IS NULL OR max_minutes >= min_minutes",
            "ext_max_minutes IS NULL OR ext_min_minutes IS NULL OR ext_max_minutes >= ext_min_minutes",
            "ext_label IS NOT NULL OR (ext_min_minutes IS NULL AND ext_max_minutes IS NULL)"):
        assert guard in sql, f"the CHECK for {guard!r} did not survive the rebuild"


def test_the_model_no_longer_declares_them():
    """The ORM and the schema have to agree, or a select names a column that is not there."""
    from models import RecipeWait
    cols = {c.name for c in RecipeWait.__table__.columns}
    assert "step_position" not in cols and "step_check" not in cols
    assert "step_id" in cols


# ---------------------------------------------------------------------------------------------
# migration 056: a wait that happens at the same time as another one.
# ---------------------------------------------------------------------------------------------

def _two_waits(kitchen, rid, when_kind="alongside"):
    """Two chills on two steps, the second running alongside the first. Mirrors morning-buns, where
    the dough chills overnight and the butter block chills overnight during the same night."""
    _save_steps(kitchen, rid, ["Chill the dough.", "Make the butter block.", "Roll and bake."], [])
    rows = _steps(kitchen, rid)
    dough, butter = rows[0]["id"], rows[1]["id"]
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": dough},
                 {"kind": "chilling", "label": "overnight", "step_id": butter,
                  "when_kind": when_kind, "alongside_step_id": dough}])
    return dough, butter


def test_an_alongside_wait_names_the_step_it_overlaps(kitchen, rid):
    dough, butter = _two_waits(kitchen, rid)
    got = _waits(kitchen, rid)
    assert (got[1]["when_kind"], got[1]["alongside_step_id"]) == ("alongside", dough)
    assert got[1]["alongside_no"] == 1, "the PRINTED number of the step it runs alongside"
    assert got[1]["step_no"] == 2, "and its own step number is unaffected"


def test_an_alongside_wait_does_not_reach_the_total(kitchen, rid):
    """⚠️ THIS NEEDED NO CODE, WHICH IS THE POINT. planahead.counts already answers "only an
    unconditional wait counts", so a fourth when_kind is excluded by the rule that was already there.
    Two overnights that happen on the same night are one night of waiting."""
    _two_waits(kitchen, rid)
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert len(d["waits"]) == 2
    import planahead
    assert [planahead.counts(w) for w in d["waits"]] == [True, False]
    assert planahead.total(d["waits"]) == (480, None), "8 hr, not 16"


def test_there_is_no_check_forcing_an_alongside_wait_to_name_a_step(kitchen):
    """⚠️ THE CHECK THAT LOOKS OBVIOUS AND CONTRADICTS THE FOREIGN KEY. "an alongside wait must name
    the step it runs alongside" cannot hold at the same time as ON DELETE SET NULL on that very
    column: deleting the step tries to null the pointer and the CHECK refuses, so the DELETE fails.
    write_recipe_rows deletes step rows BEFORE write_plan_ahead rewrites the waits, so a cook deleting
    an overlapped step would have got a 500 and lost the edit. The invariant lives in the save path
    and in counts() instead."""
    with kitchen.conn() as c:
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name='recipe_waits'").fetchone()[0]
    assert "alongside_step_id IS NOT NULL" not in sql


def test_an_alongside_wait_that_overlaps_nothing_is_still_decided_by_its_when_kind():
    """⚠️ THIS TEST USED TO ASSERT THE OPPOSITE, AND THE RULING CHANGED IT. It pinned "between the
    step being deleted and the next save the row overlaps nothing, so it is ordinary waiting time
    and the total must say so" — planahead.counts returning True for an alongside wait with a null
    pointer. The client's own filter never had that arm, so the server put that row in the figure
    while the client left it out, and a one-wait recipe printed the head figure plus a bullet
    repeating it.

    The rule is now a function of when_kind and nothing else, which is what lets the client be
    HANDED the answer (`in_total`) instead of deriving it. The cost is the transient window this
    test used to describe: write_plan_ahead normalizes an alongside row with no pointer back to
    'always' on the next save, so the undercount lasts until then. See planahead.counts."""
    import planahead
    assert planahead.counts({"when_kind": "alongside", "alongside_step_id": 7}) is False
    assert planahead.counts({"when_kind": "alongside", "alongside_step_id": None}) is False
    assert planahead.counts({"when_kind": "always"}) is True
    assert planahead.counts({"when_kind": "optional"}) is False


def test_an_alongside_wait_with_no_target_falls_back_to_always(kitchen, rid):
    """⚠️ A HALF-FILLED PICKER MUST NOT 500 THE SAVE. The table refuses an 'alongside' with nothing to
    run alongside, so the save turns it into an ordinary wait, which reads correctly and is fixable.
    Same treatment only_if already gets when its condition is blank."""
    _save_steps(kitchen, rid, ["Chill the dough."], [])
    sid = _steps(kitchen, rid)[0]["id"]
    assert _save_steps(kitchen, rid, [{"id": sid, "text": "Chill the dough."}],
                       [{"kind": "chilling", "label": "overnight", "step_id": sid,
                         "when_kind": "alongside"}]).status_code == 200
    w = _waits(kitchen, rid)[0]
    assert (w["when_kind"], w["alongside_step_id"]) == ("always", None)


def test_a_wait_cannot_run_alongside_its_own_step(kitchen, rid):
    """It would say nothing. The save drops the pointer rather than storing a row the CHECK refuses."""
    _save_steps(kitchen, rid, ["Chill the dough."], [])
    sid = _steps(kitchen, rid)[0]["id"]
    assert _save_steps(kitchen, rid, [{"id": sid, "text": "Chill the dough."}],
                       [{"kind": "chilling", "label": "overnight", "step_id": sid,
                         "when_kind": "alongside", "alongside_step_id": sid}]).status_code == 200
    w = _waits(kitchen, rid)[0]
    assert (w["when_kind"], w["alongside_step_id"]) == ("always", None)


def test_deleting_the_overlapped_step_clears_the_pointer(kitchen, rid):
    """The overlap pointer gets the same treatment as step_id: a step that is gone cannot be named."""
    dough, butter = _two_waits(kitchen, rid)
    rows = [r for r in _steps(kitchen, rid) if r["id"] != dough]
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": butter,
                  "when_kind": "alongside", "alongside_step_id": dough}])
    w = _waits(kitchen, rid)[0]
    assert w["alongside_step_id"] is None and w["when_kind"] == "always"


def test_the_database_refuses_a_dangling_overlap_pointer(kitchen, rid):
    """ON DELETE SET NULL underneath the save path, for any route to a deleted step."""
    dough, butter = _two_waits(kitchen, rid)
    with kitchen.conn() as c:
        c.execute("PRAGMA foreign_keys = ON")
        assert c.execute("SELECT alongside_step_id FROM recipe_waits WHERE when_kind='alongside'"
                         ).fetchone()[0] == dough
        c.execute("DELETE FROM recipe_steps WHERE id=?", (dough,))
        c.commit()
        assert c.execute("SELECT alongside_step_id FROM recipe_waits WHERE step_id=?",
                         (butter,)).fetchone()[0] is None


def test_an_overlap_pointing_at_another_recipes_step_is_refused(kitchen, rid):
    other = kitchen.client.post("/api/recipes", json={
        "name": "Elsewhere", "ingredients": [], "steps": ["Not this recipe."]}).get_json()["id"]
    stolen = _steps(kitchen, other)[0]["id"]
    _save_steps(kitchen, rid, ["Chill the dough.", "Make the butter."], [])
    rows = _steps(kitchen, rid)
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "chilling", "label": "overnight", "step_id": rows[1]["id"],
                  "when_kind": "alongside", "alongside_step_id": stolen}])
    w = _waits(kitchen, rid)[0]
    assert (w["when_kind"], w["alongside_step_id"]) == ("always", None)


def test_alongside_reads_as_a_qualifier_not_a_second_step_link():
    """The words the page shows. A pointer the server could not resolve leaves alongside_no null, and
    the wait then reads without the phrase rather than with a wrong number."""
    import planahead
    assert planahead.alongside_label({"alongside_no": 3}) == " alongside step 3"
    assert planahead.alongside_label({"alongside_no": None}) == ""
    assert planahead.alongside_label({}) == ""


# ---- 057: the ALTERNATIVE points at the step that describes it -----------------------------------
# Measured over the 7 stored extensions: 5 state the alternative in the wait's own step, 2 describe
# it somewhere else (beans' quick soak at step 3, brioche-bread's shorter option at step 11).

def _ext_wait(kitchen, rid, *, ext_step="pick"):
    """Two steps, a wait on the first, and its alternative described by the second."""
    _save_steps(kitchen, rid, ["Soak overnight.", "Or quick soak for 90 minutes."], [])
    rows = _steps(kitchen, rid)
    soak, quick = rows[0]["id"], rows[1]["id"]
    target = {"pick": quick, "self": soak, "none": None}[ext_step]
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "soaking", "label": "8 hr or overnight", "step_id": soak,
                  "ext_label": "or a 90 minute quick soak instead", "ext_step_id": target}])
    return soak, quick


def test_the_alternative_names_its_own_step(kitchen, rid):
    soak, quick = _ext_wait(kitchen, rid)
    w = _waits(kitchen, rid)[0]
    assert w["ext_step_id"] == quick
    assert w["ext_no"] == 2, "the PRINTED number of the step describing the alternative"
    assert w["step_no"] == 1, "and the wait's own step number is unaffected"


def test_an_alternative_in_the_waits_own_step_stores_no_link(kitchen, rid):
    """⚠️ NULL RATHER THAN A COPY OF step_id. 5 of the 7 extensions say the alternative in the same
    sentence as the wait, and printing "(step 1)" a second time on that line says nothing."""
    _ext_wait(kitchen, rid, ext_step="self")
    w = _waits(kitchen, rid)[0]
    assert (w["ext_step_id"], w["ext_no"]) == (None, None)


def test_a_link_with_no_alternative_to_hang_on_is_dropped(kitchen, rid):
    """Same rule the extension minutes already follow: no ext_label, no extension."""
    _save_steps(kitchen, rid, ["Soak overnight.", "Something else."], [])
    rows = _steps(kitchen, rid)
    _save_steps(kitchen, rid, [{"id": r["id"], "text": r["text"]} for r in rows],
                [{"kind": "soaking", "label": "overnight", "step_id": rows[0]["id"],
                  "ext_step_id": rows[1]["id"]}])
    assert _waits(kitchen, rid)[0]["ext_step_id"] is None


def test_deleting_the_alternatives_step_clears_the_link(kitchen, rid):
    """The same treatment step_id and alongside_step_id get. A step that is gone cannot be named."""
    soak, quick = _ext_wait(kitchen, rid)
    _save_steps(kitchen, rid, [{"id": soak, "text": "Soak overnight."}],
                [{"kind": "soaking", "label": "8 hr or overnight", "step_id": soak,
                  "ext_label": "or a 90 minute quick soak instead", "ext_step_id": quick}])
    w = _waits(kitchen, rid)[0]
    assert (w["ext_step_id"], w["ext_no"]) == (None, None)
    assert w["step_id"] == soak, "the wait's own link is untouched"


def test_an_ext_step_id_from_another_recipe_is_refused(kitchen, rid):
    """The step-id set is scoped to this recipe, exactly as it is for the other two pointers."""
    soak, quick = _ext_wait(kitchen, rid)
    other = kitchen.client.post("/api/recipes", json={
        "name": "Other", "ingredients": [], "steps": ["Its own step."]}).get_json()["id"]
    foreign = _steps(kitchen, other)[0]["id"]
    _save_steps(kitchen, rid, [{"id": soak, "text": "Soak overnight."}],
                [{"kind": "soaking", "label": "overnight", "step_id": soak,
                  "ext_label": "or quick", "ext_step_id": foreign}])
    assert _waits(kitchen, rid)[0]["ext_step_id"] is None


def test_the_alternatives_link_is_not_in_the_snapshot():
    """⚠️ PROVENANCE, NOT CONTENT, the same call step_position lost. Moving a step would otherwise
    read as an edit to the wait."""
    from snapshot_serialize import SNAPSHOT_WAIT_FIELDS
    assert "ext_step_id" not in SNAPSHOT_WAIT_FIELDS
    assert "step_id" not in SNAPSHOT_WAIT_FIELDS
    assert "alongside_step_id" not in SNAPSHOT_WAIT_FIELDS


# ---------------------------------------------------------------------------------------------
# Migration 056 is a TABLE REBUILD, and a rebuild that is not one transaction is a wedged database.
# ---------------------------------------------------------------------------------------------

def _waits_fixture(tmp_path):
    """The pre-056 recipe_waits with one row in it, which is all the migration needs to touch."""
    db = tmp_path / "pre056.db"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE recipes (id TEXT PRIMARY KEY);"
        "CREATE TABLE recipe_steps (id INTEGER PRIMARY KEY);"
        "CREATE TABLE recipe_waits ("
        " id INTEGER PRIMARY KEY, recipe_id TEXT NOT NULL, position INTEGER NOT NULL,"
        " kind TEXT NOT NULL, label TEXT NOT NULL, min_minutes INTEGER, max_minutes INTEGER,"
        " when_kind TEXT NOT NULL DEFAULT 'always', when_label TEXT, applies_to TEXT,"
        " ext_label TEXT, ext_min_minutes INTEGER, ext_max_minutes INTEGER, step_id INTEGER,"
        " UNIQUE (recipe_id, position));")
    c.execute("INSERT INTO recipes VALUES ('beans')")
    c.execute("INSERT INTO recipe_waits (recipe_id, position, kind, label) "
              "VALUES ('beans', 0, 'soaking', '8 hr')")
    c.commit()
    c.close()
    return db


def test_migration_056_rolls_back_whole_when_it_is_interrupted(tmp_path):
    """⚠️ THE ONE THING A TABLE REBUILD MUST DO, AND THE ONLY REASON 056 CARRIES A BEGIN.

    migrate.py applies each file through sqlite3's executescript, which opens no transaction, so
    every statement in a migration auto-commits on its own. 056 is CREATE, INSERT, DROP, RENAME.
    Interrupted between the DROP and the RENAME, the unwrapped version commits the drop: recipe_waits
    is gone, every recipe page 500s, the filename was never recorded, and migrate.py's retry dies
    forever on "table recipe_waits_new already exists". Recovery is hand SQL.

    This replays the real file truncated one statement after the DROP and closes the connection,
    which is what a Ctrl-C, a laptop sleep or a crash does.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent
           / "migrations" / "056_wait_alongside.sql").read_text()
    cut = src.index("ALTER TABLE recipe_waits_new RENAME TO recipe_waits;")

    db = _waits_fixture(tmp_path)
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(src[:cut])
    c.close()                                    # the crash: no COMMIT was ever reached

    c = sqlite3.connect(db)
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'recipe_waits%'")}
    assert tables == {"recipe_waits"}, f"the rebuild left {tables} behind"
    assert c.execute("SELECT count(*) FROM recipe_waits").fetchone()[0] == 1, "the row survived"

    c.executescript(src)                         # and migrate.py's next run recovers
    c.commit()
    cols = {r[1] for r in c.execute("PRAGMA table_info(recipe_waits)")}
    assert "alongside_step_id" in cols
    assert c.execute("SELECT count(*) FROM recipe_waits").fetchone()[0] == 1
    c.close()


def test_migration_056_is_idempotent_if_its_filename_was_never_recorded(tmp_path):
    """The same window, one statement later: applied but unrecorded, so migrate.py runs it again."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent
           / "migrations" / "056_wait_alongside.sql").read_text()
    db = _waits_fixture(tmp_path)
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(src)
    c.executescript(src)                         # the re-run, with no schema_migrations row to stop it
    c.commit()
    assert c.execute("SELECT count(*) FROM recipe_waits").fetchone()[0] == 1
    assert {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'recipe_waits%'")} \
        == {"recipe_waits"}
    c.close()
