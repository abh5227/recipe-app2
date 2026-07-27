#!/usr/bin/env python3
"""backfill_recipe_queue.py — one-off DATA-TRANSFORMING backfill: promote the latent, GLOBAL "To Make"
category tag into the PER-USER recipe_queue table (migration 024).

Two coupled moves, per recipe whose ·-delimited `category` carries the exact element "To Make":
  (1) INSERT a recipe_queue row  (user_id = the recipe's OWNER, recipe_id = the recipe id, added_at = now)
  (2) STRIP the "To Make" element out of that recipe's category string, rejoining with " · " so no
      leading/trailing/doubled delimiter is left; a category left EMPTY becomes NULL (the repo's
      empty-category convention — see import_write / test_import_write.py::test_plan_category_none_when_empty).

Why standalone (not in the SQL migration): migrate.py runs executescript, which can't do an element-wise
string strip. This mirrors scripts/backfill_qty_unit.py — the repo's other data-transforming backfill.

ELEMENT-WISE, EXACT match: "To Make" is stripped only when it is a whole ·-delimited element, never as a
substring inside a longer tag. (Verified: all 133 rows carry it as an exact element; 0 inside a longer tag.)

PER-USER owner: the queue is per-user, so user_id = each recipe's own `owner` (132 belong to user 1, 1 to
user 2 — NOT all user 1). A recipe with a NULL owner cannot get a per-user queue entry; such a row is
SKIPPED ENTIRELY (tag left intact) and reported, never half-transformed. (Verified: 0 NULL owners today.)

IDEMPOTENT — re-running --apply is a clean no-op. Both halves are independently guarded:
  - queue insert  : skipped if a (user_id, recipe_id) row already exists (also blocked by the UNIQUE);
  - category strip : only rows whose category STILL contains the "To Make" element are selected.

SAFE-BY-DEFAULT: dry-run is the DEFAULT (reports, writes nothing); pass --apply to write. (This inverts
backfill_qty_unit.py's real-run-default; deliberate, because this rewrites LIVE source='app' rows.)

Run FIRST:  python3 backup.py                              # snapshot recipes.db (safety)
Then:       python3 scripts/backfill_recipe_queue.py            # DRY-RUN: report, write nothing
            python3 scripts/backfill_recipe_queue.py --apply    # write recipe_queue rows + strip tags
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "recipes.db"

TAG = "To Make"          # the exact ·-delimited element to promote out of category
SEP = "·"           # "·" middot — the category delimiter
JOIN = " · "        # " · " — how the editor (app.js addTag) rejoins elements


def now_utc():
    """Mirror app.py::now_utc() so added_at matches shared_posts/friendships timestamp text exactly."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _elements(category):
    """Split a category string into trimmed, non-empty ·-delimited elements (the app.js catTags rule)."""
    return [t.strip() for t in (category or "").split(SEP) if t.strip()]


def _strip_tag(category):
    """Return the category with the exact TAG element removed and rejoined; None if nothing remains.
    Element-wise (never substring) — a tag that merely CONTAINS 'to make' text is left untouched."""
    kept = [e for e in _elements(category) if e != TAG]
    return JOIN.join(kept) if kept else None


def backfill(db=DB, apply=False):
    if not Path(db).exists():
        sys.exit(f"No database: {db} (run build_db.py first)")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # Candidates: rows that still carry the exact "To Make" element (LIKE is a coarse prefilter; the
    # element check is authoritative, so a substring-only hit is correctly excluded).
    rows = conn.execute(
        "SELECT id, name, category, owner FROM recipes WHERE category LIKE ?", (f"%{TAG}%",)
    ).fetchall()
    candidates = [r for r in rows if TAG in _elements(r["category"])]

    to_insert = 0        # queue rows that would be inserted (not already present)
    to_rewrite = 0       # category strings that would be rewritten
    already_queued = 0   # (user, recipe) already in queue -> insert skipped
    null_owner_skip = 0  # can't scope to a user -> row skipped entirely (tag kept)
    examples = []
    now = now_utc()

    for r in candidates:
        if r["owner"] is None:
            null_owner_skip += 1
            continue

        exists = conn.execute(
            "SELECT 1 FROM recipe_queue WHERE user_id = ? AND recipe_id = ?", (r["owner"], r["id"])
        ).fetchone()
        if exists:
            already_queued += 1
        else:
            to_insert += 1
            if apply:
                conn.execute(
                    "INSERT INTO recipe_queue (user_id, recipe_id, added_at) VALUES (?, ?, ?)",
                    (r["owner"], r["id"], now),
                )

        new_cat = _strip_tag(r["category"])
        to_rewrite += 1
        if len(examples) < 6:
            examples.append((r["id"], r["category"], new_cat, r["owner"]))
        if apply:
            conn.execute("UPDATE recipes SET category = ? WHERE id = ?", (new_cat, r["id"]))

    if apply:
        conn.commit()
    conn.close()

    tag_prefix = "" if apply else "DRY-RUN — "
    print(f"{tag_prefix}want-to-make backfill (exact '{TAG}' element -> recipe_queue):")
    print(f"  candidates (category has exact '{TAG}' element) : {len(candidates)}")
    print(f"  queue rows to insert (not already queued)        : {to_insert}")
    print(f"  category strings to rewrite                      : {to_rewrite}")
    print(f"  already-queued (insert skipped, idempotent)      : {already_queued}")
    print(f"  NULL-owner rows SKIPPED ENTIRELY (tag kept)      : {null_owner_skip}")
    if candidates:
        print("  before -> after category (up to 6; None = NULL empty category):")
        for rid, before, after, owner in examples:
            print(f"    [{rid}] owner={owner}: {before!r} -> {after!r}")
    else:
        print("  (nothing to do — no row carries the 'To Make' element; idempotent no-op)")
    return {
        "candidates": len(candidates), "inserted": to_insert, "rewritten": to_rewrite,
        "already_queued": already_queued, "null_owner_skip": null_owner_skip,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes; default is a dry-run that writes nothing")
    args = ap.parse_args()
    backfill(apply=args.apply)
