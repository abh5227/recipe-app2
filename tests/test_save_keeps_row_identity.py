"""A save keeps the rows it was given, so an unchanged save leaves the recipe byte-equal.

⚠️ THE DEFECT, OBSERVED ON LIVE. write_plan_ahead deleted every wait and every storage row of a
recipe and inserted fresh ones, so each row came back with a new AUTOINCREMENT id. The snapshot
carries the wait id, so a save that changed NOTHING changed the snapshot bytes, the recipe stopped
being byte-equal to its baseline, and it dropped out of the short-circuit for good.

Measured on live after one spot-check save of brioche-bread: the entire difference between its
baseline and its current content was `"id": 12` becoming `"id": 108` and `"id": 13` becoming
`"id": 109`. diff_snapshots compares by meaning and returned 0 entries, so nothing showed on the
page and the 49-over-20 mark count did not move. The only visible effect was the short-circuit going
275 of 300 to 274, which also means that number decays by one for every recipe ever saved.

THE RULE: a save UPDATES the rows it matched, in place, matched by wording the same way the minutes
are carried (wording first, consumed once). A row gets a new id only when it is genuinely new, and a
row nothing matched is deleted.

This file is the identity half. tests/test_save_keeps_reviewed_minutes.py is the minutes half, and
the fixture is shared with it because the two rules are two halves of one sentence: a save never
changes a wait the cook did not edit.
"""
import pytest

import app
import harness  # noqa: F401
from test_save_keeps_reviewed_minutes import _save, _state, dish  # noqa: F401


def _ids(kitchen, rid):
    with kitchen.conn() as c:
        w = [tuple(r) for r in c.execute(
            "SELECT id, position, label FROM recipe_waits WHERE recipe_id=? ORDER BY position",
            (rid,))]
        st = [tuple(r) for r in c.execute(
            "SELECT id, position, label FROM recipe_storage WHERE recipe_id=? ORDER BY position",
            (rid,))]
    return w, st


def _bytes(rid):
    with app.orm_session() as s:
        return app.serialize_recipe_content(s, rid)


def _baseline(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? "
                         "AND reason='original'", (rid,)).fetchone()[0]


# ---- the rule ------------------------------------------------------------------------------------

def test_a_save_that_changes_nothing_keeps_every_row_id(dish, kitchen):
    before = _ids(kitchen, dish)
    _save(kitchen, dish)
    assert _ids(kitchen, dish) == before


def test_a_save_that_changes_nothing_keeps_the_snapshot_bytes(dish, kitchen):
    """The whole point. Byte-equal is what the short-circuit tests, and it is what broke."""
    before = _bytes(dish)
    _save(kitchen, dish)
    assert _bytes(dish) == before


def test_a_save_that_changes_nothing_leaves_the_recipe_byte_equal_to_its_baseline(dish, kitchen):
    """Stronger, and the thing a cook actually sees: the recipe stays in the short-circuit."""
    _save(kitchen, dish)
    assert _bytes(dish) == _baseline(kitchen, dish), "the recipe fell out of the short-circuit"
    with app.orm_session() as s:
        assert app._recipe_annotations(s, dish) == []


def test_saving_twice_changes_nothing_either(dish, kitchen):
    """A second save must not start a slow drift that the first one hid."""
    base = _baseline(kitchen, dish)
    for _ in range(3):
        _save(kitchen, dish)
        assert _bytes(dish) == base


# ---- reordering, which is where the UNIQUE (recipe_id, position) bites --------------------------

