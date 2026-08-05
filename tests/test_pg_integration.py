"""Postgres integration suite (Stage 2c-2) — the scoped dialect-divergence coverage.

GATED: the whole module SKIPS unless DATABASE_URL is a postgresql URL. So `pytest` with
DATABASE_URL unset runs the SQLite suite exactly as before (this file skipped); `pytest` with
DATABASE_URL=postgresql+psycopg://... runs these against the PG test DB (schema from
`alembic upgrade head`). CI wires the env var + a postgres:16 service in 2c-3.

Covers the real dialect-divergence classes the diagnostic identified (Option S, correctly scoped —
NOT just upserts): the on_conflict UPSERTS, LIST ORDERING (collation — differs SQLite↔PG),
recipe_stats AGGREGATIONS, DELETE-CASCADE (PG-native FK), and SEQUENCE-after-insert (the setval
payoff). Each test exercises the real app routes (test client → orm_session → PG). Per-test
isolation via pg_harness.reset_and_seed (truncate-reseed), since the app commits.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(__file__))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PG integration suite — set DATABASE_URL=postgresql+psycopg://… to run",
)

import app                       # noqa: E402
import harness                   # noqa: E402  (auth-3b: reserved-user create + client login helpers)
import pg_harness                # noqa: E402
from sqlalchemy import create_engine, text   # noqa: E402

# The PG-native (linguistic collation) order of the 5 seeded TEST_RECIPES by name — this is the
# INTENDED list order (decision A: accept PG's collation). It differs from SQLite's BINARY order,
# which is exactly the divergence class the byte-identical checks missed; pinned here as correct.
EXPECTED_RECIPE_ORDER = ["bulgogi-bowls", "no-knead-bread", "mussakhan", "aloo-gobhi", "gai-yang"]


@pytest.fixture
def pg():
    """Fresh truncate-reseeded PG + the real app test client, per test (isolation; app commits).
    auth-3b: routes are login-gated, so authenticate the client. The reserved user is created AFTER
    reset_and_seed (which TRUNCATEs users), and login signs the cookie with the PG-step SECRET_KEY."""
    engine = create_engine(DATABASE_URL, future=True)
    pg_harness.reset_and_seed(engine)
    client = app.app.test_client()
    harness.login_test_client(client, harness.ensure_test_user())
    try:
        yield SimpleNamespace(engine=engine, client=client)
    finally:
        engine.dispose()


def _count(engine, sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


# ---- 1. UPSERTS (the known dialect target) -------------------------------------------------------

def test_rating_upsert_in_place(pg):
    """ON CONFLICT(recipe_id): set then re-set updates in place — one row, no duplicate."""
    c = pg.client
    assert c.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 5}).get_json()["rating"] == 5
    assert c.post("/api/recipes/gai-yang/rating", json={"rating": 3}).get_json()["rating"] == 3
    assert _count(pg.engine, "SELECT COUNT(*) FROM ratings WHERE recipe_id='gai-yang'") == 1


# ---- 2. LIST ORDERING (collation — differs SQLite↔PG) --------------------------------------------

def test_list_ordering_is_pg_collation(pg):
    """GET list endpoints return PG's native collation order (decision A). Pinned for recipes;
    for ingredients, assert the route order matches PG's own ORDER BY (route orders correctly)."""
    c = pg.client
    recs = [r["id"] for r in c.get("/api/recipes").get_json()]
    assert recs == EXPECTED_RECIPE_ORDER                                        # PG linguistic order (intended)
    with pg.engine.connect() as conn:
        db_recipes = [r[0] for r in conn.execute(text("SELECT id FROM recipes ORDER BY name"))]
        db_ings = [r[0] for r in conn.execute(text("SELECT id FROM ingredients ORDER BY name"))]
    assert recs == db_recipes                                                   # route == PG ORDER BY name
    ings = [i["id"] for i in c.get("/api/ingredients").get_json()]
    assert ings == db_ings and len(ings) == 36


# ---- 3. recipe_stats AGGREGATIONS (correlated subqueries / MAX over text dates) ------------------

