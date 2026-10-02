"""Copying a recipe carries everything the recipe is made of, with every pointer remapped.

⚠️ THREE OF THESE WERE REAL AND MEASURED BEFORE THE FIX. The copy route ran two INSERT…SELECT
statements, for recipe_ingredients and recipe_steps, and that was all. It predates waits (migration
049), heading levels (059) and notes-as-rows (060), and nothing tested it. Measured on a throwaway
kitchen: a copy of a recipe with one wait and one storage row came back with none of either, and a
level-2 heading came back as level 1.

⚠️ AND A POINTER THAT IS COPIED RATHER THAN REMAPPED IS WORSE THAN A MISSING ONE. A wait or a note
naming a step id names a row of the ORIGINAL recipe, so the copy's links would move whenever the
original was edited, and deleting the original would null them. The remap is what makes a copy a
separate recipe rather than a second view of the first.
"""
import pytest

import app
import harness  # noqa: F401


@pytest.fixture
def full(kitchen):
    """A recipe carrying one of everything: a heading at level 2, a wait pointing at a step, a
    storage row, and two notes, one of which points at a step and at an ingredient line."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Everything", "ingredients": [{"qty": "1", "text": "flour"}],
        "steps": ["Mix.", "Rest."]}).get_json()["id"]
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    step_ids = [s["id"] for s in d["steps"]]
    ing_id = d["ingredients"][0]["id"]
    kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Everything",
        "ingredients": [{"id": ing_id, "quantity": "1", "unit": "", "text": "flour"}],
        "steps": [{"id": s, "text": t} for s, t in zip(step_ids, ("Mix.", "Rest."))],
        "waits": [{"kind": "resting", "label": "2 hr", "step_id": step_ids[1]}],
        "storage": [{"label": "3 days", "where_kept": "fridge"}],
        "notes": [
            {"text": "Keep going at step 2.", "kind": "tips", "step_id": step_ids[1],
             "ingredient_row_id": ing_id},
            {"text": "A plain note.", "kind": "notes"},
        ]})
    with kitchen.conn() as c:
        c.execute("UPDATE recipe_steps SET is_heading=1, heading_level=2 WHERE id=?", (step_ids[0],))
        c.commit()
    return rid


def _rows(kitchen, table, rid):
    with kitchen.conn() as c:
        c.row_factory = __import__("sqlite3").Row
        return [dict(r) for r in c.execute(
            f"SELECT * FROM {table} WHERE recipe_id=? ORDER BY position", (rid,))]


def _copy(kitchen, rid):
    return kitchen.client.post(f"/api/recipes/{rid}/copy").get_json()["id"]


def test_a_copy_keeps_its_waits(full, kitchen):
    new = _copy(kitchen, full)
    assert len(_rows(kitchen, "recipe_waits", new)) == len(_rows(kitchen, "recipe_waits", full)) == 1


def test_a_copy_keeps_its_storage(full, kitchen):
    new = _copy(kitchen, full)
    assert len(_rows(kitchen, "recipe_storage", new)) == len(_rows(kitchen, "recipe_storage", full)) == 1


def test_a_copy_keeps_its_heading_levels(full, kitchen):
    new = _copy(kitchen, full)
    levels = lambda r: [s["heading_level"] for s in _rows(kitchen, "recipe_steps", r) if s["is_heading"]]
    assert levels(new) == levels(full) == [2]


def test_a_copy_keeps_its_notes(full, kitchen):
    new = _copy(kitchen, full)
    src, cpy = _rows(kitchen, "recipe_notes", full), _rows(kitchen, "recipe_notes", new)
    assert len(cpy) == len(src) == 2
    assert [n["text"] for n in cpy] == [n["text"] for n in src]
    assert [n["kind"] for n in cpy] == [n["kind"] for n in src] == ["tips", "notes"]


def test_a_copys_wait_points_at_the_copys_own_step(full, kitchen):
    new = _copy(kitchen, full)
    w = _rows(kitchen, "recipe_waits", new)[0]
    own = {s["id"] for s in _rows(kitchen, "recipe_steps", new)}
    theirs = {s["id"] for s in _rows(kitchen, "recipe_steps", full)}
    assert w["step_id"] in own and w["step_id"] not in theirs


def test_a_copys_note_points_at_the_copys_own_step_and_ingredient(full, kitchen):
    new = _copy(kitchen, full)
    n = _rows(kitchen, "recipe_notes", new)[0]
    own_steps = {s["id"] for s in _rows(kitchen, "recipe_steps", new)}
    own_ings = {i["id"] for i in _rows(kitchen, "recipe_ingredients", new)}
    assert n["step_id"] in own_steps
    assert n["ingredient_row_id"] in own_ings
    src = _rows(kitchen, "recipe_notes", full)[0]
    assert n["step_id"] != src["step_id"] and n["ingredient_row_id"] != src["ingredient_row_id"]


def test_a_copys_step_reference_points_at_the_copys_own_step(full, kitchen):
    new = _copy(kitchen, full)
    with kitchen.conn() as c:
        note_id = c.execute("SELECT id FROM recipe_notes WHERE recipe_id=? ORDER BY position",
                            (new,)).fetchone()[0]
        refs = c.execute("SELECT ref_index, match_text, step_id FROM recipe_note_step_refs "
                         "WHERE note_id=? ORDER BY ref_index", (note_id,)).fetchall()
    own = {s["id"] for s in _rows(kitchen, "recipe_steps", new)}
    assert refs, "the note says 'step 2', so it should carry a reference"
    assert refs[0][1] == "step 2"
    assert refs[0][2] is None or refs[0][2] in own


def test_editing_the_original_does_not_move_the_copys_links(full, kitchen):
    """The whole point of remapping: the two recipes are separate afterwards."""
    new = _copy(kitchen, full)
    before = _rows(kitchen, "recipe_notes", new)[0]["step_id"]
    d = kitchen.client.get(f"/api/recipes/{full}").get_json()
    kitchen.client.put(f"/api/recipes/{full}", json={
        "name": "Everything", "ingredients": [], "steps": [], "waits": [], "storage": [],
        "notes": []})
    assert _rows(kitchen, "recipe_notes", new)[0]["step_id"] == before


def test_the_copy_is_byte_equal_to_its_own_baseline(full, kitchen):
    """A fresh copy has never been edited, so it must start in the short-circuit set."""
    new = _copy(kitchen, full)
    with app.orm_session() as s:
        assert app._recipe_annotations(s, new) == []
