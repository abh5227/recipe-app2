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
    check a save against.

    ⚠️ IT REPLACES RATHER THAN APPENDS. The create route records originals at birth now, so the
    fixture recipe already has a row at every position and the table carries
    UNIQUE (recipe_id, position). What this helper is for is pinning the EXACT four rows the test
    names, so it clears first and states what it wants."""
    import app as A
    with A.orm_session() as s:
        s.execute(A.text("DELETE FROM recipe_notes_original WHERE recipe_id = :r"), {"r": rid})
        for n in rows:
            s.execute(A.text(
                "INSERT INTO recipe_notes_original (recipe_id, position, kind, text, recorded_at)"
                " VALUES (:r, :p, :k, :t, :w)"),
                {"r": rid, "p": n["position"], "k": n["kind"], "t": n["text"],
                 "w": A.now_utc()})
        s.commit()


def _step_payload(x, heading=None):
    """One step, in the shape static/save-payload.js::stepToPayload actually sends.

    ⚠️ A HEADING GOES BACK AS {id, heading, level}, NOT AS {id, text, is_heading}. This file built
    the second shape, which app.py::_step_parts reads as an ordinary step, so every test here that
    meant to convert a step to a heading silently did not and asserted against a method that had
    not changed. Mirroring the real builder is the only way the fixture cannot drift from it.
    """
    want = bool(x["is_heading"]) if heading is None else heading
    if want:
        return {"id": x["id"], "heading": x["text"], "level": x.get("heading_level") or 1}
    return {"id": x["id"], "text": x["text"]}


def _as_heading(body, step_id, on=True):
    """Flip one step of a draft payload to (or from) a heading, in the wire shape."""
    for i, st in enumerate(body["steps"]):
        if st["id"] == step_id:
            body["steps"][i] = _step_payload(
                {"id": step_id, "text": st.get("text") or st.get("heading") or "",
                 "is_heading": on}, heading=on)
    return body


def _byte_equal(rid):
    """Is this recipe still byte-equal to its stored baseline, which is the short-circuit set?

    ⚠️ COMPARING ANNOTATIONS ALONE PROVED NOTHING ON A FRESH FIXTURE, because both sides were []
    and [] == [] whatever the save did. _recipe_annotations returns [] for a recipe that is byte
    equal AND for one that merely has no reportable difference, so the bytes have to be read.
    """
    import app as A
    with A.orm_session() as s:
        stored = s.execute(A.text(
            "SELECT content FROM recipe_snapshots WHERE recipe_id = :r AND reason = 'original'"),
            {"r": rid}).scalar()
        assert stored, "no baseline was recorded, so there is nothing to compare"
        return A.serialize_recipe_content(s, rid) == stored


def test_the_byte_equal_check_can_fail(kitchen):
    """⚠️ THE MUTATION PROOF. A gate that cannot fail is not a gate, and the per-note endpoints have
    one of these already. A real STEP edit must take the recipe out of the set, or _byte_equal is
    answering True for the wrong reason and every check above it is worthless."""
    rid = _recipe(kitchen.client, notes="Note: one.")
    assert kitchen.client.put(f"/api/recipes/{rid}",
                              json=_draft(kitchen.client, rid)).status_code == 200
    assert _byte_equal(rid), "the fixture did not start byte-equal, so nothing can be shown"

    body = _draft(kitchen.client, rid)
    body["steps"][0] = {"id": body["steps"][0]["id"], "text": "Rinse the beans very well indeed"}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert not _byte_equal(rid), "a real step edit left the recipe byte-equal, so the check is blind"
    import app as A
    with A.orm_session() as s:
        assert A._recipe_annotations(s, rid), "and it mints a mark, which a note never does"


def _draft(client, rid, **over):
    """The payload Edit mode's draftPayload builds, with the recipe as it stands."""
    d = _full(client, rid)
    r = d["recipe"]
    body = {
        "name": r["name"], "author": r.get("author") or "", "descr": r.get("descr") or "",
        "ingredients": [{"id": x["id"], "raw_text": x.get("raw_text") or ""} for x in d["ingredients"]],
        "steps": [_step_payload(x) for x in d["steps"]],
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
    # ⚠️ SEEDED ON PURPOSE: a check that the save leaves this table alone is worth nothing against
    #    an empty one. The create route records originals now (app.record_notes_original), so this
    #    fixture would have them anyway, and seeding keeps the four rows this test names rather than
    #    whatever the fixture happened to be built with.
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
    assert _byte_equal(rid), "and the recipe is still byte-equal to its baseline"


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
    assert _byte_equal(rid), "a drag does not cost the recipe its place in the set either"


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


# ---------------------------------------------------------------------------------------------
# One rule, both write doors. ⚠️ THE ROUND SHIPPED A SECOND NOTE WRITE PATH, and the recipe PUT and
# the per-note endpoints each restated the step-link rule, the reference rule and the kind rule.
# Three of the four restatements gave different answers, measured. _note_step_target and
# _note_ref_rows are the one copy now, and every case below is one of the measured divergences.
# ---------------------------------------------------------------------------------------------

def _steps(client, rid):
    return _full(client, rid)["steps"]


def test_absent_keys_on_an_id_matched_note_mean_keep_not_clear(kitchen):
    """⚠️ ABSENT IS NOT EMPTY, ONE LAYER DOWN. The rule is enforced at the `notes` key already. A
    PUT naming a row by id and sending only its text cleared the cook's chosen type AND their step
    link, answered 200, and said nothing."""
    rid = _recipe(kitchen.client, notes="Tip: salt at the end.")
    steps = _steps(kitchen.client, rid)
    first = next(s for s in steps if not s["is_heading"])
    before = _rows(kitchen.client, rid)
    assert len(before) == 1, "nothing to compare against"

    body = _draft(kitchen.client, rid)
    body["notes"] = [{"id": before[0]["id"], "text": before[0]["text"], "kind": "storage",
                      "step_id": first["id"], "ingredient_row_id": None, "refs": []}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    linked = _rows(kitchen.client, rid)[0]
    assert (linked["kind"], linked["step_id"]) == ("storage", first["id"]), "set up the state first"

    # now a save that names the row and sends only its words
    body = _draft(kitchen.client, rid)
    body["notes"] = [{"id": linked["id"], "text": linked["text"]}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    after = _rows(kitchen.client, rid)[0]
    assert after["kind"] == "storage", "an absent kind did not clear the cook's choice"
    assert after["step_id"] == first["id"], "and an absent step_id did not clear the link"
    assert after["id"] == linked["id"]


def test_the_old_string_shape_does_not_wipe_the_kinds_and_links(kitchen):
    """The documented deploy-window path. write_notes' docstring calls the bare string safe in both
    directions, and it was not: nothing older than migration 060 sends a kind or a step link, so one
    save from it cleared every one on the recipe."""
    rid = _recipe(kitchen.client, notes="Tip: one.\n\nStorage: two.")
    steps = _steps(kitchen.client, rid)
    first = next(s for s in steps if not s["is_heading"])
    before = _rows(kitchen.client, rid)
    assert len(before) == 2, "nothing to compare against"
    body = _draft(kitchen.client, rid)
    body["notes"] = [{"id": n["id"], "text": n["text"], "kind": n["kind"],
                      "step_id": first["id"] if n is before[0] else None,
                      "ingredient_row_id": None, "refs": []} for n in before]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    staged = _rows(kitchen.client, rid)
    assert staged[0]["step_id"] == first["id"] and staged[0]["kind"] == "tips", "set the state up"

    # the previous client's single textarea, split by the same rule the corpus move used
    body = _draft(kitchen.client, rid)
    body["notes"] = "Tip: one.\n\nStorage: two."
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    after = _rows(kitchen.client, rid)
    assert [n["kind"] for n in after] == [n["kind"] for n in staged], "the kinds survived"
    assert [n["step_id"] for n in after] == [n["step_id"] for n in staged], "and the links did"


def test_a_step_named_in_a_note_s_words_auto_links_through_the_PUT_too(kitchen):
    """⚠️ THE SAME WORDS THROUGH THE TWO DOORS GAVE TWO ANSWERS. Typed in reading view, "step 2"
    linked and put a marker on that step. Typed in Edit mode, it stayed plain text."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    assert len(steps) >= 2, "nothing to link to"

    body = _draft(kitchen.client, rid)
    # exactly what note-draft.js::notesPayload builds for a note typed this session
    body["notes"] = [{"text": "then do what step 2 says", "kind": "notes", "step_id": None,
                      "ingredient_row_id": None,
                      "refs": [{"ref_index": 0, "match_text": "step 2", "step_id": None}]}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    note = _full(kitchen.client, rid)["notes"][0]
    assert note["refs"], "the mention was not even recorded"
    assert note["refs"][0]["step_id"] == steps[1]["id"], "the words name step 2, so they link to it"
    assert note["refs"][0]["step_no"] == 2


def test_an_unlinked_reference_stays_unlinked_through_a_later_save(kitchen):
    """The other half of the auto-link: a stored NULL is an answer and it stops the search, which is
    what lets a deliberate unlink survive. Otherwise the auto-link would undo it on the next save."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    r = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "then do what step 2 says"})
    assert r.status_code == 201, r.get_json()
    note = _full(kitchen.client, rid)["notes"][0]
    assert note["refs"][0]["step_id"] == steps[1]["id"], "nothing to unlink"
    assert kitchen.client.patch(
        f"/api/recipes/{rid}/notes/{note['id']}/refs/0", json={"step_id": None}).status_code == 200
    assert _full(kitchen.client, rid)["notes"][0]["refs"][0]["step_id"] is None

    body = _draft(kitchen.client, rid)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _full(kitchen.client, rid)["notes"][0]["refs"][0]["step_id"] is None, \
        "the save re-linked a reference the cook had unlinked"


def test_a_reference_to_a_step_that_became_a_heading_survives_a_later_text_edit(kitchen):
    """⚠️ MEASURED DATA LOSS, AND THE ID LIVES NOWHERE ELSE. write_notes kept such a reference and
    _rescan_note_refs destroyed it, so editing one word of the note in reading view made the
    conversion irreversible. Both read _note_step_target now."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    target = steps[1]["id"]
    assert kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "then do what step 2 says"}).status_code == 201
    note = _full(kitchen.client, rid)["notes"][0]
    assert note["refs"][0]["step_id"] == target, "nothing to preserve"

    # turn that step into a heading through the PUT, which is where the conversion lives
    body = _as_heading(_draft(kitchen.client, rid), target)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert next(st for st in _steps(kitchen.client, rid)
                if st["id"] == target)["is_heading"], "the conversion did not land"
    held = _full(kitchen.client, rid)["notes"][0]
    assert held["refs"][0]["step_id"] == target, "the PUT dropped it"
    assert held["refs"][0]["step_no"] is None, "and it must not print a number"

    # then change one word of the note through the OTHER door
    assert kitchen.client.patch(f"/api/recipes/{rid}/notes/{note['id']}",
                               json={"text": "then do just what step 2 says"}).status_code == 200
    after = _full(kitchen.client, rid)["notes"][0]
    assert after["refs"][0]["step_id"] == target, "a text edit destroyed the reference"

    # and converting the heading back brings the link home, which is the whole point
    body = _as_heading(_draft(kitchen.client, rid), target, on=False)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _full(kitchen.client, rid)["notes"][0]["refs"][0]["step_no"] == 2


def test_a_reference_to_a_step_that_is_GONE_is_dropped(kitchen):
    """The other side of the same rule: nothing can bring a deleted step's id back."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    assert kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "then do what step 2 says"}).status_code == 201
    assert _full(kitchen.client, rid)["notes"][0]["refs"][0]["step_id"] == steps[1]["id"]

    body = _draft(kitchen.client, rid)
    body["steps"] = [st for st in body["steps"] if st["id"] != steps[1]["id"]]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _full(kitchen.client, rid)["notes"][0]["refs"][0]["step_id"] is None


def test_the_PUT_will_not_newly_link_a_note_to_a_heading(kitchen):
    """The per-note door answers 400 for this and the PUT stored it, so the same value meant two
    things depending on which door it came through."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    head = steps[1]["id"]
    body = _as_heading(_draft(kitchen.client, rid), head)
    body["notes"] = [{"text": "stuck on a heading", "kind": "notes", "step_id": head,
                      "ingredient_row_id": None, "refs": []}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _rows(kitchen.client, rid)[0]["step_id"] is None, "a new link to a heading was stored"
    # and the per-note door still refuses it outright
    r = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "also stuck", "step_id": head})
    assert r.status_code == 400
    assert "heading" in r.get_json()["error"]


def test_a_note_already_linked_to_a_step_keeps_the_link_when_that_step_becomes_a_heading(kitchen):
    """And the reversibility half, for the note's OWN link rather than for a reference."""
    rid = _recipe(kitchen.client)
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    target = steps[1]["id"]
    assert kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "about that step", "step_id": target}).status_code == 201
    body = _as_heading(_draft(kitchen.client, rid), target)
    body["notes"] = _notes_payload(_full(kitchen.client, rid))
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    kept = _rows(kitchen.client, rid)[0]
    assert kept["step_id"] == target, "the conversion has to be reversible"
    assert _full(kitchen.client, rid)["notes"][0]["step_no"] is None, "and print no number"


# ---------------------------------------------------------------------------------------------
# A write path refuses what it cannot read. ⚠️ resolve_recipe_payload checked the notes CONTAINER
# and each ENTRY and stopped there, so every scalar inside a note reached write_notes untyped.
# ---------------------------------------------------------------------------------------------

def test_a_malformed_field_inside_a_note_is_refused_rather_than_a_500(kitchen):
    rid = _recipe(kitchen.client, notes="Note: keep me.")
    before = _rows(kitchen.client, rid)
    assert before, "nothing to protect"
    bad = [
        ({"text": 5}, "text"),
        ({"text": "x", "step_id": [1]}, "step_id"),
        ({"text": "x", "ingredient_row_id": "7"}, "ingredient_row_id"),
        ({"text": "x", "kind": ["notes"]}, "kind"),
        ({"text": "x", "refs": 7}, "refs"),
        ({"text": "x", "refs": [3]}, "refs"),
        ({"text": "x", "refs": [{"ref_index": "0", "match_text": "step 2"}]}, "ref_index"),
        ({"text": "x", "refs": [{"ref_index": 0, "match_text": 9}]}, "words"),
        ({"text": "x", "id": True}, "id"),
        ({"text": "x", "step_id": True}, "step_id"),
        ({"text": "x", "position": 1.5}, "position"),
    ]
    for note, why in bad:
        body = _draft(kitchen.client, rid)
        body["notes"] = [note]
        r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
        assert r.status_code == 400, f"{note!r} answered {r.status_code}, not 400"
        assert why in r.get_json()["error"] or "kind" in r.get_json()["error"], \
            f"{note!r} -> {r.get_json()['error']!r}"
    assert _rows(kitchen.client, rid) == before, "a refused save wrote nothing"
    # ⚠️ AND A WELL-FORMED KIND THE TABLE DOES NOT LIST IS NOT REFUSED. recipe_notes.kind is a
    #    foreign key, so a stale client's unknown kind falls back to the default rather than failing
    #    an otherwise valid save. The per-note PATCH answers 400 for the same string, which is a
    #    disagreement between the two doors and a decision rather than a defect.
    body = _draft(kitchen.client, rid)
    body["notes"] = [{"text": "from a stale client", "kind": "nonsense"}]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _rows(kitchen.client, rid)[0]["kind"] == "notes"


def test_a_well_formed_note_payload_still_goes_through(kitchen):
    """The guard above must not refuse what the real client sends. Nothing to compare means nothing
    proved, so this asserts the shape notesPayload builds, field for field."""
    rid = _recipe(kitchen.client, notes="Note: one.")
    steps = [s for s in _steps(kitchen.client, rid) if not s["is_heading"]]
    stored = _rows(kitchen.client, rid)[0]
    body = _draft(kitchen.client, rid)
    body["notes"] = [
        {"id": stored["id"], "text": "then do what step 2 says", "kind": "tips",
         "step_id": steps[0]["id"], "ingredient_row_id": None,
         "refs": [{"ref_index": 0, "match_text": "step 2", "step_id": None}]},
        {"text": "a new one", "kind": "storage", "step_id": None,
         "ingredient_row_id": None, "refs": []},
    ]
    r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200, r.get_json()
    after = _rows(kitchen.client, rid)
    assert [n["kind"] for n in after] == ["tips", "storage"]
    assert after[0]["id"] == stored["id"]

