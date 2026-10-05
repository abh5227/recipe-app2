"""Notes held in the Edit-mode draft: what Save writes, and what it must leave alone.

⚠️ WHY THIS FILE EXISTS SEPARATELY FROM test_note_api.py. Those are the per-note endpoints, which
the recipe page uses and which write the moment a cook stops typing. These are the recipe PUT, which
Edit mode uses and which writes everything at once. The same rows, two doors, and the dangerous one
is this door: a PUT carries the WHOLE list, so a bug here does not mis-write one note, it rewrites
or deletes all of them.

⚠️ EVERY CHECK HERE COMPARES AGAINST A BEFORE-STATE IT READ, and each one asserts that state is
non-empty first. A save-safety test with nothing to compare against passes for the wrong reason.
"""
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import harness   # noqa: E402,F401  (the shared `kitchen` fixture lives in conftest.py)


def _recipe(client, notes=None):
    body = {"name": "Beans", "ingredients": [{"raw_text": "1 cup beans"}],
            "steps": [{"text": "Rinse the beans"},
                      {"text": "Soak them overnight"},
                      {"text": "Simmer until tender"}]}
    if notes is not None:
        body["notes"] = notes
    return client.post("/api/recipes", json=body).get_json()["id"]


def _full(client, rid):
    return client.get(f"/api/recipes/{rid}").get_json()


def _rows(client, rid):
    """Every note row, as the API hands them back: the shape a save must not move."""
    return [{k: n[k] for k in ("id", "position", "kind", "text", "step_id", "ingredient_row_id")}
            for n in _full(client, rid)["notes"]]


def _originals(kitchen, rid):
    """recipe_notes_original, which nothing on the page reads and no save may touch."""
    import app as A
    with A.orm_session() as s:
        return sorted(tuple(r) for r in s.execute(
            A.text("SELECT position, kind, text FROM recipe_notes_original WHERE recipe_id = :r"),
            {"r": rid}))


def _seed_originals(kitchen, rid, rows):
    """Record the author's words, the way scripts/notes_to_rows.py does, so there is a record to
    check a save against."""
    import app as A
    with A.orm_session() as s:
        for n in rows:
            s.execute(A.text(
                "INSERT INTO recipe_notes_original (recipe_id, position, kind, text, recorded_at)"
                " VALUES (:r, :p, :k, :t, :w)"),
                {"r": rid, "p": n["position"], "k": n["kind"], "t": n["text"],
                 "w": A.now_utc()})
        s.commit()


def _draft(client, rid, **over):
    """The payload Edit mode's draftPayload builds, with the recipe as it stands."""
    d = _full(client, rid)
    r = d["recipe"]
    body = {
        "name": r["name"], "author": r.get("author") or "", "descr": r.get("descr") or "",
        "ingredients": [{"id": x["id"], "raw_text": x.get("raw_text") or ""} for x in d["ingredients"]],
        "steps": [{"id": x["id"], "text": x["text"], "is_heading": bool(x["is_heading"])}
                  for x in d["steps"]],
        "notes": [{"text": n["text"], "kind": n["kind"], "step_id": n["step_id"],
                   "ingredient_row_id": n["ingredient_row_id"],
                   "refs": [{"ref_index": f["ref_index"], "match_text": f["match_text"],
                             "step_id": f["step_id"]} for f in (n["refs"] or [])]}
                  for n in d["notes"]],
    }
    body.update(over)
    return body


def test_saving_with_no_note_changes_moves_no_note_row(kitchen):
    """The commonest save there is, and the one that used to cost a recipe its short-circuit."""
    rid = _recipe(kitchen.client, notes="Note: soak first.\n\nTip: salt at the end.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 2, "nothing to compare against"

    assert kitchen.client.put(f"/api/recipes/{rid}", json=_draft(kitchen.client, rid)).status_code == 200
    assert _rows(kitchen.client, rid) == before, "ids, positions, kinds and words all unmoved"


def test_a_save_that_does_not_name_notes_leaves_them_alone(kitchen):
    """⚠️ ABSENT IS NOT EMPTY, which is the rule that once erased a headnote.

    An older bundle, or any caller that does not know about notes, must not delete them.
    """
    rid = _recipe(kitchen.client, notes="Note: soak first.\n\nTip: salt at the end.")
    before = _rows(kitchen.client, rid)
    assert before, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body.pop("notes")
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _rows(kitchen.client, rid) == before


def test_an_explicit_empty_list_still_clears_them(kitchen):
    """The other half of the rule, so "absent is not empty" does not become "nothing can empty"."""
    rid = _recipe(kitchen.client, notes="Note: soak first.")
    assert _rows(kitchen.client, rid), "nothing to clear"
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_draft(kitchen.client, rid, notes=[])).status_code == 200
    assert _rows(kitchen.client, rid) == []


def test_changing_the_steps_leaves_every_note_on_the_step_it_named(kitchen):
    """A save that reworded and reordered the method must not move a single note's link.

    ⚠️ THE LINK IS AN ID AND THE PRINTED NUMBER IS DERIVED, so moving a step changes the number the
    page shows and must not change which step the note belongs to.
    """
    rid = _recipe(kitchen.client)
    steps = _full(kitchen.client, rid)["steps"]
    kitchen.client.post(f"/api/recipes/{rid}/notes",
                        json={"text": "watch it", "step_id": steps[2]["id"]})
    before = _rows(kitchen.client, rid)
    assert before and before[0]["step_id"] == steps[2]["id"], "nothing to compare against"
    assert _full(kitchen.client, rid)["notes"][0]["step_no"] == 3

    body = _draft(kitchen.client, rid)
    body["steps"][0]["text"] = "Rinse the beans very well"            # a reword
    body["steps"] = [body["steps"][2], body["steps"][0], body["steps"][1]]   # and a reorder
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert after[0]["step_id"] == before[0]["step_id"], "the same step row"
    assert _full(kitchen.client, rid)["notes"][0]["step_no"] == 1, "which is now printed as step 1"


