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
