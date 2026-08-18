"""Original-baseline capture (O-a): a NEW recipe gets a reason='original' snapshot at birth — the
pristine baseline the recipe-page annotations (O-c) will diff the current version against. Covers the
app-create path (the import path is in test_import_write.py). Pins: create captures ONE original; the
guard makes it once; original is DISTINCT from cook (both coexist); and — the whole point — an EDIT does
NOT re-capture the original (edits are what annotations diff AGAINST the birth state). Nothing reads
these yet (O-c renders later)."""
import json

import app
import harness


def _recipe(client, name="Baseline Dish"):
    return client.post("/api/recipes", json={
        "name": name,
        "ingredients": [{"heading": "For the base"}, {"qty": "2", "text": "eggs"}],
        "steps": ["Beat the eggs"],
    }).get_json()["id"]


def _snaps(kitchen, rid, reason=None):
    q = "SELECT id, cook_log_id, reason, content FROM recipe_snapshots WHERE recipe_id = ?"
    args = [rid]
    if reason is not None:
        q += " AND reason = ?"
        args.append(reason)
    with kitchen.conn() as c:
        return c.execute(q + " ORDER BY id", args).fetchall()


def test_create_captures_original(kitchen):
    rid = _recipe(kitchen.client)
    orig = _snaps(kitchen, rid, "original")
    assert len(orig) == 1
    assert orig[0]["cook_log_id"] is None                  # cook-less baseline
    assert '"name":"Baseline Dish"' in orig[0]["content"]  # the pristine content


def test_original_captured_once_guard(kitchen):
    rid = _recipe(kitchen.client)
    with app.orm_session() as s:
        app.snapshot_original(s, rid)                      # re-trigger the helper directly
        app.snapshot_original(s, rid)
        s.commit()
    assert len(_snaps(kitchen, rid, "original")) == 1      # still ONE — the WHERE NOT EXISTS guard holds


def test_original_distinct_from_cook(kitchen):
    rid = _recipe(kitchen.client)
    kitchen.client.post(f"/api/recipes/{rid}/cooked")      # logs a cook -> a reason='cook' snapshot
    reasons = sorted(r["reason"] for r in _snaps(kitchen, rid))
    assert reasons == ["cook", "original"]                 # both coexist, distinct reasons


def test_edit_does_not_recapture_original(kitchen):
    rid = _recipe(kitchen.client)
    # edit the recipe (a PUT through write_recipe_rows) — must NOT add a second original
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Baseline Dish", "servings": "8",
        "ingredients": [{"heading": "For the base"}, {"qty": "3", "text": "eggs"}],
        "steps": ["Beat the eggs harder"],
    })
    assert r.status_code == 200
    assert len(_snaps(kitchen, rid, "original")) == 1      # original is the BIRTH state, never re-captured on edit


def test_copy_captures_original_of_copied_content(kitchen):
    # The 3rd creation path: a COPY's original = its copied content at birth (before editing) — closes the
    # gap O-b (seed.py/Paprika backfill) can't fill, since a copy is in neither source.
    a = kitchen.client
    src = _recipe(a, "Copy Source")
    cid = a.post(f"/api/recipes/{src}/copy").get_json()["id"]
    orig = _snaps(kitchen, cid, "original")
    assert len(orig) == 1
    assert orig[0]["cook_log_id"] is None
    with app.orm_session() as s:                            # the original == the copy's current content at birth
        assert orig[0]["content"] == app.serialize_recipe_content(s, cid)


def test_copy_then_edit_keeps_copied_birth_original(kitchen):
    a = kitchen.client
    src = _recipe(a, "Copy Then Edit Source")
    cid = a.post(f"/api/recipes/{src}/copy").get_json()["id"]
    birth = _snaps(kitchen, cid, "original")[0]["content"]  # the copied birth state
    r = a.put(f"/api/recipes/{cid}", json={
        "name": "Copy Then Edit Source (copy)", "servings": "12",
        "ingredients": [{"qty": "9", "text": "eggs"}], "steps": ["Totally different"],
    })
    assert r.status_code == 200
    orig = _snaps(kitchen, cid, "original")
    assert len(orig) == 1                                   # still ONE — the edit did not re-capture
    # This edit also DROPS the "For the base" heading, and since the heading-sync write path landed
    # (app.sync_original_heading_layout) the baseline's heading LAYOUT follows the current rows — so the
    # blob is no longer byte-identical. The assertion this test exists to make is about the birth
    # CONTENT, which must survive an edit verbatim; that is what is checked now. Heading layout carries
    # no information (heading changes emit no annotations), and the transform's content-safety
    # postcondition is pinned in tests/test_heading_sync.py + tests/test_heading_sync_write.py.
    bare = lambda blob, key: [{k: v for k, v in row.items() if k != "position"}
                              for row in json.loads(blob)[key] if not row["is_heading"]]
    assert bare(orig[0]["content"], "ingredients") == bare(birth, "ingredients")
    assert bare(orig[0]["content"], "steps") == bare(birth, "steps")
    assert json.loads(orig[0]["content"])["recipe"] == json.loads(birth)["recipe"]
