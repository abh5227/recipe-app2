#!/usr/bin/env python3
"""seed_made_cooks.py — one-off backfill: seed a provisional cook for each Paprika "Made"-tagged
recipe that has no cook yet, dated from its Paprika 'created' date.

Why: the Paprika "Made" tag was the manual cook-tracking workaround; those recipes were cooked but
carry no cook_log entry. Each gets ONE cook_log row marked source='paprika-import' (provisional) so
it reads as cooked. The date is the recipe's Paprika 'created' timestamp (a real date, but a
stand-in for the true cook date — to be corrected later from photos, then flipped to source='app').

Guarded + idempotent: a row is inserted only if the recipe EXISTS and has no existing
'paprika-import' cook, so re-running is safe and bulgogi-bowls (real cooks) + every other recipe are
left untouched. Requires migration 014 (the cook_log.source column).

Run:   python3 scripts/seed_made_cooks.py --dry-run    # show what would happen; writes nothing
       python3 scripts/seed_made_cooks.py              # actually seed
"""
import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "recipes.db"
SOURCE = "paprika-import"

# recipe_id -> Paprika 'created' DATE (date part of the source timestamp; cook_log stores YYYY-MM-DD).
SEEDS = [
    ("brownies",                                   "2025-11-23"),
    ("chicken-pepperoni",                          "2024-12-01"),
    ("chicken-tikka-masala",                       "2024-10-25"),
    ("homemade-pasta-dough",                       "2024-11-16"),
    ("hummus",                                     "2026-01-25"),
    ("king-arthur-s-original-cake-pan-cake",       "2025-08-20"),
    ("prego-rolls-steak-and-piri-piri-sandwiches", "2024-10-25"),
    ("sarma-hot-honey-cornbread",                  "2026-01-10"),
    ("thai-tea-ice-cream-chatramues-thai-tea",     "2025-08-19"),
]


def main():
    ap = argparse.ArgumentParser(description="Seed provisional cooks from the Paprika 'Made' tag.")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen; write nothing")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    seeded, skipped = [], []
    try:
        for rid, date in SEEDS:
            if conn.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone() is None:
                skipped.append((rid, "recipe not found"))
                continue
            if conn.execute(
                "SELECT 1 FROM cook_log WHERE recipe_id = ? AND source = ?", (rid, SOURCE)
            ).fetchone() is not None:
                skipped.append((rid, "already has a paprika-import cook"))
                continue
            if not args.dry_run:
                conn.execute(
                    "INSERT INTO cook_log (recipe_id, cooked_on, source) VALUES (?, ?, ?)",
                    (rid, date, SOURCE),
                )
            seeded.append((rid, date))
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"=== {'DRY-RUN (no writes)' if args.dry_run else 'SEEDED'} ===")
    print(f"seeded {len(seeded)}, skipped {len(skipped)}")
    for rid, date in seeded:
        print(f"  + {rid}  ->  {date}  (source={SOURCE})")
    for rid, why in skipped:
        print(f"  . {rid}  skipped: {why}")


if __name__ == "__main__":
    main()