def test_recipe_stats_aggregations(pg):
    c = pg.client
    c.post("/api/recipes/gai-yang/cooked", json={"date": "2024-05-01"})
    c.post("/api/recipes/gai-yang/cooked", json={"date": "2024-06-15"})
    c.post("/api/recipes/gai-yang/rating", json={"rating": 4})
    stats = c.get("/api/recipes/gai-yang").get_json()["stats"]
    assert stats["cook_count"] == 2
    assert stats["last_cooked"] == "2024-06-15"                                 # MAX over text-date cooked_on
    assert stats["rating"] == 4
    row = next(r for r in c.get("/api/recipes").get_json() if r["id"] == "gai-yang")
    assert row["cook_count"] == 2 and row["last_cooked"] == "2024-06-15" and row["rating"] == 4   # list subqueries agree


# ---- 4. DELETE-CASCADE (PG-native FK; the 2b-1 PRAGMA no-ops on PG) -------------------------------

def test_delete_cascade_pg_native(pg):
    c = pg.client
    rid = c.post("/api/recipes", json={"name": "PG Cascade", "is_test": True,
                 "ingredients": [{"qty": "1", "text": "x"}], "steps": ["go"]}).get_json()["id"]
    c.post(f"/api/recipes/{rid}/cooked-and-rated", json={"rating": 5})
    kids = ["recipe_ingredients", "recipe_steps", "cook_log", "ratings"]
    before = {t: _count(pg.engine, f"SELECT COUNT(*) FROM {t} WHERE recipe_id=:r", r=rid) for t in kids}
    assert c.delete(f"/api/recipes/{rid}").status_code == 200
    after = {t: _count(pg.engine, f"SELECT COUNT(*) FROM {t} WHERE recipe_id=:r", r=rid) for t in kids}
    assert any(v > 0 for v in before.values()) and all(v == 0 for v in after.values())


# ---- 5. SEQUENCE-after-insert (RESTART IDENTITY + app inserts coexist, no collision) -------------

def test_sequence_after_insert(pg):
    c = pg.client
    max_before = _count(pg.engine, "SELECT MAX(id) FROM recipe_ingredients") or 0
    rid = c.post("/api/recipes", json={"name": "Seq Check", "is_test": True,
                 "ingredients": [{"qty": "1", "text": "a"}, {"qty": "2", "text": "b"}], "steps": ["s"]}).get_json()["id"]
    with pg.engine.connect() as conn:
        new_ids = [r[0] for r in conn.execute(
            text("SELECT id FROM recipe_ingredients WHERE recipe_id=:r"), {"r": rid})]
    assert new_ids and all(i > max_before for i in new_ids)


# ---- 6. per-user cook/rating scoping — the cross-bleed pin (rescoping R4, consideration #3) -------

def test_undo_cook_rating_is_per_user_no_cross_bleed(pg):
    """MY undo (cooks -> 0) must drop only MY rating, never another user's on the same recipe. The
    single-user harness can't catch this — it needs two users. Sharpest isolation of the rating-delete
    cross-bleed: user B RATES the recipe without cooking it (0 cooks); user A cooks once then undoes.
    With the R4 user-filter, A's undo drops only A's (absent) rating; the old unscoped
    delete(Rating).where(recipe_id) would wipe B's rating too."""
    a_id = harness.ensure_test_user()                                 # the harness user (pg.client is A)
    b_id = harness.ensure_test_user(email="userb@test.local")         # a 2nd user
    ca = pg.client
    cb = app.app.test_client()
    harness.login_test_client(cb, b_id)
    rid = "gai-yang"
    assert cb.post(f"/api/recipes/{rid}/rating", json={"rating": 3}).status_code == 200   # B rates, does NOT cook
    assert ca.post(f"/api/recipes/{rid}/cooked", json={}).status_code == 200              # A cooks once (no rating)
    assert ca.post(f"/api/recipes/{rid}/uncook").status_code == 200                       # A undoes -> A's cooks 0
    b_rating = _count(pg.engine, "SELECT rating FROM ratings WHERE recipe_id=:r AND user_id=:u", r=rid, u=b_id)
    a_ratings = _count(pg.engine, "SELECT COUNT(*) FROM ratings WHERE recipe_id=:r AND user_id=:u", r=rid, u=a_id)
    assert b_rating == 3      # B's rating SURVIVES A's undo (the cross-bleed would have deleted it)
    assert a_ratings == 0     # A never rated; A's undo-to-0 only ever touches A's own layer


