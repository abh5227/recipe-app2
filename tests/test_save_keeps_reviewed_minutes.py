"""A save never changes a wait the cook did not edit.

⚠️ WHY A STORED FIGURE OUTRANKS A FRESH READ. The minutes behind a wait are read from what a person
typed, and some of them were read by a REVIEWER rather than by planahead.read_duration.
brioche-bread's extension says "or an hour of fridge rest if you skip the overnight proof" and
carries the reviewed 60; read_duration answers 480, because the word overnight is in the sentence.
write_plan_ahead re-derived every row on every save, so a save overwrote the reviewed figure with the
worse one, and it did so on a save that changed nothing at all.

Measured over the 107 stored waits: 0 labels and exactly 1 extension re-read differently from what is
stored. One row today, and the rule is what matters. The page showed it as a wait "modified" entry
whose `from` and `to` were the same words, because the printed label does not include the minutes.

THE RULE: stored minutes are kept unless that wait's own wording changed. Only an edited wait is
re-read. read_duration is untouched; its reading of that sentence is a separate defect on the roadmap
with the Round B parser item.
"""
import pytest

import app
import harness  # noqa: F401


@pytest.fixture
def dish(kitchen):
    """A recipe with two waits and two storage rows, one of each carrying minutes that a fresh read
    of the label would NOT produce — the reviewed-figure case, reproduced."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Carry", "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": ["Mix it.", "Rest it."]}).get_json()["id"]
    kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Carry",
        "ingredients": [{"quantity": "2", "unit": "", "text": "eggs"}],
        "steps": [{"id": s["id"], "text": s["text"]}
                  for s in kitchen.client.get(f"/api/recipes/{rid}").get_json()["steps"]],
        "waits": [
            {"kind": "rising", "label": "8-12 hr",
             "ext_label": "or an hour of fridge rest if you skip the overnight proof"},
            {"kind": "resting", "label": "30 min"},
        ],
        "storage": [{"where_kept": "fridge", "label": "keeps 3 days"},
                    {"where_kept": "freezer", "label": "up to 1 month"}],
    })
    # the reviewed figure, written the way the corpus pass wrote it: 60, not read_duration's 480
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_waits SET ext_min_minutes=60, ext_max_minutes=60 "
                  "WHERE recipe_id=? AND ext_label IS NOT NULL", (rid,))
        c.execute("UPDATE recipe_storage SET min_minutes=4320 WHERE recipe_id=? AND label=?",
                  (rid, "keeps 3 days"))
        c.commit()
    # ⚠️ AND THE BASELINE IS PATCHED IN LOCKSTEP, which is what makes this fixture the live state
    #    rather than a convenient one. The corpus pass wrote the waits into the live row AND into the
    #    reason='original' snapshot in one transaction, so a recipe's waits are part of its birth
    #    state and carry no mark. A fixture that adds waits after birth would show them as additions
    #    forever, and the mark this file is about would be invisible underneath them.
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, rid)
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (blob, rid))
        c.commit()
    with app.orm_session() as s:
        assert app._recipe_annotations(s, rid) == [], "the fixture should start with no marks"
    return rid


def _state(kitchen, rid):
    with kitchen.conn() as c:
        w = [tuple(r) for r in c.execute(
            "SELECT label, min_minutes, max_minutes, ext_label, ext_min_minutes, ext_max_minutes "
            "FROM recipe_waits WHERE recipe_id=? ORDER BY position", (rid,))]
        st = [tuple(r) for r in c.execute(
            "SELECT label, min_minutes, max_minutes FROM recipe_storage WHERE recipe_id=? "
            "ORDER BY position", (rid,))]
    return w, st


def _save(kitchen, rid, waits=None, storage=None):
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    body = {"name": d["recipe"]["name"],
            "ingredients": [{"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
                             "text": x["label"]} for x in d["ingredients"]],
            "steps": [{"id": s["id"], "text": s["text"]} for s in d["steps"]],
            "waits": ([{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"],
                        "when_kind": w["when_kind"], "when_label": w["when_label"],
                        "step_id": w["step_id"], "alongside_step_id": w["alongside_step_id"],
                        "ext_step_id": w["ext_step_id"]} for w in d["waits"]]
                      if waits is None else waits),
            "storage": ([{"where_kept": x["where_kept"], "applies_to": x["applies_to"],
                          "label": x["label"]} for x in d["storage"]]
                        if storage is None else storage)}
    r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200, r.get_json()
    return r


# ---- the rule ------------------------------------------------------------------------------------

def test_a_save_that_changes_nothing_keeps_every_stored_minute(dish, kitchen):
    before = _state(kitchen, dish)
    assert before[0][0][4] == 60, "fixture should carry the reviewed 60"
    _save(kitchen, dish)
    assert _state(kitchen, dish) == before


def test_the_reviewed_extension_survives_a_save_and_is_not_re_read(dish, kitchen):
    """Andy's named case. read_duration reads that sentence as 480; the stored figure is 60."""
    import planahead
    label = "or an hour of fridge rest if you skip the overnight proof"
    assert planahead.read_duration(label) == (480, None), "the parse defect this protects against"
    _save(kitchen, dish)
    w, _ = _state(kitchen, dish)
    assert (w[0][4], w[0][5]) == (60, 60), f"the save re-derived the extension: {w[0]}"


