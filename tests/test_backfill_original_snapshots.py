"""Original-baseline backfill (scripts/backfill_original_snapshots.py) — O-b's data-transforming step.
Pins: it captures each recipe's CURRENT content as a reason='original' snapshot (cook_log_id NULL,
user_id=owner, created_at=recipe.created_at); the backfilled original diffs to ZERO against current
(clean-by-construction — no false annotations); it's idempotent (WHERE NOT EXISTS reason='original'); and
it coexists with reason='cook' snapshots. Archive-free by design (the quality investigation)."""
import importlib.util
from pathlib import Path

import app
import harness
import snapshot_diff as sd

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "backfill_original_snapshots", REPO / "scripts" / "backfill_original_snapshots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                # uses app.orm_session() -> app.DB (redirected by kitchen)
    return mod


def _prep_owner(kitchen):
    # Fixture recipes seed without an owner (a fresh build has no user); the live corpus has owner set.
    # Give them one so the backfill (user_id is NOT NULL) targets them — mirroring the real state.
    uid = harness.ensure_test_user()
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET owner = ? WHERE owner IS NULL", (uid,))
        c.commit()
    return uid


def _some_recipe(kitchen):
    with kitchen.conn() as c:
        return c.execute("SELECT id, created_at FROM recipes ORDER BY id LIMIT 1").fetchone()


def _snaps(kitchen, rid, reason=None):
    q = "SELECT cook_log_id, user_id, reason, content, created_at FROM recipe_snapshots WHERE recipe_id = ?"
    args = [rid]
    if reason is not None:
        q += " AND reason = ?"
        args.append(reason)
    with kitchen.conn() as c:
        return c.execute(q + " ORDER BY reason", args).fetchall()


def test_backfills_original_field_correctness(kitchen):
    uid = _prep_owner(kitchen)
    row = _some_recipe(kitchen)
    rid = row["id"]
    _load().backfill(dry_run=False)
    snaps = _snaps(kitchen, rid, "original")
    assert len(snaps) == 1
    o = snaps[0]
    assert o["cook_log_id"] is None                     # cook-less baseline
    assert o["user_id"] == uid                          # = recipe.owner
    assert o["created_at"] == row["created_at"]         # created_at = recipe.created_at (predates cooks)
    with app.orm_session() as s:
        assert o["content"] == app.serialize_recipe_content(s, rid)   # the CURRENT content


def test_original_diffs_to_zero(kitchen):
    _prep_owner(kitchen)
    rid = _some_recipe(kitchen)["id"]
    _load().backfill(dry_run=False)
    original = _snaps(kitchen, rid, "original")[0]["content"]
    with app.orm_session() as s:
        current = app.serialize_recipe_content(s, rid)
    assert sd.diff_snapshots(original, current) == []   # clean-by-construction: no annotations until an edit


def test_idempotent(kitchen):
    _prep_owner(kitchen)
    mod = _load()
    first = mod.backfill(dry_run=False)
    assert len(first) > 0
    with kitchen.conn() as c:
        n1 = c.execute("SELECT COUNT(*) FROM recipe_snapshots WHERE reason='original'").fetchone()[0]
    second = mod.backfill(dry_run=False)
    assert second == []                                 # WHERE NOT EXISTS -> nothing left to add
    with kitchen.conn() as c:
        n2 = c.execute("SELECT COUNT(*) FROM recipe_snapshots WHERE reason='original'").fetchone()[0]
    assert n1 == n2                                      # no duplicates on re-run


def test_coexists_with_cook_snapshot(kitchen):
    _prep_owner(kitchen)
    rid = _some_recipe(kitchen)["id"]
    kitchen.client.post(f"/api/recipes/{rid}/cooked", json={})   # writes a reason='cook' snapshot
    _load().backfill(dry_run=False)
    reasons = [r["reason"] for r in _snaps(kitchen, rid)]         # ordered by reason
    assert reasons == ["cook", "original"]              # both coexist for one recipe
