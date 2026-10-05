"""The per-note write path: the owner gate, in-place updates, and the playground guarantee.

⚠️ WHY THIS FILE EXISTS. The notes round proved that a note edit costs a recipe nothing by MEASURING
live before the code existed. These endpoints are a SECOND door into the same rows, so "it cannot
mint a mark" is now a property of five routes rather than of one save path. The guarantee is stated
here against the real serializer, and `test_the_no_marks_check_can_fail` proves the measurement is
capable of failing. A check with nothing to compare against passes for the wrong reason, and this
suite has been bitten by exactly that twice.
"""
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import harness                                                        # noqa: E402


def _recipe(client, name="Beans", steps=None, notes=None):
    """An owned app recipe with real steps, through the ordinary create route."""
    body = {"name": name, "ingredients": [{"raw_text": "1 cup beans"}],
            "steps": steps if steps is not None else [
                {"text": "Rinse the beans"},
                {"text": "Soak them overnight"},
                {"text": "Simmer until tender"}]}
    if notes is not None:
        body["notes"] = notes
    return client.post("/api/recipes", json=body).get_json()["id"]


def _notes_of(client, rid):
    # ⚠️ TOP LEVEL, NOT INSIDE `recipe`. The `recipe` key is the recipes-table row, where `notes` is
    #    the DERIVED string column; the rows the page reads are the top-level `notes` list.
    return client.get(f"/api/recipes/{rid}").get_json()["notes"]


def _steps_of(client, rid):
    return client.get(f"/api/recipes/{rid}").get_json()["steps"]


def _second_user_client():
    import app as A
    uid = harness.ensure_test_user(email="someone-else@test.invalid")
    c = A.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


# --- the owner gate ------------------------------------------------------------------------------

def test_a_non_owner_gets_403_from_every_note_endpoint(kitchen):
    """⚠️ STATED OVER THE ROUTES, NOT OVER A LIST SOMEBODY REMEMBERED.

    The brief's rule is "the server enforces it, not just the UI". A hidden button is not an access
    rule, so each route is asked directly, and the note survives untouched.
    """
    rid = _recipe(kitchen.client, "Mine Alone")
    note = kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "Mine"}).get_json()["note"]
    _uid, other = _second_user_client()
    calls = [
        ("post", f"/api/recipes/{rid}/notes", {"text": "theirs"}),
        ("patch", f"/api/recipes/{rid}/notes/{note['id']}", {"text": "theirs"}),
        ("patch", f"/api/recipes/{rid}/notes/{note['id']}", {"kind": "tips"}),
        ("patch", f"/api/recipes/{rid}/notes/{note['id']}", {"step_id": None}),
        # ⚠️ THE REFERENCE ROUTE WAS NOT ON THIS LIST, and the companion test below claimed a sixth
        #    route could not be added without covering it. The route already there was uncovered,
        #    so the claim was false about the routes that existed, not only about future ones.
        ("patch", f"/api/recipes/{rid}/notes/{note['id']}/refs/0", {"step_id": None}),
        ("delete", f"/api/recipes/{rid}/notes/{note['id']}", None),
    ]
    # ⚠️ EVERY WRITE ROUTE IN THE URL MAP IS REACHED BY AT LEAST ONE CALL ABOVE, checked here rather
    #    than asserted in prose. A path nobody calls is the shape this gap had.
    import app as A
    wanted = {str(r) for r in A.app.url_map.iter_rules()
              if "/notes" in str(r) and r.methods & {"POST", "PATCH", "DELETE", "PUT"}}
    assert wanted, "no note routes found, so nothing was gated"
    reached = set()
    for _verb, url, _b in calls:
        for rule in wanted:
            head = rule.split("<")[0]
            if url.startswith(head.replace("<rid>", rid)) or head.replace("<rid>", rid) in url:
                reached.add(rule)
    missing = {r for r in wanted if r not in reached}
    assert not missing, f"a note write route is reached by no call in this test: {sorted(missing)}"
    for verb, url, body in calls:
        resp = getattr(other, verb)(url, json=body) if body is not None else getattr(other, verb)(url)
        assert resp.status_code == 403, f"{verb.upper()} {url} answered {resp.status_code}"
        assert resp.get_json()["error"] == "not your recipe"
    rows = _notes_of(kitchen.client, rid)
    assert [r["text"] for r in rows] == ["Mine"], "a refused call changed the note"


