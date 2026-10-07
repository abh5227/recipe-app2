"""A recipe created in the app records the words it was born with.

⚠️ A NOTE IS A PLAYGROUND ONLY IF THERE IS A WAY BACK. Andy's ruling is that editing a note costs
the recipe nothing: no annotation entry, no mark, no place in the byte-equal set. Both halves need
the notes OUT of recipe_snapshots.content, so the baseline is NOT the record of what the author
wrote. recipe_notes_original is, and it was written by exactly two things: the corpus move
(scripts/applied/notes_to_rows.py) and the importer. A recipe typed into the app got the playground
without the way back, and migration 063 removed the last incidental copy when it dropped
recipes.notes.

⚠️ MEASURED ON LIVE BEFORE ANY OF THIS, READ ONLY: 300 recipes, 95 carrying note rows, 95 carrying
originals. Nothing needs a backfill, which is the whole reason this could be closed as a rule
rather than as a repair.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from harness import make_kitchen                                                # noqa: E402
# ⚠️ THE SAVE PAYLOAD IS BUILT BY THE SAME HELPER EDIT MODE'S OWN TESTS USE, not written out here.
#    A PUT needs the whole recipe, and a hand-built one drifts from what the client actually sends.
from test_edit_mode_notes import _draft                                         # noqa: E402


@pytest.fixture
def kitchen(tmp_path):
    return make_kitchen(tmp_path)


def _originals(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT position, kind, text FROM recipe_notes_original "
            "WHERE recipe_id = ? ORDER BY position", (rid,))]


def _notes(kitchen, rid):
    with kitchen.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT position, kind, text FROM recipe_notes "
            "WHERE recipe_id = ? ORDER BY position", (rid,))]


def _create(kitchen, **over):
    body = {"name": "Birth Test", "ingredients": [],
            "steps": ["Mix."], "notes": "Note: rest the dough.\n\nTip: salt late."}
    body.update(over)
    r = kitchen.client.post("/api/recipes", json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def test_a_created_recipe_records_its_notes_as_originals(kitchen):
    rid = _create(kitchen)
    notes, originals = _notes(kitchen, rid), _originals(kitchen, rid)
    assert len(notes) == 2, notes
    assert [(o["position"], o["kind"], o["text"]) for o in originals] == \
           [(n["position"], n["kind"], n["text"]) for n in notes]


def test_a_created_recipe_with_no_notes_records_nothing(kitchen):
    """⚠️ AN EMPTY RECORD IS NOT THE SAME AS NO RECORD, and a row with empty text would fail the
    table's own CHECK (length(trim(text)) > 0)."""
    rid = _create(kitchen, notes="")
    assert _notes(kitchen, rid) == []
    assert _originals(kitchen, rid) == []


def test_the_record_does_not_follow_a_later_edit(kitchen):
    """⚠️ THE POINT OF THE TABLE. An original that moved with the rows would be a derived copy of
    the rows, which is what recipes.notes was and what migration 063 dropped."""
    rid = _create(kitchen)
    body = _draft(kitchen.client, rid)
    body["notes"][0]["text"] = "Note: actually, do not rest it."
    r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200, r.get_json()
    assert _notes(kitchen, rid)[0]["text"] == "Note: actually, do not rest it."
    assert _originals(kitchen, rid)[0]["text"] == "Note: rest the dough.", \
        "the record of the author's words followed the edit"


def test_deleting_every_note_leaves_the_way_back(kitchen):
    rid = _create(kitchen)
    r = kitchen.client.put(f"/api/recipes/{rid}", json=_draft(kitchen.client, rid, notes=[]))
    assert r.status_code == 200, r.get_json()
    assert _notes(kitchen, rid) == []
    assert len(_originals(kitchen, rid)) == 2, "every note was deleted and nothing remembers them"


def test_a_copy_of_an_app_recipe_is_given_its_own_record(kitchen):
    """⚠️ copy_recipe HAD THIS RULE WRITTEN OUT A SECOND TIME, and it now calls the same function.
    recipe_notes_original is written once per recipe, so a copy has to be given one at birth or
    never get one."""
    rid = _create(kitchen)
    r = kitchen.client.post(f"/api/recipes/{rid}/copy")
    assert r.status_code == 201, r.get_json()
    new_id = r.get_json()["id"]
    assert [o["text"] for o in _originals(kitchen, new_id)] == \
           [o["text"] for o in _originals(kitchen, rid)]


def test_recording_twice_changes_nothing(kitchen):
    """It is called from two doors and must be safe to call again, or a second call would double
    every row and break UNIQUE (recipe_id, position)."""
    import app
    rid = _create(kitchen)
    before = _originals(kitchen, rid)
    with kitchen.session() as s:
        assert app.record_notes_original(s, rid) == 0
        s.commit()
    assert _originals(kitchen, rid) == before
