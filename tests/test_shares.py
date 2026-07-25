"""Deliberate-share feed tests (social sub-stage 2a) — the two-user + integrity cases.

SQLite suite (the sub-stage-1 pattern): the `kitchen` fixture builds the DB + logs in harness user A;
`_user_client` mints friends with their own clients. Covers friend-scoped visibility, self-feed, the
BOUNDED window/cap, share authz (own things / test-tier block / caption cap), and — the integrity
proof — that ON DELETE CASCADE fires on the real undo_cook / delete_recipe paths (a shared post can
never be orphaned). Dialect-independent; the PG cascade/CHECK echo lives in test_pg_integration.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app         # noqa: E402
import harness     # noqa: E402

A_EMAIL = harness.HARNESS_USER_EMAIL   # the kitchen client is logged in as this user (A)


def _user_client(email):
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _make_friends(a_client, b_client, b_email):
    a_client.post("/api/friends/requests", json={"email": b_email})
    b_client.post("/api/friends/accept", json={"email": A_EMAIL})


def _log_cook(client, kitchen, rid, user_id):
    """Cook `rid` as `client` and return the new cook_log.id."""
    client.post(f"/api/recipes/{rid}/cooked", json={})
    with kitchen.conn() as c:
        return c.execute(
            "SELECT id FROM cook_log WHERE recipe_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (rid, user_id),
        ).fetchone()[0]


def _own_recipe(client, name="My Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


# ---- friend-scoped visibility --------------------------------------------------------------------

def test_share_cook_visible_to_friend_not_stranger(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    _cid, c = _user_client("c@test.local")          # NOT a friend
    _make_friends(a, b, "b@test.local")

    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    assert a.post("/api/shares", json={"cook_log_id": clid, "caption": "nailed it"}).status_code == 201

    fb = b.get("/api/feed").get_json()              # friend B sees it
    assert len(fb) == 1
    assert fb[0]["post_type"] == "cook"
    assert fb[0]["recipe"]["id"] == "gai-yang"
    assert fb[0]["cooked_on"] is not None
    assert fb[0]["caption"] == "nailed it"
    assert fb[0]["sharer"]["email"] == A_EMAIL
    assert fb[0]["is_mine"] is False

    assert c.get("/api/feed").get_json() == []      # non-friend C sees nothing


def test_share_recipe_serializes_recipe(kitchen):
    a = kitchen.client
    _bid, b = _user_client("b@test.local")
    _make_friends(a, b, "b@test.local")
    rid = _own_recipe(a, "Owned Dish")

    assert a.post("/api/shares", json={"recipe_id": rid}).status_code == 201
    fb = b.get("/api/feed").get_json()
    assert len(fb) == 1 and fb[0]["post_type"] == "recipe"
    assert fb[0]["recipe"]["id"] == rid and fb[0]["recipe"]["name"] == "Owned Dish"
    assert fb[0]["cooked_on"] is None


def test_self_feed_includes_own_posts(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    a.post("/api/shares", json={"cook_log_id": clid})
    fa = a.get("/api/feed").get_json()
    assert len(fa) == 1 and fa[0]["is_mine"] is True   # include-self


# ---- the BOUNDED shape (connection-not-consumption) ----------------------------------------------

def test_feed_window_excludes_old_and_has_no_pagination(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    recent = _log_cook(a, kitchen, "gai-yang", a_id)
    a.post("/api/shares", json={"cook_log_id": recent, "caption": "fresh"})

    old_cook = _log_cook(a, kitchen, "no-knead-bread", a_id)
    old_ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    with kitchen.conn() as c:
        c.execute("INSERT INTO shared_posts (user_id, cook_log_id, caption, created_at) VALUES (?,?,?,?)",
                  (a_id, old_cook, "ancient", old_ts))
        c.commit()

    fa = a.get("/api/feed").get_json()
    assert isinstance(fa, list)                        # a plain bounded list — no cursor/next envelope
    assert len(fa) == 1 and fa[0]["caption"] == "fresh"   # the 30-day-old post is outside the window
    assert a.get("/api/feed?page=2").get_json() == fa  # no pagination param — same bounded response


def test_feed_capped_at_limit(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    clid = _log_cook(a, kitchen, "gai-yang", a_id)     # repeat shares allowed (no dedup)
    now = datetime.datetime.now(datetime.timezone.utc)
    with kitchen.conn() as c:
        for i in range(app.FEED_LIMIT + 5):            # 55 posts, all inside the window
            ts = (now - datetime.timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO shared_posts (user_id, cook_log_id, created_at) VALUES (?,?,?)",
                      (a_id, clid, ts))
        c.commit()
    assert len(a.get("/api/feed").get_json()) == app.FEED_LIMIT   # hard cap holds


# ---- ⭐ integrity: ON DELETE CASCADE fires on the real undo/delete paths (no orphans) -------------

def test_undo_cook_cascades_shared_post(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    pid = a.post("/api/shares", json={"cook_log_id": clid}).get_json()["id"]

    assert a.post("/api/recipes/gai-yang/uncook").status_code == 200   # undo_cook -> orm_session (FK on)

    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM cook_log WHERE id=?", (clid,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM shared_posts WHERE id=?", (pid,)).fetchone()[0] == 0  # cascaded
    assert a.get("/api/feed").get_json() == []                        # feed clean, no orphan


def test_delete_recipe_cascades_shared_post(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    rid = _own_recipe(a, "Doomed")
    pid = a.post("/api/shares", json={"recipe_id": rid}).get_json()["id"]

    assert a.delete(f"/api/recipes/{rid}").status_code == 200
    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM shared_posts WHERE id=?", (pid,)).fetchone()[0] == 0  # cascaded


# ---- exactly-one target + authz ------------------------------------------------------------------

def test_exactly_one_target_required(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    assert a.post("/api/shares", json={"cook_log_id": clid, "recipe_id": "gai-yang"}).status_code == 400  # both
    assert a.post("/api/shares", json={"caption": "nothing"}).status_code == 400                          # neither


def test_cannot_share_someone_elses_cook(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    b_id, b = _user_client("b@test.local")
    b_cook = _log_cook(b, kitchen, "gai-yang", b_id)         # B's cook
    assert a.post("/api/shares", json={"cook_log_id": b_cook}).status_code == 404   # A can't share it


def test_cannot_share_recipe_you_dont_own(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    # gai-yang is a seed recipe (owner NULL) — A doesn't own it
    assert a.post("/api/shares", json={"recipe_id": "gai-yang"}).status_code == 404


def test_cannot_share_test_recipe(kitchen):
    a = kitchen.client
    harness.ensure_test_user()
    rid = a.post("/api/recipes", json={"name": "Scratch", "is_test": True,
                                       "ingredients": [], "steps": []}).get_json()["id"]
    assert a.post("/api/shares", json={"recipe_id": rid}).status_code == 400


def test_only_sharer_can_unshare(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    _bid, b = _user_client("b@test.local")
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    pid = a.post("/api/shares", json={"cook_log_id": clid}).get_json()["id"]

    assert b.delete(f"/api/shares/{pid}").status_code == 404       # not the sharer
    assert a.delete(f"/api/shares/{pid}").status_code == 200       # sharer can retract
    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM shared_posts").fetchone()[0] == 0


def test_caption_over_max_rejected(kitchen):
    a = kitchen.client
    a_id = harness.ensure_test_user()
    clid = _log_cook(a, kitchen, "gai-yang", a_id)
    assert a.post("/api/shares", json={"cook_log_id": clid, "caption": "x" * (app.CAPTION_MAX + 1)}).status_code == 400
    assert a.post("/api/shares", json={"cook_log_id": clid, "caption": "x" * app.CAPTION_MAX}).status_code == 201