def test_reads_are_user_scoped(pg):
    """R5 (the crux): list_recipes + get_recipe show MY rating/cook_count/last_cooked — not a global
    aggregate, not the other user's. A rates 4 + cooks 2×; B rates 2 + cooks 1×; each sees only theirs."""
    b_id = harness.ensure_test_user(email="userb@test.local")
    ca = pg.client
    cb = app.app.test_client()
    harness.login_test_client(cb, b_id)
    rid = "gai-yang"
    ca.post(f"/api/recipes/{rid}/cooked", json={"date": "2024-01-01"})
    ca.post(f"/api/recipes/{rid}/cooked", json={"date": "2024-02-02"})
    ca.post(f"/api/recipes/{rid}/rating", json={"rating": 4})
    cb.post(f"/api/recipes/{rid}/cooked", json={"date": "2024-03-03"})
    cb.post(f"/api/recipes/{rid}/rating", json={"rating": 2})
    # get_recipe: each sees their OWN stats
    sa = ca.get(f"/api/recipes/{rid}").get_json()["stats"]
    sb = cb.get(f"/api/recipes/{rid}").get_json()["stats"]
    assert (sa["rating"], sa["cook_count"], sa["last_cooked"]) == (4, 2, "2024-02-02")
    assert (sb["rating"], sb["cook_count"], sb["last_cooked"]) == (2, 1, "2024-03-03")
    # list_recipes: same per-user scoping on the list row (the raw text() subqueries)
    la = next(r for r in ca.get("/api/recipes").get_json() if r["id"] == rid)
    lb = next(r for r in cb.get("/api/recipes").get_json() if r["id"] == rid)
    assert (la["rating"], la["cook_count"], la["last_cooked"]) == (4, 2, "2024-02-02")
    assert (lb["rating"], lb["cook_count"], lb["last_cooked"]) == (2, 1, "2024-03-03")


def test_untouched_recipe_empty_stats_but_still_listed(pg):
    """R5 empty case + visibility: a recipe the user never touched shows rating=NULL, cook_count=0,
    last_cooked=NULL — and STILL appears in the list (recipes are NOT owner-filtered; all stay visible)."""
    ca = pg.client
    other = "no-knead-bread"                                  # a seeded recipe the user never rates/cooks
    s = ca.get(f"/api/recipes/{other}").get_json()["stats"]
    assert s["rating"] is None and s["cook_count"] == 0 and s["last_cooked"] is None
    lst = ca.get("/api/recipes").get_json()
    row = next((r for r in lst if r["id"] == other), None)
    assert row is not None                                    # still listed
    assert row["rating"] is None and row["cook_count"] == 0 and row["last_cooked"] is None
    assert len(lst) == len(EXPECTED_RECIPE_ORDER)             # ALL seeded recipes visible (none owner-filtered)


# ---- 7. friend graph — composite PK + status/self CHECKs on PG (dialect echo, social sub-stage 1) --

def _expect_error(engine, sql, **params):
    """A raw INSERT that must be rejected by a PG constraint — the exception propagates out of begin()
    (rolling back), and pytest.raises catches it outside, so the transaction is never left aborted."""
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text(sql), params)


