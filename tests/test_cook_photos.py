"""cook_photos album (Stage 4, build 1 — SCHEMA foundation): the cook_photos table + CookPhoto ORM model.

No endpoints / UI / save_cook_photo helper yet (that's build 2), so rows are inserted directly via
app.orm_session() to prove the FOUNDATION: the migration creates the table, the model round-trips
(caption nullable — one row with a caption, one without), and the FKs hold (a row references a real
cook_log + recipe + user; a dangling FK is rejected). Recipe + cook state is set up through the REAL
endpoints (POST /api/recipes, POST /cooked) so the FK targets are genuine rows, not raw inserts.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest                              # noqa: E402
from sqlalchemy import inspect, select     # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import app                                 # noqa: E402
import harness                             # noqa: E402
from models import CookLog, CookPhoto      # noqa: E402


def _own_recipe(client, name="Album Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _log_cook(client, rid):
    """Log a cook via the REAL endpoint, then return the new cook_log id (newest for this recipe)."""
    assert client.post(f"/api/recipes/{rid}/cooked", json={}).status_code == 200
    with app.orm_session() as s:
        return s.execute(
            select(CookLog.id).where(CookLog.recipe_id == rid).order_by(CookLog.id.desc()).limit(1)
        ).scalar_one()


def _add_photo(cook_log_id, recipe_id, user_id, path, caption=None):
    """Insert a CookPhoto through the ORM (no endpoint yet) and return its id."""
    with app.orm_session() as s:
        p = CookPhoto(cook_log_id=cook_log_id, recipe_id=recipe_id, user_id=user_id,
                      path=path, caption=caption, added_at=app.now_utc())
        s.add(p)
        s.commit()
        return p.id


# ---- migration applies: the table + columns + indexes exist ---------------------------------------

def test_migration_creates_cook_photos_table(kitchen):
    with app.orm_session() as s:
        insp = inspect(s.get_bind())
        assert "cook_photos" in insp.get_table_names()             # migration 025 applied by build_db
        cols = {c["name"] for c in insp.get_columns("cook_photos")}
        assert cols == {"id", "cook_log_id", "recipe_id", "user_id", "path", "caption", "added_at"}
        idx = {i["name"] for i in insp.get_indexes("cook_photos")}
        assert "idx_cook_photos_recipe" in idx                      # per-recipe album query
        assert "idx_cook_photos_cook_log" in idx                    # per-cook lookup


# ---- model round-trips: caption nullable (with + without) -----------------------------------------

def test_cook_photo_round_trips_with_and_without_caption(kitchen):
    a = kitchen.client
    uid = harness.ensure_test_user()
    rid = _own_recipe(a, "Round Trip Dish")
    clid = _log_cook(a, rid)

    with_cap = _add_photo(clid, rid, uid, "images/cooks/1.jpg", caption="golden crust")
    no_cap = _add_photo(clid, rid, uid, "images/cooks/2.jpg")   # caption omitted -> NULL

    with app.orm_session() as s:
        p1 = s.get(CookPhoto, with_cap)
        p2 = s.get(CookPhoto, no_cap)

    assert (p1.cook_log_id, p1.recipe_id, p1.user_id, p1.path, p1.caption) == \
        (clid, rid, uid, "images/cooks/1.jpg", "golden crust")
    assert p1.added_at                                             # stamped from now_utc()
    assert p2.caption is None                                      # nullable round-trips as NULL
    assert p2.path == "images/cooks/2.jpg"


# ---- FKs hold: reference real rows; a dangling FK is rejected -------------------------------------

def test_cook_photo_fks_reference_real_rows(kitchen):
    a = kitchen.client
    uid = harness.ensure_test_user()
    rid = _own_recipe(a, "FK Dish")
    clid = _log_cook(a, rid)
    pid = _add_photo(clid, rid, uid, "images/cooks/3.jpg")

    with kitchen.conn() as c:
        row = c.execute(
            """SELECT cl.id AS cook, r.id AS recipe, u.id AS usr
               FROM cook_photos cp
               JOIN cook_log cl ON cl.id = cp.cook_log_id
               JOIN recipes  r  ON r.id  = cp.recipe_id
               JOIN users    u  ON u.id  = cp.user_id
               WHERE cp.id = ?""",
            (pid,),
        ).fetchone()
    assert row["cook"] == clid and row["recipe"] == rid and row["usr"] == uid


def test_cook_photo_dangling_cook_log_fk_rejected(kitchen):
    # FK enforcement is ON (orm_session registers PRAGMA foreign_keys=ON for SQLite; PG always enforces),
    # so a photo pointing at a non-existent cook_log can never be written.
    a = kitchen.client
    uid = harness.ensure_test_user()
    rid = _own_recipe(a, "Bad FK Dish")
    with pytest.raises(IntegrityError):
        _add_photo(999999, rid, uid, "images/cooks/x.jpg")   # no such cook_log row