def test_every_note_route_is_covered_by_the_gate_test(kitchen):
    """⚠️ THE LIST ABOVE IS CHECKED AGAINST THE URL MAP, so a sixth route cannot be added without
    either covering it or failing here. The gate test names paths; this names the rules."""
    import app as A
    # A path with two verbs is two rules (PATCH and DELETE on the note itself), so the SET of paths
    # is the question, not the list of rules.
    note_rules = sorted({
        str(r) for r in A.app.url_map.iter_rules()
        if "/notes" in str(r) and r.methods & {"POST", "PATCH", "DELETE", "PUT"}})
    assert note_rules == [
        "/api/recipes/<rid>/notes",
        "/api/recipes/<rid>/notes/<int:note_id>",
        "/api/recipes/<rid>/notes/<int:note_id>/refs/<int:ref_index>",
    ], note_rules


def test_a_logged_out_caller_gets_401_not_403(kitchen, kitchen_logged_out):
    """The fail-closed before_request gate answers first, so the two failures stay distinct."""
    rid = _recipe(kitchen.client)
    resp = kitchen_logged_out.client.post(f"/api/recipes/{rid}/notes", json={"text": "x"})
    assert resp.status_code == 401


def test_a_seed_recipe_refuses_by_tier_not_by_ownership(kitchen):
    """A seed row is owner-NULL, so the message has to be the tier one or it reads as a lie."""
    resp = kitchen.client.post("/api/recipes/gai-yang/notes", json={"text": "x"})
    assert resp.status_code == 403
    assert "seed.py" in resp.get_json()["error"]


def test_a_missing_recipe_is_404(kitchen):
    assert kitchen.client.post("/api/recipes/nope/notes", json={"text": "x"}).status_code == 404


# --- create, update, delete ----------------------------------------------------------------------

def test_create_appends_and_defaults_to_the_note_kind(kitchen):
    rid = _recipe(kitchen.client)
    for text in ("first", "second"):
        kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": text})
    rows = _notes_of(kitchen.client, rid)
    assert [r["text"] for r in rows] == ["first", "second"]
    assert [r["position"] for r in rows] == [0, 1]
    assert {r["kind"] for r in rows} == {"notes"}


def test_create_from_a_step_links_that_step(kitchen):
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[1]["id"]
    out = kitchen.client.post(f"/api/recipes/{rid}/notes",
                              json={"text": "Use warm water", "step_id": sid}).get_json()
    assert out["note"]["step_id"] == sid
    assert out["note"]["step_no"] == 2, "the number the page prints, not the position"


def test_a_note_will_not_attach_to_a_heading(kitchen):
    rid = _recipe(kitchen.client, steps=[{"heading": "For the beans"}, {"text": "Rinse them"}])
    head = [s for s in _steps_of(kitchen.client, rid) if s["is_heading"]][0]
    resp = kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "x", "step_id": head["id"]})
    assert resp.status_code == 400
    assert "heading" in resp.get_json()["error"]


def test_a_step_from_another_recipe_is_refused(kitchen):
    a = _recipe(kitchen.client, "Recipe A")
    b = _recipe(kitchen.client, "Recipe B")
    foreign = _steps_of(kitchen.client, b)[0]["id"]
    resp = kitchen.client.post(f"/api/recipes/{a}/notes",
                               json={"text": "x", "step_id": foreign})
    assert resp.status_code == 400


def test_an_empty_note_is_refused(kitchen):
    rid = _recipe(kitchen.client)
    for body in ({"text": "   "}, {"text": ""}, {"text": None}, {}):
        assert kitchen.client.post(f"/api/recipes/{rid}/notes", json=body).status_code == 400


