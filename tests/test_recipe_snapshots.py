"""Change-tracking stage 1: the recipe_snapshots table + capture-on-cook. Pins (a) the pure
serialize_recipe_content blob (content in, non-content out, stable + position-ordered), (b) that EVERY
cook-log path writes a reason='cook' snapshot (log_cook instant + backdate, log_cook_and_rate, redo_cook —
a missed path = a cook with no snapshot), and (c) that undoing a cook cascade-removes its snapshot.
Nothing reads snapshots yet (the diff / Journal are stages 3-4)."""
import json

from sqlalchemy import inspect

import app
import harness


def _recipe_with_content(client, name="Snapshot Dish"):
    return client.post("/api/recipes", json={
        "name": name,
        "ingredients": [
            {"heading": "For the base"},
            {"qty": "2", "text": "eggs"},
            {"qty": "1 cup", "text": "milk"},
        ],
        "steps": ["Beat the eggs well", "Whisk in the milk"],
    }).get_json()["id"]


def _snaps(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute(
            "SELECT id, recipe_id, cook_log_id, user_id, reason, content, created_at "
            "FROM recipe_snapshots WHERE recipe_id = ? ORDER BY id", (rid,)).fetchall()


# ---- the table exists (migration 028 applied by build_db) ---------------------------------------

def test_migration_creates_recipe_snapshots(kitchen):
    with app.orm_session() as s:
        insp = inspect(s.get_bind())
        assert "recipe_snapshots" in insp.get_table_names()
        cols = {c["name"] for c in insp.get_columns("recipe_snapshots")}
        assert cols == {"id", "recipe_id", "cook_log_id", "user_id", "reason", "content", "created_at"}
        idx = {i["name"] for i in insp.get_indexes("recipe_snapshots")}
        assert "idx_recipe_snapshots_recipe" in idx        # per-recipe history (stage-3 diff)
        assert "idx_recipe_snapshots_cook_log" in idx       # the cook <-> snapshot link


# ---- serialize_recipe_content (the load-bearing pure serialization) -----------------------------

def test_serialize_captures_content_excludes_noncontent_and_is_stable(kitchen):
    a = kitchen.client
    rid = _recipe_with_content(a)
    with app.orm_session() as s:
        blob = app.serialize_recipe_content(s, rid)
        blob2 = app.serialize_recipe_content(s, rid)
    assert blob == blob2                                    # deterministic (stable order + sorted keys)
    data = json.loads(blob)                                 # round-trips
    assert set(data.keys()) == {"recipe", "ingredients", "steps"}
    # the 11 content fields captured; non-content excluded
    assert data["recipe"]["name"] == "Snapshot Dish"
    assert set(data["recipe"].keys()) == {"name", "author", "source_url", "category", "servings",
        "prep_time", "cook_time", "total_time", "descr", "notes", "image"}
    for k in ("id", "owner", "source", "uid", "hash", "created_at"):
        assert k not in data["recipe"]
    # ingredient rows ordered by position; the heading captured
    positions = [i["position"] for i in data["ingredients"]]
    assert positions == sorted(positions)
    assert any(i["is_heading"] for i in data["ingredients"])
    # steps: text + order preserved verbatim (serialize copies recipe_steps.text as-is, incl. any [[ ]] markup)
    assert [st["text"] for st in data["steps"]] == ["Beat the eggs well", "Whisk in the milk"]


# ---- capture on EACH cook path ------------------------------------------------------------------

def _assert_one_cook_snapshot(kitchen, rid, cook_log_id, uid):
    rows = _snaps(kitchen, rid)
    assert len(rows) == 1
    r = rows[0]
    assert r["reason"] == "cook"
    assert r["cook_log_id"] == cook_log_id
    assert r["user_id"] == uid
    assert r["created_at"]
    with app.orm_session() as s:
        assert r["content"] == app.serialize_recipe_content(s, rid)   # the captured blob is the recipe's content


def test_snapshot_on_cooked_instant(kitchen):
    a = kitchen.client
    uid = harness.ensure_test_user()                        # kitchen.client is logged in as the harness user
    rid = _recipe_with_content(a)
    clid = a.post(f"/api/recipes/{rid}/cooked", json={}).get_json()["cook_log_id"]
    _assert_one_cook_snapshot(kitchen, rid, clid, uid)


def test_snapshot_on_cooked_backdate(kitchen):
    a = kitchen.client
    uid = harness.ensure_test_user()
    rid = _recipe_with_content(a)
    clid = a.post(f"/api/recipes/{rid}/cooked", json={"date": "2024-05-01"}).get_json()["cook_log_id"]
    _assert_one_cook_snapshot(kitchen, rid, clid, uid)


def test_snapshot_on_cooked_and_rated(kitchen):
    a = kitchen.client
    uid = harness.ensure_test_user()
    rid = _recipe_with_content(a)
    clid = a.post(f"/api/recipes/{rid}/cooked-and-rated", json={"rating": 5}).get_json()["cook_log_id"]
    _assert_one_cook_snapshot(kitchen, rid, clid, uid)


def test_snapshot_on_redo_cook(kitchen):
    a = kitchen.client
    rid = _recipe_with_content(a)
    a.post(f"/api/recipes/{rid}/cooked", json={"date": "2024-05-01"})
    undone = a.post(f"/api/recipes/{rid}/uncook", json={}).get_json()["undone"]   # removes the cook + its snapshot
    assert _snaps(kitchen, rid) == []                                            # (cascade also proven below)
    a.post(f"/api/recipes/{rid}/redo-cook",
           json={"cooked_on": undone["cooked_on"], "source": undone["source"]})   # a redo = a NEW cook
    rows = _snaps(kitchen, rid)
    assert len(rows) == 1
    assert rows[0]["reason"] == "cook" and rows[0]["cook_log_id"] is not None      # its own fresh snapshot


# ---- undo cascades the snapshot -----------------------------------------------------------------

def test_undo_cook_cascade_removes_snapshot(kitchen):
    a = kitchen.client
    rid = _recipe_with_content(a)
    a.post(f"/api/recipes/{rid}/cooked", json={})
    assert len(_snaps(kitchen, rid)) == 1
    a.post(f"/api/recipes/{rid}/uncook", json={})
    assert _snaps(kitchen, rid) == []       # ON DELETE CASCADE removed it with the cook_log row
