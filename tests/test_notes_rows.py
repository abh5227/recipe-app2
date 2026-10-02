"""A note is a row: it keeps its id, it marks once, and a reference to a step survives the steps
moving.

⚠️ ROWS UPDATE IN PLACE FROM DAY ONE. Waits got this late, and the day they did not have it a single
no-change save on brioche-bread gave every wait a new AUTOINCREMENT id, moved the snapshot bytes and
cost the recipe its byte-equal short-circuit permanently, with 0 annotation entries and nothing
visible on the page. Notes start with _match_rows, and these tests are what say so.
"""
import json
import sqlite3

import pytest

import app
import harness  # noqa: F401


@pytest.fixture
def dish(kitchen):
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Noted", "ingredients": [{"qty": "1", "text": "flour"}],
        "steps": ["Mix.", "Rest.", "Bake."]}).get_json()["id"]
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    _save(kitchen, rid, d, notes=[
        {"text": "Soaking is optional.", "kind": "notes"},
        {"text": "Keeps three days.", "kind": "storage"},
    ])
    return rid


def _save(kitchen, rid, d, **over):
    body = {
        "name": d["recipe"]["name"],
        "ingredients": [{"id": x["id"], "quantity": x["quantity"] or "", "unit": x["unit"] or "",
                         "text": x["label"]} for x in d["ingredients"]],
        "steps": [{"id": s["id"], "text": s["text"]} for s in d["steps"]],
    }
    body.update(over)
    r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200, r.get_json()
    return r


def _notes(kitchen, rid):
    with kitchen.conn() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT * FROM recipe_notes WHERE recipe_id=? ORDER BY position", (rid,))]


def _get(kitchen, rid):
    return kitchen.client.get(f"/api/recipes/{rid}").get_json()


def _blob(rid):
    with app.orm_session() as s:
        return app.serialize_recipe_content(s, rid)


def _marks(rid):
    with app.orm_session() as s:
        return app._recipe_annotations(s, rid)


# ---- the rows ---------------------------------------------------------------------------------

def test_a_note_becomes_a_row_with_its_kind(dish, kitchen):
    rows = _notes(kitchen, dish)
    assert [r["text"] for r in rows] == ["Soaking is optional.", "Keeps three days."]
    assert [r["kind"] for r in rows] == ["notes", "storage"]
    assert [r["position"] for r in rows] == [0, 1]


def test_the_old_column_is_a_derived_copy(dish, kitchen):
    with kitchen.conn() as c:
        col = c.execute("SELECT notes FROM recipes WHERE id=?", (dish,)).fetchone()[0]
    assert col == "Soaking is optional.\n\nKeeps three days."


def test_an_unchanged_save_keeps_every_note_id(dish, kitchen):
    before = [r["id"] for r in _notes(kitchen, dish)]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": n["text"], "kind": n["kind"]} for n in d["notes"]])
    assert [r["id"] for r in _notes(kitchen, dish)] == before


def test_an_unchanged_save_leaves_the_snapshot_bytes_alone(dish, kitchen):
    before = _blob(dish)
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": n["text"], "kind": n["kind"]} for n in d["notes"]])
    assert _blob(dish) == before


def test_three_unchanged_saves_in_a_row_change_nothing(dish, kitchen):
    before = _blob(dish)
    for _ in range(3):
        d = _get(kitchen, dish)
        _save(kitchen, dish, d, notes=[{"text": n["text"], "kind": n["kind"]} for n in d["notes"]])
    assert _blob(dish) == before


def test_a_reorder_keeps_both_ids(dish, kitchen):
    """⚠️ UNIQUE (recipe_id, position) MEANS A SWAP COLLIDES unless positions are pushed out of the
    way first. This is the test that fails if _apply_rows' negative-position pass is removed."""
    before = {r["text"]: r["id"] for r in _notes(kitchen, dish)}
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": d["notes"][1]["text"], "kind": d["notes"][1]["kind"]},
                                   {"text": d["notes"][0]["text"], "kind": d["notes"][0]["kind"]}])
    after = {r["text"]: r["id"] for r in _notes(kitchen, dish)}
    assert after == before
    assert [r["text"] for r in _notes(kitchen, dish)] == ["Keeps three days.", "Soaking is optional."]