def test_update_keeps_the_row_id_and_its_place(kitchen):
    """⚠️ IN PLACE BY ID. A note that came back with a new id on every edit would be a delete plus an
    insert, which is the defect that cost brioche-bread its place in the byte-equal set when waits
    were written that way."""
    rid = _recipe(kitchen.client)
    for t in ("one", "two", "three"):
        kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": t})
    before = _notes_of(kitchen.client, rid)
    mid = before[1]
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{mid['id']}", json={"text": "two, reworded"})
    after = _notes_of(kitchen.client, rid)
    assert [r["id"] for r in after] == [r["id"] for r in before]
    assert [r["text"] for r in after] == ["one", "two, reworded", "three"]


def test_update_changes_the_kind_without_touching_the_words(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "Keeps for 3 days"}).get_json()["note"]
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                               json={"kind": "storage"}).get_json()
    assert out["note"]["kind"] == "storage"
    assert out["note"]["text"] == "Keeps for 3 days"


def test_an_unknown_kind_is_refused(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "x"}).get_json()["note"]
    resp = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"kind": "nonsense"})
    assert resp.status_code == 400


def test_update_can_unlink_a_step(kitchen):
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[0]["id"]
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "x", "step_id": sid}).get_json()["note"]
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                               json={"step_id": None}).get_json()
    assert out["note"]["step_id"] is None


def test_update_with_nothing_to_change_is_refused(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "x"}).get_json()["note"]
    assert kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={}).status_code == 400


def test_a_move_renumbers_the_rest_and_keeps_every_id(kitchen):
    rid = _recipe(kitchen.client)
    for t in ("a", "b", "c"):
        kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": t})
    rows = _notes_of(kitchen.client, rid)
    ids = {r["text"]: r["id"] for r in rows}
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{ids['c']}", json={"position": 0})
    after = _notes_of(kitchen.client, rid)
    assert [r["text"] for r in after] == ["c", "a", "b"]
    assert [r["position"] for r in after] == [0, 1, 2]
    assert {r["id"] for r in after} == set(ids.values()), "a move must not replace a row"


def test_delete_renumbers_and_hands_back_what_it_took(kitchen):
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[2]["id"]
    for t in ("a", "b"):
        kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": t})
    gone = kitchen.client.post(f"/api/recipes/{rid}/notes",
                               json={"text": "c", "kind": "tips", "step_id": sid}).get_json()["note"]
    out = kitchen.client.delete(f"/api/recipes/{rid}/notes/{gone['id']}").get_json()
    assert out["deleted"] == gone["id"]
    assert out["restore"] == {"text": "c", "kind": "tips", "position": 2, "step_id": sid}
    assert [r["text"] for r in _notes_of(kitchen.client, rid)] == ["a", "b"]


def test_undo_puts_the_note_back_where_it_was(kitchen):
    """The Undo the client offers is a re-create from `restore`, so the round trip is the contract."""
    rid = _recipe(kitchen.client)
    for t in ("a", "b", "c"):
        kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": t})
    mid = _notes_of(kitchen.client, rid)[1]
    restore = kitchen.client.delete(f"/api/recipes/{rid}/notes/{mid['id']}").get_json()["restore"]
    assert [r["text"] for r in _notes_of(kitchen.client, rid)] == ["a", "c"]
    kitchen.client.post(f"/api/recipes/{rid}/notes", json=restore)
    back = _notes_of(kitchen.client, rid)
    assert [r["text"] for r in back] == ["a", "b", "c"]
    assert [r["position"] for r in back] == [0, 1, 2]


def test_deleting_a_note_takes_its_references_with_it(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "see step 2"}).get_json()["note"]
    assert len(n["refs"]) == 1
    kitchen.client.delete(f"/api/recipes/{rid}/notes/{n['id']}")
    import sqlite3
    con = sqlite3.connect(str(kitchen.db))
    assert con.execute("SELECT COUNT(*) FROM recipe_note_step_refs").fetchone()[0] == 0


# --- "step N" while typing -----------------------------------------------------------------------

