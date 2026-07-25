"""Comments-on-feed-posts tests (backend) — two-user + the 2-level cascade.

SQLite suite (the shares/friends pattern): the `kitchen` fixture builds the DB + logs in harness user A;
`_user_client` mints friends with their own clients. Covers friends-only authz (== feed visibility),
delete-own + post-owner-remove, the embedded/oldest-first feed serialization, body limits, and — the
integrity proof — the recipe -> post -> comment and unshare -> comment cascades on the real routes.
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


def _make_friends(a_client, b_client, b_email):
    a_client.post("/api/friends/requests", json={"email": b_email})
    b_client.post("/api/friends/accept", json={"email": A_EMAIL})


def _own_recipe(client, name="My Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _share_recipe(client, rid):
    return client.post("/api/shares", json={"recipe_id": rid}).get_json()["id"]


def _log_cook(client, kitchen, rid, user_id):
    client.post(f"/api/recipes/{rid}/cooked", json={})
    with kitchen.conn() as c:
        return c.execute("SELECT id FROM cook_log WHERE recipe_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                         (rid, user_id)).fetchone()[0]


def _count(kitchen, table):
    with kitchen.conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _feed_post(client, pid):
    return next((p for p in client.get("/api/feed").get_json() if p["id"] == pid), None)


# ---- friends-only visibility + serialization -----------------------------------------------------

def test_friend_comment_appears_in_feed(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    rid = _own_recipe(a, "Shared Dish")
    pid = _share_recipe(a, rid)

    r = b.post(f"/api/posts/{pid}/comments", json={"body": "looks amazing"})
    assert r.status_code == 201 and r.get_json()["body"] == "looks amazing"

    # A (post owner) sees B's comment embedded; not mine, but deletable (A owns the post)
    pa = _feed_post(a, pid)
    assert [c["body"] for c in pa["comments"]] == ["looks amazing"]
    ca = pa["comments"][0]
    assert ca["is_mine"] is False and ca["can_delete"] is True and ca["author"]["display_name"] is None
    # B sees own comment: is_mine True, deletable (author)
    cb = _feed_post(b, pid)["comments"][0]
    assert cb["is_mine"] is True and cb["can_delete"] is True


def test_non_friend_cannot_comment(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _cid, c = _user_client("c@test.local")          # NOT a friend of A
    rid = _own_recipe(a, "Private-ish")
    pid = _share_recipe(a, rid)
    assert c.post(f"/api/posts/{pid}/comments", json={"body": "hi"}).status_code == 404   # non-leaking
    assert _count(kitchen, "comments") == 0


def test_comment_on_own_post(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    pid = _share_recipe(a, _own_recipe(a, "Mine"))
    assert a.post(f"/api/posts/{pid}/comments", json={"body": "note to self"}).status_code == 201


def test_comments_oldest_first_and_grouped(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    p1 = _share_recipe(a, _own_recipe(a, "Dish One"))
    p2 = _share_recipe(a, _own_recipe(a, "Dish Two"))
    a.post(f"/api/posts/{p1}/comments", json={"body": "first"})
    b.post(f"/api/posts/{p1}/comments", json={"body": "second"})
    b.post(f"/api/posts/{p2}/comments", json={"body": "other post"})

    assert [c["body"] for c in _feed_post(a, p1)["comments"]] == ["first", "second"]   # oldest-first
    assert [c["body"] for c in _feed_post(a, p2)["comments"]] == ["other post"]        # correct grouping


# ---- delete authz --------------------------------------------------------------------------------

def test_author_deletes_own_comment(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    pid = _share_recipe(a, _own_recipe(a))
    cid = b.post(f"/api/posts/{pid}/comments", json={"body": "mine to delete"}).get_json()["id"]
    assert b.delete(f"/api/comments/{cid}").status_code == 200
    assert _count(kitchen, "comments") == 0


def test_post_owner_removes_a_comment(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    pid = _share_recipe(a, _own_recipe(a))
    cid = b.post(f"/api/posts/{pid}/comments", json={"body": "owner can remove me"}).get_json()["id"]
    assert a.delete(f"/api/comments/{cid}").status_code == 200      # A owns the post -> may moderate
    assert _count(kitchen, "comments") == 0


def test_non_party_cannot_delete_comment(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _cid, c = _user_client("c@test.local")
    _make_friends(a, b, "b@test.local")
    pid = _share_recipe(a, _own_recipe(a))
    cid = b.post(f"/api/posts/{pid}/comments", json={"body": "not yours to delete"}).get_json()["id"]
    assert c.delete(f"/api/comments/{cid}").status_code == 404      # neither author nor post owner
    assert _count(kitchen, "comments") == 1


# ---- ⭐ the 2-level cascade (recipe/cook -> post -> comment) --------------------------------------

def test_delete_recipe_cascades_post_and_comments(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    rid = _own_recipe(a, "Doomed")
    pid = _share_recipe(a, rid)
    b.post(f"/api/posts/{pid}/comments", json={"body": "rip"})
    assert _count(kitchen, "comments") == 1

    assert a.delete(f"/api/recipes/{rid}").status_code == 200       # recipe -> shared_post -> comment
    assert _count(kitchen, "shared_posts") == 0
    assert _count(kitchen, "comments") == 0                         # the whole thread cascaded


def test_undo_cook_cascades_post_and_comments(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    pid = a.post("/api/shares", json={"cook_log_id": clid}).get_json()["id"]
    b.post(f"/api/posts/{pid}/comments", json={"body": "yum"})

    assert a.post("/api/recipes/gai-yang/uncook").status_code == 200   # cook_log delete -> post -> comment
    assert _count(kitchen, "shared_posts") == 0
    assert _count(kitchen, "comments") == 0


def test_unshare_cascades_comments(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    pid = _share_recipe(a, _own_recipe(a))
    b.post(f"/api/posts/{pid}/comments", json={"body": "before unshare"})
    assert a.delete(f"/api/shares/{pid}").status_code == 200        # unshare -> comment cascades
    assert _count(kitchen, "comments") == 0


# ---- body limits ---------------------------------------------------------------------------------

def test_body_limits(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    pid = _share_recipe(a, _own_recipe(a))
    assert a.post(f"/api/posts/{pid}/comments", json={"body": "x" * (app.COMMENT_MAX + 1)}).status_code == 400
    assert a.post(f"/api/posts/{pid}/comments", json={"body": "   "}).status_code == 400        # whitespace
    assert a.post(f"/api/posts/{pid}/comments", json={"body": ""}).status_code == 400
    assert a.post(f"/api/posts/{pid}/comments", json={"body": "x" * app.COMMENT_MAX}).status_code == 201