def test_an_edited_note_keeps_its_id(dish, kitchen):
    before = [r["id"] for r in _notes(kitchen, dish)]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "Soaking is required.", "kind": "notes"},
                                   {"text": "Keeps three days.", "kind": "storage"}])
    rows = _notes(kitchen, dish)
    assert [r["id"] for r in rows] == before
    assert rows[0]["text"] == "Soaking is required."


def test_a_genuinely_new_note_gets_a_new_id(dish, kitchen):
    before = [r["id"] for r in _notes(kitchen, dish)]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": n["text"], "kind": n["kind"]} for n in d["notes"]]
                                  + [{"text": "A third thought.", "kind": "tips"}])
    rows = _notes(kitchen, dish)
    assert [r["id"] for r in rows[:2]] == before
    assert rows[2]["id"] not in before


def test_a_deleted_note_is_deleted(dish, kitchen):
    before = [r["id"] for r in _notes(kitchen, dish)]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": d["notes"][0]["text"], "kind": d["notes"][0]["kind"]}])
    rows = _notes(kitchen, dish)
    assert [r["id"] for r in rows] == [before[0]]
    assert before[1] not in [r["id"] for r in rows]


def test_replacing_a_notes_words_in_place_is_an_edit_not_a_swap(dish, kitchen):
    """⚠️ WORDING FIRST, THEN ORDER, AND THE SECOND PASS IS WHY THIS KEEPS ITS ID. A note whose text
    is replaced outright still sits in the slot the old one did, so it is that row reworded. Reading
    it as a deletion plus an addition would tell the cook a note vanished and another appeared, and
    would climb the id sequence every time someone rewrote a sentence."""
    before = [r["id"] for r in _notes(kitchen, dish)]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "Soaking is optional.", "kind": "notes"},
                                   {"text": "A completely different thought.", "kind": "tips"}])
    rows = _notes(kitchen, dish)
    assert [r["id"] for r in rows] == before
    assert rows[1]["text"] == "A completely different thought."


def test_an_absent_notes_key_keeps_the_rows(dish, kitchen):
    """⚠️ ABSENT IS NOT EMPTY. This is the rule that once erased a headnote."""
    before = _notes(kitchen, dish)
    d = _get(kitchen, dish)
    _save(kitchen, dish, d)                       # no notes key at all
    assert _notes(kitchen, dish) == before


def test_an_explicit_empty_list_clears_the_rows(dish, kitchen):
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[])
    assert _notes(kitchen, dish) == []
    with kitchen.conn() as c:
        assert c.execute("SELECT notes FROM recipes WHERE id=?", (dish,)).fetchone()[0] is None


def test_a_notes_string_from_an_old_client_still_works(dish, kitchen):
    """The deploy window in the other direction: the previous client sends one textarea of prose."""
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes="Tip: one thing.\n\nAnother thing.")
    rows = _notes(kitchen, dish)
    assert [r["text"] for r in rows] == ["Tip: one thing.", "Another thing."]
    assert [r["kind"] for r in rows] == ["tips", "notes"]


# ---- marks ------------------------------------------------------------------------------------

def test_a_note_edit_marks_once(dish, kitchen):
    """⚠️ ONCE, ON ITS ROW. recipes.notes is a derived copy of the rows, so diffing both would mark
    one edit twice, the second entry reading as the whole notes field having been replaced."""
    with app.orm_session() as s:
        app.snapshot_original.__wrapped__ if False else None
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (_blob(dish), dish))
        c.commit()
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "Soaking is required.", "kind": "notes"},
                                   {"text": "Keeps three days.", "kind": "storage"}])
    marks = _marks(dish)
    assert len(marks) == 1, marks
    assert marks[0]["kind"] == "note"


def test_a_capitalization_only_edit_does_not_mark(dish, kitchen):
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (_blob(dish), dish))
        c.commit()
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "soaking is optional", "kind": "notes"},
                                   {"text": "Keeps three days.", "kind": "storage"}])
    assert _marks(dish) == []