def test_typing_step_n_auto_links_the_step_that_number_names(kitchen):
    """⚠️ AGAINST THE NUMBER THE PAGE PRINTS, which counts non-heading rows only."""
    rid = _recipe(kitchen.client, steps=[{"heading": "For the beans"},
                                         {"text": "Rinse"}, {"text": "Soak"}, {"text": "Simmer"}])
    steps = [s for s in _steps_of(kitchen.client, rid) if not s["is_heading"]]
    out = kitchen.client.post(f"/api/recipes/{rid}/notes",
                              json={"text": "Do this before step 3"}).get_json()
    refs = out["note"]["refs"]
    assert len(refs) == 1
    assert refs[0]["step_id"] == steps[2]["id"], "step 3 is the third REAL step, not row 3"
    assert refs[0]["step_no"] == 3


def test_a_number_naming_no_step_is_stored_unlinked(kitchen):
    rid = _recipe(kitchen.client)
    out = kitchen.client.post(f"/api/recipes/{rid}/notes",
                              json={"text": "see step 40"}).get_json()
    assert [r["step_id"] for r in out["note"]["refs"]] == [None]
    assert out["note"]["refs"][0]["step_no"] is None


def test_rewording_drops_a_reference_whose_words_went(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "after step 2, rest"}).get_json()["note"]
    assert len(n["refs"]) == 1
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                               json={"text": "rest for a while"}).get_json()
    assert out["note"]["refs"] == []


def test_removing_a_link_survives_the_next_keystroke(kitchen):
    """⚠️ THE CARRIED TARGET WINS OVER THE AUTO-LINK. Unlinking a mention and then typing another
    word must not re-link it, or "remove link" is a button that undoes itself."""
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "see step 2"}).get_json()["note"]
    assert n["refs"][0]["step_id"] is not None
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}/refs/0", json={"step_id": None})
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                               json={"text": "see step 2 please"}).get_json()
    assert out["note"]["refs"][0]["step_id"] is None, "the removed link came back"


def test_a_ref_route_refuses_a_mention_that_is_not_there(kitchen):
    rid = _recipe(kitchen.client)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "no mention"}).get_json()["note"]
    resp = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}/refs/0", json={"step_id": None})
    assert resp.status_code == 404


# --- the playground guarantee --------------------------------------------------------------------

def _content_bytes(kitchen, rid):
    """The recipe's serialization, through the REAL serializer the snapshot stores."""
    import app as A
    with A.orm_session() as s:
        return A.serialize_recipe_content(s, rid)


def _annotations(kitchen, rid):
    import app as A
    with A.orm_session() as s:
        return A._recipe_annotations(s, rid)


def test_no_note_write_moves_the_snapshot_bytes_or_mints_a_mark(kitchen):
    """⚠️ THE WHOLE POINT OF THE ROUND, MEASURED THROUGH THE REAL SERIALIZER.

    A note is a playground: create, edit, re-kind, move and delete, and the recipe's content bytes
    must be the same bytes afterwards, so the byte-equal short-circuit holds and no annotation entry
    appears.
    """
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[0]["id"]
    before = _content_bytes(kitchen, rid)
    assert _annotations(kitchen, rid) == []

    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "Soak overnight, see step 2"}).get_json()["note"]
    second = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "Keeps 3 days"}).get_json()["note"]
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"text": "Soak overnight"})
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"kind": "tips"})
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"step_id": sid})
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"position": 1})
    kitchen.client.delete(f"/api/recipes/{rid}/notes/{second['id']}")

    assert _content_bytes(kitchen, rid) == before, "a note write moved the snapshot bytes"
    assert _annotations(kitchen, rid) == [], "a note write minted an annotation entry"
    assert len(_notes_of(kitchen.client, rid)) == 1, "the notes really were written"


def test_the_no_marks_check_can_fail(kitchen, monkeypatch):
    """⚠️ A CHECK WITH NOTHING TO COMPARE AGAINST PASSES FOR THE WRONG REASON.

    The test above would pass just as happily if the note routes wrote nothing at all, or if the
    serializer had stopped reading content. So: put `notes` back into the snapshot's recipe fields,
    which is where it was for one round, and the same sequence must now MOVE the bytes. That proves
    the comparison is live and that leaving notes out is what makes the guarantee.
    """
    import snapshot_serialize as ss
    rid = _recipe(kitchen.client)
    monkeypatch.setattr(ss, "SNAPSHOT_RECIPE_FIELDS",
                        tuple(ss.SNAPSHOT_RECIPE_FIELDS) + ("notes",))
    before = _content_bytes(kitchen, rid)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "a note"})
    assert _content_bytes(kitchen, rid) != before, (
        "with notes in the blob a note write MUST move the bytes, so the check above is inert")