def test_friend_graph_pg_dialect(pg):
    """PG echo (like the ratings composite-PK coverage): the friend-graph ROUTES round-trip on Postgres,
    and the composite PK + status CHECK + self CHECK all enforce there — the constraints Alembic
    autogenerate wouldn't have emitted, so this pins the hand-authored revision."""
    a_id = harness.ensure_test_user()                                 # harness user A (pg.client is A)
    b_id = harness.ensure_test_user(email="friendb@test.local")
    ca = pg.client
    cb = app.app.test_client()
    harness.login_test_client(cb, b_id)
    a_email = harness.HARNESS_USER_EMAIL

    # routes work end-to-end on PG: request -> accept -> one accepted row
    assert ca.post("/api/friends/requests", json={"email": "friendb@test.local"}).status_code == 200
    assert cb.post("/api/friends/accept", json={"email": a_email}).status_code == 200
    assert _count(pg.engine, "SELECT COUNT(*) FROM friendships WHERE status='accepted'") == 1

    ins = "INSERT INTO friendships (requester_id, addressee_id, status, created_at) VALUES (:r,:a,:s,'t')"
    _expect_error(pg.engine, ins, r=a_id, a=b_id, s="pending")        # composite PK: dup (a,b) rejected
    _expect_error(pg.engine, ins, r=b_id, a=a_id, s="bogus")          # status CHECK: bad value rejected
    _expect_error(pg.engine, ins, r=a_id, a=a_id, s="pending")        # self CHECK: (a,a) rejected


# ---- 8. deliberate-share feed — the FK cascade + exactly-one CHECK on PG (social sub-stage 2a) -----

def test_shared_posts_pg_dialect(pg):
    """PG echo (like the friendships coverage): the share ROUTES round-trip on Postgres, the exactly-one
    XOR CHECK rejects both/neither, and — the integrity proof — deleting a cook_log row CASCADES its
    shared_post on PG (the constraint + cascade Alembic autogenerate wouldn't reliably emit)."""
    a_id = harness.ensure_test_user()
    ca = pg.client

    # a cook -> a share, via the routes
    ca.post("/api/recipes/gai-yang/cooked", json={})
    clid = _count(pg.engine, "SELECT id FROM cook_log WHERE recipe_id='gai-yang' AND user_id=:u", u=a_id)
    pid = ca.post("/api/shares", json={"cook_log_id": clid, "caption": "pg"}).get_json()["id"]
    assert _count(pg.engine, "SELECT COUNT(*) FROM shared_posts WHERE id=:p", p=pid) == 1

    # exactly-one XOR CHECK: both targets and neither target are rejected
    ins = "INSERT INTO shared_posts (user_id, cook_log_id, recipe_id, caption, created_at) VALUES (:u,:c,:r,'x','t')"
    _expect_error(pg.engine, ins, u=a_id, c=clid, r="gai-yang")       # both set -> CHECK rejects
    _expect_error(pg.engine, ins, u=a_id, c=None, r=None)             # neither set -> CHECK rejects

    # ON DELETE CASCADE: undo the cook (route) -> the shared_post cascades away on PG
    assert ca.post("/api/recipes/gai-yang/uncook").status_code == 200
    assert _count(pg.engine, "SELECT COUNT(*) FROM shared_posts WHERE id=:p", p=pid) == 0


# ---- 9. comments — friends-only authz + the 2-level cascade (recipe -> post -> comment) on PG ------

def test_comments_pg_dialect(pg):
    """PG echo: the comment ROUTES round-trip on Postgres, friends-only authz holds (a non-friend 404s),
    and the 2-level cascade fires on PG — deleting the RECIPE removes the shared_post AND its comments."""
    a_id = harness.ensure_test_user()
    b_id = harness.ensure_test_user(email="commb@test.local")
    ca = pg.client
    cb = app.app.test_client()
    harness.login_test_client(cb, b_id)
    a_email = harness.HARNESS_USER_EMAIL
    # friend A<->B, A shares a recipe A owns
    ca.post("/api/friends/requests", json={"email": "commb@test.local"})
    cb.post("/api/friends/accept", json={"email": a_email})
    rid = ca.post("/api/recipes", json={"name": "PG Comment Dish", "ingredients": [{"qty": "1", "text": "x"}],
                                        "steps": ["go"]}).get_json()["id"]
    pid = ca.post("/api/shares", json={"recipe_id": rid}).get_json()["id"]

    # friend B can comment; a non-friend can't (fresh 3rd user)
    assert cb.post(f"/api/posts/{pid}/comments", json={"body": "great on PG"}).status_code == 201
    c_id = harness.ensure_test_user(email="commc@test.local")
    cc = app.app.test_client(); harness.login_test_client(cc, c_id)
    assert cc.post(f"/api/posts/{pid}/comments", json={"body": "sneaky"}).status_code == 404
    assert _count(pg.engine, "SELECT COUNT(*) FROM comments WHERE post_id=:p", p=pid) == 1

    # ⭐ 2-level cascade on PG: delete the recipe -> shared_post -> comments
    assert ca.delete(f"/api/recipes/{rid}").status_code == 200
    assert _count(pg.engine, "SELECT COUNT(*) FROM shared_posts WHERE id=:p", p=pid) == 0
    assert _count(pg.engine, "SELECT COUNT(*) FROM comments WHERE post_id=:p", p=pid) == 0