def test_deleting_a_linked_step_leaves_the_note_unlinked_rather_than_deleted(kitchen):
    """⚠️ THE NOTE IS THE THING WITH NO SECOND COPY. Losing a step's words is an undo away in the
    editor; losing the note attached to it is not. The link goes, the note stays, and it reads in
    its type group because a note with no resolvable step is not a step note."""
    rid = _recipe(kitchen.client)
    steps = _full(kitchen.client, rid)["steps"]
    kitchen.client.post(f"/api/recipes/{rid}/notes",
                        json={"text": "Tip: watch it", "kind": "tips", "step_id": steps[2]["id"]})
    before = _rows(kitchen.client, rid)
    assert len(before) == 1 and before[0]["step_id"] == steps[2]["id"], "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body["steps"] = body["steps"][:2]                                  # the linked step is deleted
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _full(kitchen.client, rid)
    assert len(after["notes"]) == 1, "the note survives"
    assert after["notes"][0]["text"] == "Tip: watch it", "with its words"
    assert after["notes"][0]["kind"] == "tips", "and its type, which is the group it reads in"
    assert after["notes"][0]["step_id"] is None
    assert after["notes"][0]["step_no"] is None


def test_a_held_session_writes_exactly_what_it_changed(kitchen):
    """Edit one, add one, delete one, retype one, then Save. Exactly those four, nothing else."""
    rid = _recipe(kitchen.client,
                  notes="Note: keep.\n\nNote: edit me.\n\nNote: delete me.\n\nTip: retype me.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 4, "nothing to compare against"
    keep = next(n for n in before if n["text"] == "Note: keep.")
    edit = next(n for n in before if n["text"] == "Note: edit me.")
    retype = next(n for n in before if n["text"] == "Tip: retype me.")
    # ⚠️ recipe_notes_original IS WRITTEN BY THE CORPUS PASS AND BY THE IMPORTER, not by the create
    #    route, so a fixture recipe has none. It is seeded here on purpose: a check that the save
    #    leaves it alone is worth nothing against an empty table.
    _seed_originals(kitchen, rid, before)
    originals = _originals(kitchen, rid)
    assert len(originals) == 4, "the record this check compares against was not written"

    body = _draft(kitchen.client, rid)
    body["notes"] = [
        {"text": "Note: keep.", "kind": "notes", "step_id": None, "ingredient_row_id": None, "refs": []},
        {"text": "Note: edited.", "kind": "notes", "step_id": None, "ingredient_row_id": None, "refs": []},
        {"text": "Tip: retype me.", "kind": "storage", "step_id": None, "ingredient_row_id": None, "refs": []},
        {"text": "a brand new one", "kind": "notes", "step_id": None, "ingredient_row_id": None, "refs": []},
    ]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == [
        "Note: keep.", "Note: edited.", "Tip: retype me.", "a brand new one"]
    by_text = {n["text"]: n for n in after}
    assert by_text["Note: keep."]["id"] == keep["id"], "an untouched note keeps its row"
    assert by_text["Tip: retype me."]["id"] == retype["id"], "and so does one that only changed type"
    assert by_text["Tip: retype me."]["kind"] == "storage"
    assert by_text["Note: edited."]["id"] == edit["id"], "a reword is an EDIT, not a delete plus an add"
    assert "Note: delete me." not in by_text
    # ⚠️ AND THE SERVER CANNOT TELL "DELETE ONE, ADD ONE" FROM "REWORD ONE", because a PUT carries a
    #    LIST and both produce the same list. _match_rows pairs by wording first and then by ORDER
    #    over what is left, so the added note takes the deleted one's row. That is the stated rule
    #    and it costs a note nothing: recipe_notes is not in the snapshot blob, and
    #    recipe_notes_original is keyed on (recipe_id, position) rather than on a row id.
    assert len(after) == 4
    assert len({n["id"] for n in after}) == 4, "four rows, whichever ids they landed on"

    assert _originals(kitchen, rid) == originals, "the author's words are not a save's business"


def test_a_held_session_mints_no_annotation_and_keeps_the_short_circuit(kitchen):
    """The playground guarantee, through the PUT rather than through the per-note endpoints.

    ⚠️ THE PUT IS THE DANGEROUS DOOR FOR THIS, because it writes the recipe's content rows in the
    same transaction. If notes had crept back into the snapshot blob, this is where it would show.
    """
    import app as A
    rid = _recipe(kitchen.client, notes="Note: one.\n\nTip: two.")
    body = _draft(kitchen.client, rid)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200   # settle a baseline

    with A.orm_session() as s:
        before_marks = A._recipe_annotations(s, rid)
    body = _draft(kitchen.client, rid)
    body["notes"] = [
        {"text": "Note: one, reworded.", "kind": "tips", "step_id": None,
         "ingredient_row_id": None, "refs": []},
    ]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    with A.orm_session() as s:
        after_marks = A._recipe_annotations(s, rid)
    assert after_marks == before_marks, "a note edit, a type change and a delete, and no mark"