def test_a_note_write_never_touches_steps_or_ingredients(kitchen):
    rid = _recipe(kitchen.client)
    rec = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    before_steps = [(s["id"], s["text"], s["is_heading"]) for s in rec["steps"]]
    before_ings = [(i["id"], i.get("label"), i.get("raw_text")) for i in rec["ingredients"]]
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "x"}).get_json()["note"]
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"text": "y"})
    kitchen.client.delete(f"/api/recipes/{rid}/notes/{n['id']}")
    rec2 = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert [(s["id"], s["text"], s["is_heading"]) for s in rec2["steps"]] == before_steps
    assert [(i["id"], i.get("label"), i.get("raw_text")) for i in rec2["ingredients"]] == before_ings


def test_the_derived_column_follows_the_rows(kitchen):
    """recipes.notes is a derived copy, and nothing but the rows may decide what it says."""
    import sqlite3
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "one"})
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "two"}).get_json()["note"]
    con = sqlite3.connect(str(kitchen.db))
    col = con.execute("SELECT notes FROM recipes WHERE id=?", (rid,)).fetchone()[0]
    assert col == "one\n\ntwo"
    kitchen.client.delete(f"/api/recipes/{rid}/notes/{n['id']}")
    con = sqlite3.connect(str(kitchen.db))
    assert con.execute("SELECT notes FROM recipes WHERE id=?", (rid,)).fetchone()[0] == "one"


def test_last_write_wins_and_costs_only_the_wording(kitchen):
    """Two tabs, two PATCHes. The second wins, and the row, its place and its links survive."""
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[0]["id"]
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "first wording", "step_id": sid}).get_json()["note"]
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"text": "tab one"})
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={"text": "tab two"})
    row = out.get_json()["note"]
    assert row["text"] == "tab two"
    assert row["id"] == n["id"] and row["position"] == 0 and row["step_id"] == sid


# --- the Edit-mode save leaves notes alone -------------------------------------------------------

def test_an_edit_mode_save_that_omits_notes_leaves_them_alone(kitchen):
    """⚠️ ABSENT IS NOT EMPTY, and this is the rule the new client depends on. Notes left the Edit
    mode draft, so a recipe PUT no longer names them, and write_notes must read that as "do not
    touch" rather than as "clear the list"."""
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "survive me"})
    resp = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Beans, renamed",
        "ingredients": [{"raw_text": "1 cup beans"}],
        "steps": [{"text": "Rinse the beans"}, {"text": "Soak them overnight"},
                  {"text": "Simmer until tender"}]})
    assert resp.status_code == 200
    assert [r["text"] for r in _notes_of(kitchen.client, rid)] == ["survive me"]


def test_an_explicit_empty_list_still_clears_them(kitchen):
    """The old client's way of emptying the list keeps working, which is what makes the window safe."""
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "goodbye"})
    kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Beans", "ingredients": [], "steps": [{"text": "Rinse"}], "notes": []})
    assert _notes_of(kitchen.client, rid) == []


# --- a copy records the source's original notes --------------------------------------------------

def _originals(kitchen, rid):
    import sqlite3
    con = sqlite3.connect(str(kitchen.db))
    return con.execute(
        "SELECT position, kind, text FROM recipe_notes_original WHERE recipe_id=? ORDER BY position",
        (rid,)).fetchall()


def test_a_copy_records_its_original_notes_from_the_sources(kitchen):
    """⚠️ MEASURED ON LIVE AND IT WAS ZERO. A copy carried its note and the note's step reference and
    wrote no originals at all, so the copy was a playground with no way back."""
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "soak them first"})
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "Keeps 3 days", "kind": "storage"})
    new_id = kitchen.client.post(f"/api/recipes/{rid}/copy", json={}).get_json()["id"]
    assert _originals(kitchen, new_id) == [(0, "notes", "soak them first"),
                                           (1, "storage", "Keeps 3 days")]


