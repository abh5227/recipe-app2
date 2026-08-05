#!/usr/bin/env python3
"""backfill_hero_album_rows.py — one-off backfill for the hero↔album unification (Stage 2). Every
existing HERO-ONLY recipe (recipes.image set, but NO cook_photos row pointing at that path) gets a
cook-less cook_photos row for its hero, so the existing hero joins the album — matching Stage 1, where a
newly UPLOADED hero already becomes a cook-less album row + is promoted ("a photo is a photo").

Targets recipes WHERE image IS NOT NULL/'' AND NOT EXISTS a cook_photos row with path == recipes.image.
This auto-skips (a) the already-consistent PROMOTED hero (its row exists) and (b) any Stage-1 uploaded
hero (already an album row) — so it's the ~121 legacy/import + direct-upload-pre-Stage-1 heroes. Files
are NOT touched: the album row points at the hero's EXISTING path (slug-flat images/<slug>.jpg for
imports; uuid for Stage-1 uploads) — slug-flat heroes and uuid uploads coexist fine. Inserts:
cook_log_id=NULL (cook-less), user_id=recipes.owner, path=recipes.image, caption=NULL,
position=max(position)+1 for that recipe (append), added_at=now (UTC, matching app.now_utc()).

DATA-TRANSFORMING (writes new cook_photos rows), so — like scripts/backfill_cook_photo_position.py — it
gets the full gate: backup → dry-run → review → apply. Idempotent: the NOT-EXISTS guard means a second
run finds nothing (a re-inserted row would already satisfy path==image → skipped).

Run FIRST:  python3 backup.py                                       # snapshot recipes.db (safety)
Then:       python3 scripts/backfill_hero_album_rows.py --dry-run   # report the recipes it would add rows for; write nothing
            python3 scripts/backfill_hero_album_rows.py             # apply
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "recipes.db"


def _now_utc():
    # Mirror app.now_utc(): second-precision UTC 'YYYY-MM-DD HH:MM:SS' (cook_photos.added_at shape).
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def backfill(dry_run=False):
    if not DB.exists():
        sys.exit(f"No database: {DB} (run build_db.py first)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Hero-only recipes: image set, but no cook_photos row already points at that path. Auto-skips the
    # promoted hero (row exists) and Stage-1 uploads (album row exists). Deterministic order for review.
    targets = conn.execute(
        """
        SELECT r.id, r.name, r.owner, r.image
          FROM recipes r
         WHERE r.image IS NOT NULL AND r.image != ''
           AND NOT EXISTS (
               SELECT 1 FROM cook_photos cp
                WHERE cp.recipe_id = r.id AND cp.path = r.image
           )
         ORDER BY r.id
        """
    ).fetchall()

    now = _now_utc()
    plan = []          # (id, name, owner, image, position)
    skipped_no_owner = []
    for t in targets:
        if t["owner"] is None:                             # owner NOT NULL is required by cook_photos.user_id
            skipped_no_owner.append(t["id"])
            continue
        next_pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM cook_photos WHERE recipe_id = ?", (t["id"],)
        ).fetchone()[0]
        plan.append((t["id"], t["name"], t["owner"], t["image"], next_pos))

    if not dry_run and plan:
        conn.executemany(
            "INSERT INTO cook_photos (cook_log_id, recipe_id, user_id, path, caption, added_at, position) "
            "VALUES (NULL, ?, ?, ?, NULL, ?, ?)",
            [(rid, owner, image, now, pos) for rid, _name, owner, image, pos in plan],
        )
        conn.commit()
    conn.close()

    print(f"{'DRY-RUN — ' if dry_run else ''}backfill hero album rows: "
          f"{len(plan)} recipe(s) get a cook-less hero album row"
          f"{f', {len(skipped_no_owner)} skipped (no owner)' if skipped_no_owner else ''}.")
    for rid, name, owner, image, pos in plan:
        print(f"  + {rid:24s} owner={owner} pos={pos}  {image}   ({name})")
    if skipped_no_owner:
        print("  skipped (owner IS NULL — cook_photos.user_id is NOT NULL):")
        for rid in skipped_no_owner:
            print(f"      {rid}")
    if not plan:
        print("  (nothing to do — every hero already has a matching album row; idempotent no-op)")
    return plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report what it would insert; write nothing")
    args = ap.parse_args()
    backfill(dry_run=args.dry_run)