def test_a_recipe_with_no_notes_has_no_notes_key_in_its_snapshot(kitchen):
    """⚠️ THE OMIT-WHEN-EMPTY TRICK, which is what kept all 300 baselines byte-equal the day
    migration 060 shipped."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Bare", "ingredients": [{"qty": "1", "text": "x"}], "steps": ["Do."]}).get_json()["id"]
    assert '"notes":[' not in _blob(rid)
    assert _marks(rid) == []


# ---- the step link and the step reference -----------------------------------------------------

def test_a_note_can_point_at_a_step(dish, kitchen):
    d = _get(kitchen, dish)
    sid = d["steps"][1]["id"]
    _save(kitchen, dish, d, notes=[{"text": "Soaking is optional.", "kind": "notes", "step_id": sid}])
    assert _notes(kitchen, dish)[0]["step_id"] == sid
    assert _get(kitchen, dish)["notes"][0]["step_no"] == 2


def test_a_link_to_a_heading_is_stored_and_not_printed(dish, kitchen):
    """⚠️ STORING A POINTER AND PRINTING IT ARE DIFFERENT QUESTIONS. The same rule waits follow: a
    conversion has to be reversible, so the id is kept, and the number is simply not resolved."""
    d = _get(kitchen, dish)
    sid = d["steps"][1]["id"]
    _save(kitchen, dish, d, notes=[{"text": "A note.", "kind": "notes", "step_id": sid}])
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_steps SET is_heading=1 WHERE id=?", (sid,))
        c.commit()
    got = _get(kitchen, dish)["notes"][0]
    assert got["step_id"] == sid, "the link must survive the conversion"
    assert got["step_no"] is None, "but it must not print a number"
    assert got["step_ok"] is False


def test_a_link_to_another_recipes_step_is_refused(dish, kitchen):
    other = kitchen.client.post("/api/recipes", json={
        "name": "Other", "ingredients": [{"qty": "1", "text": "x"}], "steps": ["Do."]}).get_json()["id"]
    foreign = _get(kitchen, other)["steps"][0]["id"]
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "A note.", "kind": "notes", "step_id": foreign}])
    assert _notes(kitchen, dish)[0]["step_id"] is None


def test_a_step_mention_becomes_a_reference(dish, kitchen):
    d = _get(kitchen, dish)
    sid = d["steps"][2]["id"]
    _save(kitchen, dish, d, notes=[{"text": "Then proceed with step 3.", "kind": "notes",
                                    "refs": [{"ref_index": 0, "step_id": sid}]}])
    got = _get(kitchen, dish)["notes"][0]
    assert got["refs"][0]["match_text"] == "step 3"
    assert got["refs"][0]["step_id"] == sid
    assert got["refs"][0]["step_no"] == 3


def test_a_reference_follows_its_step_when_the_steps_move(dish, kitchen):
    """⚠️ THE WHOLE REASON IT IS A REFERENCE RATHER THAN A FROZEN NUMBER. Deleting a step ahead of
    the target renumbers the page, and the sentence has to keep meaning the same step."""
    d = _get(kitchen, dish)
    sid = d["steps"][2]["id"]
    _save(kitchen, dish, d, notes=[{"text": "Then proceed with step 3.", "kind": "notes",
                                    "refs": [{"ref_index": 0, "step_id": sid}]}])
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, steps=[{"id": d["steps"][1]["id"], "text": d["steps"][1]["text"]},
                                   {"id": sid, "text": d["steps"][2]["text"]}],
          notes=[{"text": "Then proceed with step 3.", "kind": "notes"}])
    got = _get(kitchen, dish)["notes"][0]
    assert got["refs"][0]["step_id"] == sid, "the reference must survive the save"
    assert got["refs"][0]["step_no"] == 2, "and must print the step's NEW number"


def test_deleting_the_words_drops_the_reference(dish, kitchen):
    d = _get(kitchen, dish)
    sid = d["steps"][2]["id"]
    _save(kitchen, dish, d, notes=[{"text": "Then proceed with step 3.", "kind": "notes",
                                    "refs": [{"ref_index": 0, "step_id": sid}]}])
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "Then carry on.", "kind": "notes"}])
    assert _get(kitchen, dish)["notes"][0].get("refs") == []


def test_inserting_words_before_a_mention_keeps_its_reference(dish, kitchen):
    """Keyed on the mention's ORDINAL, not on a character offset, which is what makes this hold."""
    d = _get(kitchen, dish)
    sid = d["steps"][2]["id"]
    _save(kitchen, dish, d, notes=[{"text": "Proceed with step 3.", "kind": "notes",
                                    "refs": [{"ref_index": 0, "step_id": sid}]}])
    d = _get(kitchen, dish)
    _save(kitchen, dish, d, notes=[{"text": "If it has risen enough, proceed with step 3.",
                                    "kind": "notes"}])
    assert _get(kitchen, dish)["notes"][0]["refs"][0]["step_id"] == sid