def test_a_copy_prefers_the_sources_recorded_originals_over_its_current_words(kitchen):
    """Where the source HAS originals, those are what the copy inherits, so a machine repair to the
    source's live rows does not become the copy's idea of what the author wrote."""
    import sqlite3
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "Capitalized now"})
    con = sqlite3.connect(str(kitchen.db))
    con.execute("INSERT INTO recipe_notes_original (recipe_id, position, kind, text, recorded_at) "
                "VALUES (?, 0, 'notes', 'capitalized now', '2026-01-01 00:00:00')", (rid,))
    con.commit()
    con.close()
    new_id = kitchen.client.post(f"/api/recipes/{rid}/copy", json={}).get_json()["id"]
    assert _originals(kitchen, new_id) == [(0, "notes", "capitalized now")]


def test_a_copy_of_a_recipe_with_no_notes_records_none(kitchen):
    rid = _recipe(kitchen.client)
    new_id = kitchen.client.post(f"/api/recipes/{rid}/copy", json={}).get_json()["id"]
    assert _originals(kitchen, new_id) == []


def test_a_copys_note_links_point_at_the_copys_own_steps(kitchen):
    """The existing remap, re-stated here because the originals insert sits beside it."""
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[1]["id"]
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "see step 2", "step_id": sid})
    new_id = kitchen.client.post(f"/api/recipes/{rid}/copy", json={}).get_json()["id"]
    own = {s["id"] for s in _steps_of(kitchen.client, new_id)}
    note = _notes_of(kitchen.client, new_id)[0]
    assert note["step_id"] in own and note["step_id"] != sid
    assert note["refs"][0]["step_id"] in own


# ---------------------------------------------------------------------------------------------
# What a save writes, now that the editor shows the display text
# ---------------------------------------------------------------------------------------------

def test_saving_the_shown_text_keeps_the_link_on_the_same_step(kitchen):
    """⚠️ THE NUMBER CHANGES AND THE TARGET MUST NOT.

    The editor shows the step's CURRENT number, so a cook who edits a note saves "step 2" where the
    row said "step 3". The reference has to come back pointing at the same row, or every edit of a
    note that names a step quietly repoints it.
    """
    rid = _recipe(kitchen.client)
    steps = _steps_of(kitchen.client, rid)
    third = steps[2]["id"]
    kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "finish at step 3"})
    note = _notes_of(kitchen.client, rid)[0]
    assert [(r["match_text"], r["step_id"], r["step_no"]) for r in note["refs"]] \
        == [("step 3", third, 3)]

    # the first step goes, so the step that was 3 is now 2 and the page prints "step 2"
    kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Beans", "ingredients": [{"raw_text": "1 cup beans"}],
        "steps": [{"text": "Soak them overnight"}, {"text": "Simmer until tender"}]})
    note = _notes_of(kitchen.client, rid)[0]
    assert note["refs"][0]["step_no"] == 2, "the page resolves it to the new number"
    assert note["text"] == "finish at step 3", "and the row still holds the author's words"

    # the cook edits the note, and what the editor held was "finish at step 2"
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{note['id']}",
                         json={"text": "finish at step 2, carefully"})
    after = _notes_of(kitchen.client, rid)[0]
    assert after["text"] == "finish at step 2, carefully"
    assert [(r["match_text"], r["step_id"], r["step_no"]) for r in after["refs"]] \
        == [("step 2", third, 2)], "the same row, named by its new number"


