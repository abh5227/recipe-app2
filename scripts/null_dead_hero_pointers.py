#!/usr/bin/env python3
"""null_dead_hero_pointers.py — one-off data fix: NULL recipes.image for the 5 former-seed recipes whose
image points at a JPG that was never shipped (aloo-gobhi, bulgogi-bowls, gai-yang, mussakhan,
no-knead-bread). Their image column reads 'images/<slug>.jpg' but the file is absent, so dishPhoto
(app.js) takes the FILLED branch, the <img> 404s, and its onerror deletes the whole hero Polaroid — no
blank uploadable slot appears. NULLing the dead pointer routes them to the working blank-uploadable
Polaroid (the image-falsy+editable branch), so a photo can be uploaded.

Targets the KNOWN 5 explicitly (never a blanket "file missing" scan — can't touch anything unexpected),
and — belt-and-suspenders — only NULLs a target whose file is TRULY missing on disk (so if someone later
ships the real JPG, this won't clobber a now-valid pointer). Pure data: image col -> NULL for <=5 rows.
No schema, no migration.

This is a DATA-TRANSFORMING step, so — like scripts/backfill_cook_photo_position.py — it gets the full
gate: backup -> dry-run -> review -> apply. Idempotent: a target already NULL (or with a present file) is
skipped, so a second run is a no-op.

Run FIRST:  python3 backup.py                                       # snapshot recipes.db (safety)
Then:       python3 scripts/null_dead_hero_pointers.py --dry-run    # report what it would NULL; write nothing
            python3 scripts/null_dead_hero_pointers.py              # apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "recipes.db"

# The 5 former-seed recipes with dead image pointers (diagnosed: image set, file missing). Explicit —
# never a blanket scan. image = 'images/<slug>.jpg' -> served from static/images/<slug>.jpg.
TARGETS = ("aloo-gobhi", "bulgogi-bowls", "gai-yang", "mussakhan", "no-knead-bread")


def _file_present(image):
    """True iff the recipe's image path resolves to a real file (image is 'images/<slug>.jpg' under static/)."""
    return bool(image) and (BASE_DIR / "static" / image).is_file()


def null_dead_pointers(dry_run=False):
    if not DB.exists():
        sys.exit(f"No database: {DB} (run build_db.py first)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    plan = []      # rows we WILL null: (id, name, image)
    skipped = []   # (id, reason) — already null, or file actually present, or row absent
    for rid in TARGETS:
        row = conn.execute("SELECT id, name, image FROM recipes WHERE id = ?", (rid,)).fetchone()
        if row is None:
            skipped.append((rid, "no such recipe"))
        elif row["image"] is None or row["image"] == "":
            skipped.append((rid, "image already NULL/empty"))
        elif _file_present(row["image"]):
            skipped.append((rid, f"file PRESENT ({row['image']}) — pointer valid, left as-is"))
        else:
            plan.append((row["id"], row["name"], row["image"]))

    if not dry_run and plan:
        conn.executemany("UPDATE recipes SET image = NULL WHERE id = ?", [(pid,) for pid, _n, _i in plan])
        conn.commit()
    conn.close()

    print(f"{'DRY-RUN — ' if dry_run else ''}NULL dead hero-photo pointers: "
          f"{len(plan)} row(s) to clear, {len(skipped)} skipped.")
    for pid, name, image in plan:
        print(f"  NULL  {pid:16s} {name!r:38s} was image={image!r}")
    for rid, reason in skipped:
        print(f"  skip  {rid:16s} ({reason})")
    if not plan:
        print("  (nothing to do — idempotent no-op)")
    return plan


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report what it would NULL; write nothing")
    args = ap.parse_args()
    null_dead_pointers(dry_run=args.dry_run)
