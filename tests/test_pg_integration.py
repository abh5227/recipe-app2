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


def test_line_change_upsert_composite_key(pg):
    """ON CONFLICT(recipe_id, person_id, position) on the seed-gated change layer: edit in place, then remove."""
    c = pg.client
    pid = c.get("/api/people").get_json()[0]["id"]
    assert c.put(f"/api/recipes/gai-yang/people/{pid}/lines/0", json={"kind": "edit", "qty": "9 cups"}).status_code == 200
    c.put(f"/api/recipes/gai-yang/people/{pid}/lines/0", json={"kind": "edit", "qty": "10 cups"})   # re-edit
    changes = c.get("/api/recipes/gai-yang").get_json()["changes"][pid]
    assert changes["edits"]["0"] == "10 cups"                                   # updated in place
    assert _count(pg.engine,
                  "SELECT COUNT(*) FROM recipe_line_changes WHERE recipe_id='gai-yang' AND person_id=:p AND position=0",
                  p=pid) == 1                                                    # no duplicate
    c.put(f"/api/recipes/gai-yang/people/{pid}/lines/0", json={"kind": "remove"})
    changes = c.get("/api/recipes/gai-yang").get_json()["changes"][pid]
    assert 0 in changes["removes"] and "0" not in changes["edits"]              # remove branch


# ---- 2. LIST ORDERING (collation — differs SQLite↔PG) --------------------------------------------

def test_list_ordering_is_pg_collation(pg):
    """GET list endpoints return PG's native collation order (decision A). Pinned for recipes;
    for ingredients/people, assert the route order matches PG's own ORDER BY (route orders correctly)."""
    c = pg.client
    recs = [r["id"] for r in c.get("/api/recipes").get_json()]
    assert recs == EXPECTED_RECIPE_ORDER                                        # PG linguistic order (intended)
    with pg.engine.connect() as conn:
        db_recipes = [r[0] for r in conn.execute(text("SELECT id FROM recipes ORDER BY name"))]
        db_ings = [r[0] for r in conn.execute(text("SELECT id FROM ingredients ORDER BY name"))]
    assert recs == db_recipes                                                   # route == PG ORDER BY name
    ings = [i["id"] for i in c.get("/api/ingredients").get_json()]
    assert ings == db_ings and len(ings) == 36
    assert [p["id"] for p in c.get("/api/people").get_json()] == ["andy", "vedant"]


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
