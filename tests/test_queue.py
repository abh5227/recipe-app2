"""Want-to-make queue API (stage 2) — the three per-user routes over the recipe_queue table
(schema: migration 024, backfilled stage 1). Routes only; no schema/data change here.

  - GET    /api/queue              — MY queue, newest-first, join recipe_queue -> recipes; auth-gated.
  - POST   /api/queue {recipe_id}  — add (idempotent via ON CONFLICT DO NOTHING); any visible recipe.
  - DELETE /api/queue/<recipe_id>  — remove MY entry, keyed by recipe_id (undo_cook idiom); uniform.

Two-user cases follow the sub-stage-1/2a idiom (test_compose_reads.py / test_shares.py): the `kitchen`
fixture logs in harness user A; `_user_client` mints a second user B. State is driven through the REAL
endpoints (POST /api/queue), not raw inserts, so the write path is exercised.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app         # noqa: E402
import harness     # noqa: E402


def _user_client(email):
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _own_recipe(client, name="My Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _queue(client, rid):
    return client.post("/api/queue", json={"recipe_id": rid})


# ---- GET /api/queue -------------------------------------------------------------------------------

def test_queue_lists_my_queue_newest_first_with_shape(kitchen):
    a = kitchen.client
    first = _own_recipe(a, "Ratatouille")
    second = _own_recipe(a, "Cassoulet")
    assert _queue(a, first).status_code == 201
    assert _queue(a, second).status_code == 201     # added later -> newer

    q = a.get("/api/queue").get_json()
    assert [row["recipe_name"] for row in q] == ["Cassoulet", "Ratatouille"]   # newest add first
    top = q[0]
    assert set(top) == {"queue_id", "recipe_id", "recipe_name", "image", "added_at"}
    assert isinstance(top["queue_id"], int)          # exposed for a future reorder/notes consumer
    assert top["recipe_id"] == second
    assert top["recipe_name"] == "Cassoulet"
    assert top["image"] is None


def test_queue_is_strictly_my_own(kitchen):
    a = kitchen.client
    _bid, b = _user_client("queue-b@test.local")

    rid_a = _own_recipe(a, "A Queue Dish")
    rid_b = _own_recipe(b, "B Queue Dish")
    _queue(a, rid_a)
    _queue(b, rid_b)

    a_q = a.get("/api/queue").get_json()
    assert {row["recipe_id"] for row in a_q} == {rid_a}     # only A's add — never B's
    b_q = b.get("/api/queue").get_json()
    assert {row["recipe_id"] for row in b_q} == {rid_b}     # B sees only their own


# ---- POST /api/queue ------------------------------------------------------------------------------

def test_queue_add_is_idempotent_no_op_on_repeat(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Pot au Feu")
    assert _queue(a, rid).status_code == 201
    assert _queue(a, rid).status_code == 201     # same recipe again — clean no-op, not a 500

    q = a.get("/api/queue").get_json()
    assert [row["recipe_id"] for row in q] == [rid]   # still exactly ONE row (ON CONFLICT DO NOTHING)


def test_queue_add_can_queue_another_users_recipe(kitchen):
    # A want-to-make queue is for recipes you haven't made — including OTHERS'. Not owner-restricted.
    a = kitchen.client
    _bid, b = _user_client("queue-owner-b@test.local")
    theirs = _own_recipe(b, "Their Dish To Try")

    assert _queue(a, theirs).status_code == 201
    assert {row["recipe_id"] for row in a.get("/api/queue").get_json()} == {theirs}


def test_queue_add_missing_recipe_id_400(kitchen):
    a = kitchen.client
    assert a.post("/api/queue", json={}).status_code == 400


def test_queue_add_nonexistent_recipe_404(kitchen):
    a = kitchen.client
    assert a.post("/api/queue", json={"recipe_id": "no-such-recipe"}).status_code == 404


# ---- DELETE /api/queue/<recipe_id> ----------------------------------------------------------------

def test_queue_remove_deletes_my_entry(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Coq au Vin")
    _queue(a, rid)
    assert a.delete(f"/api/queue/{rid}").status_code == 200
    assert a.get("/api/queue").get_json() == []       # gone


def test_queue_remove_absent_is_uniform_ok(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Never Queued")
    r = a.delete(f"/api/queue/{rid}")                 # not in the queue
    assert r.status_code == 200 and r.get_json() == {"ok": True}   # idempotent, non-leaking


def test_queue_remove_cannot_delete_another_users_entry(kitchen):
    a = kitchen.client
    _bid, b = _user_client("queue-del-b@test.local")
    rid = _own_recipe(b, "B's Wanted Dish")
    _queue(b, rid)

    a.delete(f"/api/queue/{rid}")                      # A tries to remove B's entry -> scoped away
    assert {row["recipe_id"] for row in b.get("/api/queue").get_json()} == {rid}   # B's entry stands


# ---- auth gate ------------------------------------------------------------------------------------

def test_queue_requires_auth(kitchen_logged_out):
    c = kitchen_logged_out.client
    assert c.get("/api/queue").status_code == 401
    assert c.post("/api/queue", json={"recipe_id": "x"}).status_code == 401
    assert c.delete("/api/queue/x").status_code == 401
