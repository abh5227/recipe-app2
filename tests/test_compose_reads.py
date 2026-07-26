"""Read-side additions for the 2b feed compose modal (routes + serializer only — no schema/DB writes).

Covers the two endpoints the compose picker needs:
  - GET /api/cooks  — MY cook_log entries (with cook_log_id), newest-first, strictly my own; auth-gated.
  - GET /api/recipes — the additive `is_mine` flag (owner == me), owner id NOT leaked (least-exposure).

Two-user cases follow the sub-stage-1/2a idiom (test_shares.py): the `kitchen` fixture logs in harness
user A; `_user_client` mints a second user B with its own client, so ownership/scope is proven with a
real second user (not hand-waved).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app         # noqa: E402
import harness     # noqa: E402

A_EMAIL = harness.HARNESS_USER_EMAIL


def _user_client(email):
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _own_recipe(client, name="My Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _cook(client, rid, date=None):
    client.post(f"/api/recipes/{rid}/cooked", json={"date": date} if date else {})


# ---- GET /api/cooks -------------------------------------------------------------------------------

def test_cooks_lists_my_cooks_newest_first_with_ids(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Bulgogi")
    _cook(a, rid, "2020-01-01")
    _cook(a, rid, "2021-06-15")          # newer

    cooks = a.get("/api/cooks").get_json()
    assert [c["cooked_on"] for c in cooks] == ["2021-06-15", "2020-01-01"]   # newest-first
    top = cooks[0]
    assert set(top) == {"cook_log_id", "recipe_id", "recipe_name", "image", "cooked_on"}
    assert isinstance(top["cook_log_id"], int)     # the id that lets the client POST /api/shares {cook_log_id}
    assert top["recipe_id"] == rid
    assert top["recipe_name"] == "Bulgogi"
    assert top["image"] is None


def test_cooks_are_strictly_my_own(kitchen):
    a = kitchen.client
    _bid, b = _user_client("b@test.local")

    rid_a = _own_recipe(a, "A Dish")
    rid_b = _own_recipe(b, "B Dish")
    _cook(a, rid_a)
    _cook(b, rid_b)

    a_cooks = a.get("/api/cooks").get_json()
    assert {c["recipe_id"] for c in a_cooks} == {rid_a}       # only A's cook — never B's
    b_cooks = b.get("/api/cooks").get_json()
    assert {c["recipe_id"] for c in b_cooks} == {rid_b}       # B sees only their own


def test_cooks_requires_auth(kitchen_logged_out):
    assert kitchen_logged_out.client.get("/api/cooks").status_code == 401


# ---- is_mine on GET /api/recipes ------------------------------------------------------------------

def test_recipes_is_mine_owned_vs_other(kitchen):
    a = kitchen.client
    _bid, b = _user_client("owner-b@test.local")

    mine = _own_recipe(a, "Mine To Share")
    theirs = _own_recipe(b, "Theirs Not Mine")

    rows = {r["id"]: r for r in a.get("/api/recipes").get_json()}
    assert rows[mine]["is_mine"] is True
    assert rows[theirs]["is_mine"] is False
    assert "owner" not in rows[mine]        # least-exposure: the raw owner id is never leaked
    assert "owner" not in rows[theirs]