def test_an_edit_never_touches_the_recorded_original(kitchen):
    """recipe_notes_original is the way back, and a save is not allowed to move it."""
    import models
    from sqlalchemy import select
    rid = _recipe(kitchen.client, notes="Tip: soak them first.")
    note = _notes_of(kitchen.client, rid)[0]

    import app as A

    def recorded():
        with A.orm_session() as s:
            return [(m["position"], m["kind"], m["text"]) for m in s.execute(
                select(models.RecipeNoteOriginal.__table__)
                .where(models.RecipeNoteOriginal.__table__.c.recipe_id == rid)
                .order_by(models.RecipeNoteOriginal.__table__.c.position)).mappings()]

    before = recorded()
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{note['id']}",
                         json={"text": "Soak them first, for an hour."})
    kitchen.client.patch(f"/api/recipes/{rid}/notes/{note['id']}", json={"kind": "storage"})
    assert recorded() == before, "the author's words as they arrived, untouched by either write"


def test_a_patch_with_the_same_text_is_refused_rather_than_written(kitchen):
    """⚠️ THE CLIENT DECIDES NOT TO SEND, AND THE SERVER AGREES IF IT DOES.

    Click-away fires on every blur. The client compares the draft with what the field was seeded
    with and sends nothing when they match; this is the second half of that rule, so a client that
    sends anyway cannot rewrite a row with its own contents.
    """
    rid = _recipe(kitchen.client, notes="Soak them first.")
    note = _notes_of(kitchen.client, rid)[0]
    r = kitchen.client.patch(f"/api/recipes/{rid}/notes/{note['id']}",
                             json={"text": note["text"]})
    assert r.status_code == 200, "the same words are still a legal write"
    after = _notes_of(kitchen.client, rid)[0]
    assert after["text"] == note["text"]
    assert after["id"] == note["id"], "and it is the same row, updated in place"


def test_the_picker_writes_the_link_the_page_then_prints(kitchen):
    """Picking a step in the editor is one PATCH, and the number comes back resolved.

    ⚠️ THE NUMBER IS THE SERVER'S ANSWER, NOT THE CLIENT'S. The picker shows "step 2" because the
    client counted the method, and the page prints "Step 2" because notes_rules.resolve counted it
    again on the way out. The two have to agree, so the write is checked against what the read
    returns rather than against what was sent.
    """
    rid = _recipe(kitchen.client)
    steps = _steps_of(kitchen.client, rid)
    n = kitchen.client.post(f"/api/recipes/{rid}/notes", json={"text": "watch it"}).get_json()["note"]
    assert n["step_id"] is None and n["step_no"] is None

    target = steps[1]
    out = kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                               json={"step_id": target["id"]}).get_json()
    assert out["note"]["step_id"] == target["id"]
    assert out["note"]["step_no"] == 2, "the second ordinary step, as the picker offered it"
    assert out["note"]["step_ok"] is True

    # and the recipe read agrees, which is what the Notes section draws from
    again = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    row = next(x for x in again["notes"] if x["id"] == n["id"])
    assert (row["step_id"], row["step_no"]) == (target["id"], 2)


def test_opening_the_picker_and_leaving_writes_nothing(kitchen):
    """Escape has to leave the row byte-identical, and this is the server half of that.

    The picker's whole state (the typed filter, the cursor) is client-side, so the only way it could
    reach the database is a PATCH. A PATCH naming no change is refused, which means a stray one
    cannot quietly rewrite the row either.
    """
    rid = _recipe(kitchen.client)
    sid = _steps_of(kitchen.client, rid)[0]["id"]
    n = kitchen.client.post(f"/api/recipes/{rid}/notes",
                            json={"text": "x", "step_id": sid}).get_json()["note"]
    before = kitchen.client.get(f"/api/recipes/{rid}").get_json()["notes"]
    assert before, "nothing to compare against"

    # a PATCH naming nothing is refused outright
    assert kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}", json={}).status_code == 400
    # ⚠️ AND ONE NAMING THE LINK IT ALREADY HAS IS ANSWERED 200, which is why the client refuses to
    #    send it (note-ui.js::noteStepChanged). The row is unmoved either way, and this pins that:
    #    the refusal is about keeping a glance off the wire, never about protecting the row.
    assert kitchen.client.patch(f"/api/recipes/{rid}/notes/{n['id']}",
                                json={"step_id": sid}).status_code == 200

    assert kitchen.client.get(f"/api/recipes/{rid}").get_json()["notes"] == before