def test_reordering_keeps_the_ids_and_moves_only_the_positions(dish, kitchen):
    """⚠️ THE CASE THAT NEEDS THE POSITION DANCE. Both tables carry UNIQUE (recipe_id, position), so
    writing a swapped pair straight back collides on the first UPDATE. The rows go to negative
    positions first and then take their final places."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    before = {w[2]: w[0] for w in _ids(kitchen, dish)[0]}        # label -> id
    swapped = list(reversed(d["waits"]))
    _save(kitchen, dish, waits=[{"kind": w["kind"], "label": w["label"],
                                 "ext_label": w["ext_label"], "when_kind": w["when_kind"],
                                 "when_label": w["when_label"], "step_id": w["step_id"],
                                 "alongside_step_id": w["alongside_step_id"],
                                 "ext_step_id": w["ext_step_id"]} for w in swapped])
    after = _ids(kitchen, dish)[0]
    assert [w[1] for w in after] == [0, 1], "positions were not renumbered"
    assert {w[2]: w[0] for w in after} == before, "a reorder changed the row ids"
    assert [w[2] for w in after] == [w["label"] for w in swapped], "the order did not change"


def test_reordering_storage_keeps_its_ids_too(dish, kitchen):
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    before = {x[2]: x[0] for x in _ids(kitchen, dish)[1]}
    swapped = list(reversed(d["storage"]))
    _save(kitchen, dish, storage=[{"where_kept": x["where_kept"], "applies_to": x["applies_to"],
                                   "label": x["label"]} for x in swapped])
    after = _ids(kitchen, dish)[1]
    assert [x[1] for x in after] == [0, 1]
    assert {x[2]: x[0] for x in after} == before
    assert [x[2] for x in after] == [x["label"] for x in swapped]


# ---- added, removed and edited rows -------------------------------------------------------------

def test_only_a_genuinely_new_row_gets_a_new_id(dish, kitchen):
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    before = {w[2]: w[0] for w in _ids(kitchen, dish)[0]}
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"],
              "when_kind": w["when_kind"], "when_label": w["when_label"],
              "step_id": w["step_id"], "alongside_step_id": w["alongside_step_id"],
              "ext_step_id": w["ext_step_id"]} for w in d["waits"]]
    waits.append({"kind": "chilling", "label": "2 hr"})
    _save(kitchen, dish, waits=waits)
    after = {w[2]: w[0] for w in _ids(kitchen, dish)[0]}
    assert len(after) == len(before) + 1
    for label, i in before.items():
        assert after[label] == i, f"{label} was given a new id"
    assert after["2 hr"] not in before.values()


def test_a_removed_row_is_deleted_and_the_survivors_keep_their_ids(dish, kitchen):
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    before = {w[2]: w[0] for w in _ids(kitchen, dish)[0]}
    keep = d["waits"][0]
    _save(kitchen, dish, waits=[{"kind": keep["kind"], "label": keep["label"],
                                 "ext_label": keep["ext_label"], "when_kind": keep["when_kind"],
                                 "when_label": keep["when_label"], "step_id": keep["step_id"],
                                 "alongside_step_id": keep["alongside_step_id"],
                                 "ext_step_id": keep["ext_step_id"]}])
    after = _ids(kitchen, dish)[0]
    assert len(after) == 1, "the dropped wait was not deleted"
    assert after[0][0] == before[keep["label"]], "the surviving wait was given a new id"
    assert after[0][1] == 0


def test_an_edited_wait_keeps_its_id_and_is_re_read(dish, kitchen):
    """Decision 1 and this rule together. Editing the WORDING re-reads the minutes, which is the
    point of decision 1, and the row is still the same row."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    target = next(w for w in d["waits"] if w["label"] == "30 min")
    waits = [{"kind": w["kind"], "label": ("45 min" if w["label"] == "30 min" else w["label"]),
              "ext_label": w["ext_label"], "when_kind": w["when_kind"],
              "when_label": w["when_label"], "step_id": w["step_id"],
              "alongside_step_id": w["alongside_step_id"],
              "ext_step_id": w["ext_step_id"]} for w in d["waits"]]
    _save(kitchen, dish, waits=waits)
    with kitchen.conn() as c:
        row = c.execute("SELECT id, label, min_minutes, max_minutes FROM recipe_waits "
                        "WHERE recipe_id=? AND label='45 min'", (dish,)).fetchone()
    assert row is not None, "the edited wait is gone"
    assert row[0] == target["id"], "an edit should not mint a new row"
    assert (row[2], row[3]) == (45, 45), "an edited wait must be re-read"


def test_an_unedited_wait_keeps_its_minutes_when_its_neighbour_is_edited(dish, kitchen):
    """Decision 1 still holds. The reviewed 60 is the figure read_duration would NOT produce."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": ("45 min" if w["label"] == "30 min" else w["label"]),
              "ext_label": w["ext_label"], "when_kind": w["when_kind"],
              "when_label": w["when_label"], "step_id": w["step_id"],
              "alongside_step_id": w["alongside_step_id"],
              "ext_step_id": w["ext_step_id"]} for w in d["waits"]]
    _save(kitchen, dish, waits=waits)
    with kitchen.conn() as c:
        ext = c.execute("SELECT ext_min_minutes, ext_max_minutes FROM recipe_waits "
                        "WHERE recipe_id=? AND ext_label IS NOT NULL", (dish,)).fetchone()
    assert tuple(ext) == (60, 60), "the reviewed extension was re-read"


def test_two_rows_with_the_same_wording_take_one_row_each(dish, kitchen):
    """Consume-once, which is why the carry pops rather than peeks. Two identical labels must not
    both claim the first stored row, which would delete the second and mint a new id."""
    _save(kitchen, dish, waits=[{"kind": "resting", "label": "1 hr"},
                                {"kind": "resting", "label": "1 hr"}])
    first = _ids(kitchen, dish)[0]
    assert len(first) == 2 and first[0][0] != first[1][0]
    _save(kitchen, dish)
    assert _ids(kitchen, dish)[0] == first, "a repeated wording lost a row id on re-save"


def test_an_explicit_empty_list_still_deletes_every_row(dish, kitchen):
    _save(kitchen, dish, waits=[], storage=[])
    assert _ids(kitchen, dish) == ([], [])


def test_an_omitted_list_still_leaves_the_rows_alone(dish, kitchen):
    """The absent-key rule, re-checked here because the deletion now runs off the same branch."""
    before = _ids(kitchen, dish)
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    r = kitchen.client.put(f"/api/recipes/{dish}", json={
        "name": d["recipe"]["name"],
        "ingredients": [{"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
                         "text": x["label"]} for x in d["ingredients"]],
        "steps": [{"id": s["id"], "text": s["text"]} for s in d["steps"]]})
    assert r.status_code == 200, r.get_json()
    assert _ids(kitchen, dish) == before


def test_rotating_three_rows_keeps_every_id(dish, kitchen):
    """A two-row swap collides on one UPDATE. A rotation collides on every one of them, which is the
    case that proves the negative-position pass rather than getting lucky on ordering."""
    three = [{"kind": "rising", "label": "one"},
             {"kind": "resting", "label": "two"},
             {"kind": "chilling", "label": "three"}]
    _save(kitchen, dish, waits=three)
    first = {w[2]: w[0] for w in _ids(kitchen, dish)[0]}
    assert len(first) == 3
    rotated = [three[2], three[0], three[1]]
    _save(kitchen, dish, waits=rotated)
    after = _ids(kitchen, dish)[0]
    assert [w[1] for w in after] == [0, 1, 2]
    assert [w[2] for w in after] == ["three", "one", "two"]
    assert {w[2]: w[0] for w in after} == first, "a rotation changed the row ids"
