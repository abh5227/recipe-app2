#!/usr/bin/env python3
"""backfill_original_snapshots.py — one-off backfill for original-baseline capture (O-b). Every EXISTING
recipe that lacks a reason='original' snapshot gets one, capturing its CURRENT content as the baseline the
recipe-page annotations (O-c) diff future edits against — matching O-a, which captures a reason='original'
at birth for NEW recipes.

CURRENT-STATE baseline (NOT re-derived from the Paprika archive): the quality investigation found the raw
archive is ~85% systematic post-import noise (unit-abbrev, the qty/unit split, name->unit, heading
promotion, note extraction — all backfills the archive predates) and the 5 former-seed recipes' archive
uid is a dedup-TWIN lookalike, not their real original; the genuine historical signal was only ~11
recipes. So existing recipes get a clean current-state birth-baseline like O-a's new ones — annotations
accrue from FUTURE edits, and O-c needs NO field filtering (original == current => zero noise by
construction). The ~11 recipes' past hand-edits are lost AS annotations (already baked into current
content) — a bounded, accepted loss.

Reuses app.serialize_recipe_content (the O-a/stage-1 shared snapshot_serialize format), so a backfilled
original serializes IDENTICALLY to O-a's going-forward captures. Per recipe: content =
serialize_recipe_content(current rows), reason='original', cook_log_id=NULL, user_id = the recipe's OWNER,
created_at = the recipe's created_at (the original predates its cooks — chronology correct). Guarded
WHERE NOT EXISTS reason='original' => idempotent + skips any O-a already captured.

Operates on app.DB (recipes.db by default; tests redirect it via the kitchen fixture). DATA-TRANSFORMING,
so — like the other backfills — the full gate: backup -> dry-run -> review -> apply.

Run FIRST:  python3 backup.py
Then:       python3 scripts/backfill_original_snapshots.py --dry-run   # report the count; write nothing
            python3 scripts/backfill_original_snapshots.py             # apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root on path so `import app` works from scripts/

import app
from models import Recipe, RecipeSnapshot
from sqlalchemy import insert, select


def backfill(dry_run=False):
    with app.orm_session() as s:
        have = set(s.scalars(select(RecipeSnapshot.recipe_id).where(RecipeSnapshot.reason == "original")))
        rows = s.execute(select(Recipe.id, Recipe.owner, Recipe.created_at).order_by(Recipe.id)).all()
        plan, skipped = [], []
        for rid, owner, created_at in rows:
            if rid in have:
                continue                                   # already has an original (O-a or a prior run)
            if owner is None:
                skipped.append((rid, "owner IS NULL — recipe_snapshots.user_id is NOT NULL"))
                continue
            plan.append((rid, owner, created_at))
        if not dry_run:
            for rid, owner, created_at in plan:
                s.execute(insert(RecipeSnapshot.__table__).values(
                    recipe_id=rid, cook_log_id=None, user_id=owner, reason="original",
                    content=app.serialize_recipe_content(s, rid), created_at=created_at))
            s.commit()

    print(f"{'DRY-RUN — ' if dry_run else ''}backfill original snapshots: "
          f"{len(plan)} recipe(s) get a reason='original' baseline"
          f"{f', {len(skipped)} skipped' if skipped else ''}.")
    print(f"  ({len(have)} recipe(s) already had an original — skipped by the WHERE NOT EXISTS guard)")
    for rid, reason in skipped:
        print(f"  skip  {rid}  ({reason})")
    if not plan:
        print("  (nothing to do — every recipe already has an original; idempotent no-op)")
    return plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report the count; write nothing")
    args = ap.parse_args()
    backfill(dry_run=args.dry_run)