def test_a_save_that_changes_nothing_leaves_no_mark(dish, kitchen):
    """The user-visible half. The entry it used to produce had `from` and `to` equal, because the
    printed label does not include the minutes — a mark saying nothing changed."""
    _save(kitchen, dish)
    with app.orm_session() as s:
        ann = app._recipe_annotations(s, dish)
    assert [a for a in ann if a["kind"] == "wait"] == [], ann


def test_an_edited_wait_is_re_read(dish, kitchen):
    """The other direction, and the reason this is a carry rather than a freeze. A cook who rewrites
    the wording means the figure to follow it."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"]}
             for w in d["waits"]]
    waits[1]["label"] = "2 hr"                      # was "30 min"
    _save(kitchen, dish, waits=waits)
    w, _ = _state(kitchen, dish)
    assert (w[1][1], w[1][2]) == (120, 120), f"an edited wait was not re-read: {w[1]}"
    assert (w[0][4], w[0][5]) == (60, 60), "and the untouched wait kept its reviewed figure"


def test_editing_the_extension_re_reads_the_extension_and_not_the_wait(dish, kitchen):
    """Two pieces of wording on one row, decided separately."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"]}
             for w in d["waits"]]
    waits[0]["ext_label"] = "or 45 min on the counter"
    _save(kitchen, dish, waits=waits)
    w, _ = _state(kitchen, dish)
    assert (w[0][4], w[0][5]) == (45, 45), f"the edited extension was not re-read: {w[0]}"
    assert (w[0][1], w[0][2]) == (480, 720), "the wait's own minutes were re-read anyway"


def test_a_reordered_wait_keeps_its_minutes(dish, kitchen):
    """The carry is keyed on wording, not on position, so dragging the panel does not re-read."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"]}
             for w in d["waits"]][::-1]
    _save(kitchen, dish, waits=waits)
    w, _ = _state(kitchen, dish)
    assert w[1][4] == 60, f"a reorder lost the reviewed figure: {w}"


def test_a_new_wait_is_read_normally(dish, kitchen):
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"]}
             for w in d["waits"]]
    waits.append({"kind": "soaking", "label": "4 hr"})
    _save(kitchen, dish, waits=waits)
    w, _ = _state(kitchen, dish)
    assert (w[2][1], w[2][2]) == (240, 240)
    assert w[0][4] == 60


def test_two_waits_with_the_same_wording_consume_one_row_each(dish, kitchen):
    """Consume-once, the same reason the ingredient carry is. pepperoni-rolls rises twice."""
    _save(kitchen, dish, waits=[{"kind": "rising", "label": "1 hr rise"},
                                {"kind": "rising", "label": "1 hr rise"}])
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_waits SET min_minutes=11 WHERE recipe_id=? AND position=0", (dish,))
        c.execute("UPDATE recipe_waits SET min_minutes=22 WHERE recipe_id=? AND position=1", (dish,))
        c.commit()
    _save(kitchen, dish, waits=[{"kind": "rising", "label": "1 hr rise"},
                                {"kind": "rising", "label": "1 hr rise"}])
    w, _ = _state(kitchen, dish)
    assert [r[1] for r in w] == [11, 22], f"one row's figure was taken twice: {w}"


def test_storage_gets_the_same_rule(dish, kitchen):
    """Storage re-derived on save too, so it carries as well. One piece of wording, no extension."""
    before, before_st = _state(kitchen, dish)
    assert before_st[0][1] == 4320, "fixture should carry a figure a fresh read would not produce"
    _save(kitchen, dish)
    assert _state(kitchen, dish)[1] == before_st


def test_an_edited_storage_row_is_re_read(dish, kitchen):
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    st = [{"where_kept": x["where_kept"], "label": x["label"]} for x in d["storage"]]
    st[0]["label"] = "keeps 5 days"
    _save(kitchen, dish, storage=st)
    _, got = _state(kitchen, dish)
    assert got[0][1] == 7200, f"an edited storage row was not re-read: {got[0]}"


def test_whitespace_is_folded_but_case_is_not(dish, kitchen):
    """A re-wrap is not an edit. Changing a letter is."""
    d = kitchen.client.get(f"/api/recipes/{dish}").get_json()
    waits = [{"kind": w["kind"], "label": w["label"], "ext_label": w["ext_label"]}
             for w in d["waits"]]
    waits[0]["ext_label"] = "or an  hour of fridge rest if you skip the  overnight proof"
    _save(kitchen, dish, waits=waits)
    assert _state(kitchen, dish)[0][0][4] == 60, "a re-wrap counted as an edit"

    waits[0]["ext_label"] = "Or an hour of fridge rest if you skip the overnight proof"
    _save(kitchen, dish, waits=waits)
    assert _state(kitchen, dish)[0][0][4] == 480, "a changed letter did not count as an edit"
