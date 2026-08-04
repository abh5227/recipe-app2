#!/usr/bin/env python3
"""backfill_cook_photo_position.py — one-off backfill: seed cook_photos.position (migration 027) for
existing rows from the album's CURRENT display order, so the album looks IDENTICAL after 3d-i switches the
payload to ORDER BY position (Model B: cooked_on SEEDS the stored order, which then takes over once dragged).

Per recipe, assigns position 0,1,2,… to that recipe's photos in the SAME order the album shows today — the
3a construction: cook-linked newest-first (cooked_on desc), undated/standalone last (added_at desc, id desc).
So position 0 = the photo currently shown first.

This is a DATA-TRANSFORMING step (it writes existing cook_photos rows), so — like scripts/backfill_qty_unit.py
— it lives OUTSIDE migrate.py (executescript can't do the per-recipe windowed ordering) and gets the full
gate: backup → dry-run → review → apply. Guarded + idempotent: only rows WHERE position IS NULL are touched,
sequenced per recipe CONTINUING from that recipe's current max — so a second run finds nothing (a no-op) and
it never renumbers a row that already has a position (a dragged/appended order is never disturbed).

Run FIRST:  python3 backup.py                                          # snapshot recipes.db (safety)
Then:       python3 scripts/backfill_cook_photo_position.py --dry-run  # report id->position, write nothing
            python3 scripts/backfill_cook_photo_position.py            # write position
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "recipes.db"

# The album's CURRENT display order (3a), kept in ONE place so the seed matches the payload exactly:
# cook-linked newest-first, undated/standalone last. `(cl.cooked_on IS NULL) ASC` pushes undated last portably.
DISPLAY_ORDER = "ORDER BY (cl.cooked_on IS NULL) ASC, cl.cooked_on DESC, cp.added_at DESC, cp.id DESC"


def backfill(dry_run=False):
    if not DB.exists():
        sys.exit(f"No database: {DB} (run build_db.py first)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Recipes that still have any NULL-position photo (the idempotent guard: none after a clean run).
    recipes = [r["recipe_id"] for r in conn.execute(
        "SELECT DISTINCT recipe_id FROM cook_photos WHERE position IS NULL ORDER BY recipe_id"
    ).fetchall()]

    plan = []   # [(recipe_id, [(photo_id, position), ...]), ...]
    for rid in recipes:
        base = conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM cook_photos WHERE recipe_id = ? AND position IS NOT NULL",
            (rid,),
        ).fetchone()[0]
        nulls = conn.execute(
            "SELECT cp.id FROM cook_photos cp "
            "LEFT JOIN cook_log cl ON cl.id = cp.cook_log_id "
            f"WHERE cp.recipe_id = ? AND cp.position IS NULL {DISPLAY_ORDER}",
            (rid,),
        ).fetchall()
        plan.append((rid, [(row["id"], base + 1 + i) for i, row in enumerate(nulls)]))

    if not dry_run:
        for _rid, mapping in plan:
            conn.executemany(
                "UPDATE cook_photos SET position = ? WHERE id = ?",
                [(pos, pid) for pid, pos in mapping],
            )
        conn.commit()
    conn.close()

    total = sum(len(m) for _rid, m in plan)
    print(f"{'DRY-RUN — ' if dry_run else ''}seeded position for {total} cook_photos row(s) "
          f"across {len(recipes)} recipe(s):")
    for rid, mapping in plan:
        pairs = ", ".join(f"#{pid}->{pos}" for pid, pos in mapping)
        print(f"  {rid}: {pairs}")
    if total == 0:
        print("  (nothing to do — every cook_photos row already has a position; idempotent no-op)")
    return plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report id->position; write nothing")
    args = ap.parse_args()
    backfill(dry_run=args.dry_run)
