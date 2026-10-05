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


def _recipe(client, notes=None, name="Beans"):
    body = {"name": name, "ingredients": [{"raw_text": "1 cup beans"}],
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
        {"id": keep["id"], "text": "Note: keep.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"id": edit["id"], "text": "Note: edited.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"id": retype["id"], "text": "Tip: retype me.", "kind": "storage", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"text": "a brand new one", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
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
    # ⚠️ THE DELETED NOTE'S ROW IS GONE AND THE NEW ONE IS NEW. The payload names the row each
    #    note came from, so the server no longer guesses which of the two happened.
    deleted = next(n for n in before if n["text"] == "Note: delete me.")
    assert deleted["id"] not in {n["id"] for n in after}
    assert by_text["a brand new one"]["id"] not in {n["id"] for n in before}

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


# ---------------------------------------------------------------------------------------------
# Pairing by id. ⚠️ THE QUESTION IS "WHICH ROW IS THIS", AND ONLY THE CLIENT KNOWS THE ANSWER.
# Wording-then-order reads "delete A, add B" and "reword A" as the same list, so the added note
# took the deleted one's row. Edit mode holds the cook's own rows and now names them.
# ---------------------------------------------------------------------------------------------

def test_deleting_one_note_and_adding_another_in_one_save_is_a_delete_and_an_add(kitchen):
    rid = _recipe(kitchen.client, notes="Note: A, which goes.\n\nNote: C, which stays.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 2, "nothing to compare against"
    gone = next(n for n in before if n["text"].startswith("Note: A"))
    stays = next(n for n in before if n["text"].startswith("Note: C"))

    body = _draft(kitchen.client, rid)
    body["notes"] = [
        {"id": stays["id"], "text": "Note: C, which stays.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"text": "Note: B, which is new.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},        # no id, so it is new
    ]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == ["Note: C, which stays.", "Note: B, which is new."]
    assert gone["id"] not in {n["id"] for n in after}, "A's row is deleted, not reused"
    assert after[0]["id"] == stays["id"], "C is untouched"
    assert after[1]["id"] not in {n["id"] for n in before}, "B is a new row"


def test_rewording_a_note_keeps_its_row_and_its_id(kitchen):
    rid = _recipe(kitchen.client, notes="Note: C, before.\n\nNote: another one.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 2, "nothing to compare against"
    c = before[0]

    body = _draft(kitchen.client, rid)
    body["notes"][0]["text"] = "Note: C, completely rewritten."
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert len(after) == 2
    assert after[0]["id"] == c["id"], "a reword is an edit of the row that was sitting there"
    assert after[0]["text"] == "Note: C, completely rewritten."
    assert after[1]["id"] == before[1]["id"], "and its neighbor is untouched"


def test_a_payload_with_no_ids_at_all_still_falls_back_to_wording_then_order(kitchen):
    """The previous bundle sends a bare string and an older client sends a list with no ids. For
    those, wording-then-order is still the rule, and an unchanged save still moves no row."""
    rid = _recipe(kitchen.client, notes="Note: one.\n\nTip: two.")
    before = _rows(kitchen.client, rid)
    assert before, "nothing to compare against"

    assert kitchen.client.put(
        f"/api/recipes/{rid}", json=_draft(kitchen.client, rid, note_ids=False)).status_code == 200
    assert _rows(kitchen.client, rid) == before, "an id-less unchanged save moves nothing"

    # and the bare-string shape, which never had ids to send
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_draft(kitchen.client, rid,
                                          notes="Note: one.\n\nTip: two.")).status_code == 200
    assert _rows(kitchen.client, rid) == before


def test_an_id_this_recipe_does_not_own_is_treated_as_a_new_note(kitchen):
    """⚠️ THE POOL IS THIS RECIPE'S ROWS, so a payload cannot reach another recipe's notes by naming
    one. An id from elsewhere, a deleted id and a repeated id all land in the same safe place."""
    mine = _recipe(kitchen.client, notes="Note: mine.")
    theirs = _recipe(kitchen.client, notes="Note: theirs.", name="Someone Else's Lentils")
    their_row = _rows(kitchen.client, theirs)[0]
    my_row = _rows(kitchen.client, mine)[0]
    assert their_row["id"] != my_row["id"], "nothing to compare against"

    body = _draft(kitchen.client, mine)
    body["notes"] = [
        {"id": my_row["id"], "text": "Note: mine.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"id": their_row["id"], "text": "Note: borrowed.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"id": 999999, "text": "Note: nobody's.", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
    ]
    assert kitchen.client.put(f"/api/recipes/{mine}", json=body).status_code == 200

    after = _rows(kitchen.client, mine)
    assert [n["text"] for n in after] == ["Note: mine.", "Note: borrowed.", "Note: nobody's."]
    assert after[0]["id"] == my_row["id"]
    assert after[1]["id"] != their_row["id"], "the other recipe's row was not claimed"
    assert _rows(kitchen.client, theirs) == [their_row], "and it is still sitting where it was"


def test_one_id_is_claimed_once(kitchen):
    """A payload naming the same row twice gets one update and one new row, never two updates."""
    rid = _recipe(kitchen.client, notes="Note: one.")
    row = _rows(kitchen.client, rid)[0]
    body = _draft(kitchen.client, rid)
    body["notes"] = [
        {"id": row["id"], "text": "first", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
        {"id": row["id"], "text": "second", "kind": "notes", "step_id": None,
         "ingredient_row_id": None, "refs": []},
    ]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == ["first", "second"]
    assert after[0]["id"] == row["id"]
    assert after[1]["id"] != row["id"]


def test_a_note_keeps_its_step_reference_across_an_id_matched_save(kitchen):
    """⚠️ THE REFERENCE CARRY READS THE MATCHED ROW, so changing how rows are matched could have
    dropped a link on every save. It is keyed on (ref_index, match_text) either way."""
    rid = _recipe(kitchen.client)
    steps = _full(kitchen.client, rid)["steps"]
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "then do step 3 again"})
    n = _full(kitchen.client, rid)["notes"][0]
    assert n["refs"] and n["refs"][0]["step_id"] == steps[2]["id"], "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body["notes"][0]["text"] = "Rest it, then do step 3 again"      # a word added before the mention
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _full(kitchen.client, rid)["notes"][0]
    assert after["id"] == n["id"]
    assert after["refs"][0]["step_id"] == steps[2]["id"], "the link survived the reword"
    assert after["refs"][0]["step_no"] == 3


# ---------------------------------------------------------------------------------------------
# Reordering. ⚠️ THE ORDER IS THE DATA. noteSections prints a group in list order and write_notes
# assigns position from the order it is given, so a drag's whole effect is which position each
# EXISTING row ends up with. The row ids must survive it, or a reorder would be a delete and a
# re-add of every note on the recipe, and recipe_notes carries UNIQUE (recipe_id, position), which
# a reordered list collides with the moment two rows swap.
# ---------------------------------------------------------------------------------------------

def _notes_payload(d):
    """What static/note-draft.js::notesPayload sends: the row each note came from, NAMED."""
    return [{"id": n["id"], "text": n["text"], "kind": n["kind"], "step_id": n["step_id"],
             "ingredient_row_id": n["ingredient_row_id"],
             "refs": [{"ref_index": f["ref_index"], "match_text": f["match_text"],
                       "step_id": f["step_id"]} for f in (n["refs"] or [])]}
            for n in d["notes"]]


def test_reordering_notes_moves_the_positions_and_keeps_every_id(kitchen):
    rid = _recipe(kitchen.client, notes="Note: one.\n\nNote: two.\n\nNote: three.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 3, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    body["notes"] = [sent[1], sent[0], sent[2]]                 # drag note two above note one
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == ["Note: two.", "Note: one.", "Note: three."]
    assert [n["position"] for n in after] == [0, 1, 2]
    assert {n["id"] for n in after} == {n["id"] for n in before}, "a move is not a delete and an add"
    by_id = {n["id"]: n for n in after}
    for n in before:
        assert by_id[n["id"]]["text"] == n["text"], "a move changes no words"
        assert by_id[n["id"]]["kind"] == n["kind"]
        assert by_id[n["id"]]["step_id"] == n["step_id"]


def test_a_reversed_list_never_collides_on_UNIQUE_recipe_id_position(kitchen):
    """⚠️ THE CASE THE NEGATIVE-POSITION PASS IN _apply_rows EXISTS FOR. Writing a reordered list
    straight back collides the moment two rows swap, and a full reversal collides on every row."""
    rid = _recipe(kitchen.client,
                  notes="Note: a.\n\nNote: b.\n\nNote: c.\n\nNote: d.\n\nNote: e.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 5, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body["notes"] = list(reversed(_notes_payload(_full(kitchen.client, rid))))
    r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200, r.get_json()

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == [n["text"] for n in reversed(before)]
    assert [n["position"] for n in after] == [0, 1, 2, 3, 4], "positions are 0..n-1, with no gaps"
    assert {n["id"] for n in after} == {n["id"] for n in before}


def test_a_reorder_leaves_the_author_s_words_and_every_other_recipe_alone(kitchen):
    rid = _recipe(kitchen.client, notes="Note: one.\n\nNote: two.")
    other = _recipe(kitchen.client, notes="Note: elsewhere.", name="Brioche")
    before, other_before = _rows(kitchen.client, rid), _rows(kitchen.client, other)
    assert len(before) == 2 and other_before, "nothing to compare against"
    _seed_originals(kitchen, rid, before)
    originals = _originals(kitchen, rid)
    assert len(originals) == 2, "the record this check compares against was not written"

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    body["notes"] = [sent[1], sent[0]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    assert _originals(kitchen, rid) == originals, "a reorder is not a save's business either"
    assert _rows(kitchen.client, other) == other_before, "one recipe's drag touches one recipe"


def test_a_reorder_mints_no_annotation_and_keeps_the_short_circuit(kitchen):
    """A drag is a note change like any other, so it costs the recipe nothing."""
    import app as A
    rid = _recipe(kitchen.client, notes="Note: one.\n\nNote: two.")
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_draft(kitchen.client, rid)).status_code == 200  # settle a baseline
    with A.orm_session() as s:
        before_marks = A._recipe_annotations(s, rid)

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    body["notes"] = [sent[1], sent[0]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    with A.orm_session() as s:
        assert A._recipe_annotations(s, rid) == before_marks


def test_saving_the_same_order_back_moves_nothing_at_all(kitchen):
    """The no-change save, with the ids the client now sends. Byte-identical rows."""
    rid = _recipe(kitchen.client, notes="Note: one.\n\nTip: two.\n\nNote: three.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 3, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body["notes"] = _notes_payload(_full(kitchen.client, rid))
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _rows(kitchen.client, rid) == before


def test_a_note_added_beside_another_lands_where_the_payload_puts_it(kitchen):
    """"Add note above / below" is an insert into the list, and position follows the list order.

    ⚠️ THE NEW NOTE CARRIES NO id, which is what tells the server it is a new row rather than a
    rename of whichever row happens to sit at that position.
    """
    rid = _recipe(kitchen.client, notes="Note: one.\n\nTip: two.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 2, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    added = {"text": "added above the tip", "kind": sent[1]["kind"],
             "step_id": sent[1]["step_id"], "ingredient_row_id": None, "refs": []}
    body["notes"] = [sent[0], added, sent[1]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == ["Note: one.", "added above the tip", "Tip: two."]
    assert [n["position"] for n in after] == [0, 1, 2]
    assert after[1]["kind"] == before[1]["kind"], "it copied its neighbour's type"
    assert after[1]["id"] not in {n["id"] for n in before}, "and it is a new row"
    assert after[0]["id"] == before[0]["id"] and after[2]["id"] == before[1]["id"], \
        "the two it was inserted between keep their own rows"


def test_an_empty_added_note_is_dropped_by_the_save(kitchen):
    """"Add note below" opens an empty row, exactly as "+ add step" does. Saving without typing
    drops it again, which is the contract nonEmptySteps already has for a step."""
    rid = _recipe(kitchen.client, notes="Note: one.")
    before = _rows(kitchen.client, rid)
    assert before, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    body["notes"] = sent + [{"text": "", "kind": "notes", "step_id": None,
                             "ingredient_row_id": None, "refs": []}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _rows(kitchen.client, rid) == before


def test_deleting_a_note_from_the_menu_takes_its_row_and_renumbers_the_rest(kitchen):
    rid = _recipe(kitchen.client, notes="Note: one.\n\nNote: two.\n\nNote: three.")
    before = _rows(kitchen.client, rid)
    assert len(before) == 3, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    sent = _notes_payload(_full(kitchen.client, rid))
    body["notes"] = [sent[0], sent[2]]                       # the middle one deleted from its ⋯ menu
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200

    after = _rows(kitchen.client, rid)
    assert [n["text"] for n in after] == ["Note: one.", "Note: three."]
    assert [n["position"] for n in after] == [0, 1]
    assert before[1]["id"] not in {n["id"] for n in after}, "the deleted row is gone"
    assert [n["id"] for n in after] == [before[0]["id"], before[2]["id"]], "the survivors keep theirs"