# ---- 10. cook-photo album STORED position ordering (3d-i) — NULLs-last differs SQLite<->PG ---------

def test_cook_photo_album_orders_by_position_nulls_last(pg):
    """The album payload orders by cook_photos.position (3d-i, migration 027 via `alembic upgrade head`),
    with a not-yet-seeded NULL position sorting LAST. PG sorts NULLs last by default and SQLite first, so
    this pins the portable `position IS NULL` construct on the PG dialect (and that the ADD COLUMN ran)."""
    uid = harness.ensure_test_user()          # pg.client's user
    rid = "gai-yang"                           # a seeded recipe; reset_and_seed leaves it photo-less
    rows = [("images/cooks/pgp0.jpg", 2), ("images/cooks/pgp1.jpg", 0),
            ("images/cooks/pgp2.jpg", 1), ("images/cooks/pgpN.jpg", None)]
    ids = {}
    with pg.engine.begin() as conn:
        for path, pos in rows:
            ids[path] = conn.execute(text(
                "INSERT INTO cook_photos (recipe_id, user_id, path, added_at, position) "
                "VALUES (:r, :u, :p, :t, :pos) RETURNING id"),
                {"r": rid, "u": uid, "p": path, "t": "2024-01-01T00:00Z", "pos": pos}).scalar_one()
    order = [p["id"] for p in pg.client.get(f"/api/recipes/{rid}").get_json()["photos"]]
    assert order == [ids["images/cooks/pgp1.jpg"], ids["images/cooks/pgp2.jpg"],
                     ids["images/cooks/pgp0.jpg"], ids["images/cooks/pgpN.jpg"]]   # 0,1,2 then NULL last


# ---- 11. change-tracking: recipe_snapshots — O-a original-capture + cook-capture + FK cascade on PG --

def test_recipe_snapshot_captured_on_cook_and_cascades_pg(pg):
    """Exercises migration 028 (the ADD TABLE via `alembic upgrade head`) on PG + BOTH capture paths:
    O-a's reason='original' baseline written at CREATE, and the reason='cook' capture on cook. Then that
    undoing the cook cascade-removes ONLY the cook snapshot (FK ON DELETE CASCADE, PG-native) while the
    cook-less original SURVIVES."""
    c = pg.client
    rid = c.post("/api/recipes", json={"name": "PG Snapshot", "is_test": True,
                 "ingredients": [{"qty": "1", "text": "flour"}], "steps": ["mix"]}).get_json()["id"]
    # O-a: create wrote a cook-less reason='original' baseline (the original-capture insert, on PG)
    assert _count(pg.engine,
                  "SELECT COUNT(*) FROM recipe_snapshots WHERE recipe_id=:r AND reason='original' AND cook_log_id IS NULL",
                  r=rid) == 1
    clid = c.post(f"/api/recipes/{rid}/cooked", json={}).get_json()["cook_log_id"]
    assert _count(pg.engine,
                  "SELECT COUNT(*) FROM recipe_snapshots WHERE recipe_id=:r AND cook_log_id=:c AND reason='cook'",
                  r=rid, c=clid) == 1
    assert c.post(f"/api/recipes/{rid}/uncook").status_code == 200
    assert _count(pg.engine,   # the cook snapshot cascaded away with cook_log; the original remains
                  "SELECT COUNT(*) FROM recipe_snapshots WHERE recipe_id=:r AND reason='cook'", r=rid) == 0
    assert _count(pg.engine,
                  "SELECT COUNT(*) FROM recipe_snapshots WHERE recipe_id=:r AND reason='original'", r=rid) == 1
