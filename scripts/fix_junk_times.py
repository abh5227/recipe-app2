#!/usr/bin/env python3
"""fix_junk_times.py — one-off data fix: NULL the two stored times that are not times.

Found by measuring all 218 stored times while scoping the time normalizer
(previews/parser-library-scoping.md). 216 of them are durations. These two are not:

    toum                                       prep_time = '1 cup'
    chocolate-peanut-butter-banana-smoothie    cook_time = '0 mins'

'1 cup' is a volume sitting in a time column, almost certainly a mis-paste at the source.
'0 mins' is a number that reads as a measurement and means the field was never filled, and a
smoothie has no cook time to state.

⚠️ NULL, NOT A GUESS. Neither value can be recovered from anything in the database, so the honest
fix is to say nothing. normalize_time deliberately passes an unreadable value through exactly as
stored, which is why '1 cup' is visible on the page today rather than hidden, and that is what
made it findable. Blanking it there would have buried it. Fixing it here is a different act.

⚠️ EXACT-MATCH GUARDED AND THEREFORE IDEMPOTENT. Each row is touched only while it still holds the
exact junk string, so a second run finds nothing and a row edited by hand in the meantime is left
alone rather than overwritten.

Run FIRST:  python3 backup.py
Then:       python3 scripts/fix_junk_times.py --dry-run
            python3 scripts/fix_junk_times.py
"""
import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "recipes.db"

# (recipe_id, column, the exact value that may be cleared)
FIXES = (
    ("toum", "prep_time", "1 cup"),
    ("chocolate-peanut-butter-banana-smoothie", "cook_time", "0 mins"),
)


def plan(conn):
    """(to_clear, skipped) — skipped is a row whose value is no longer the junk string."""
    to_clear, skipped = [], []
    for rid, col, junk in FIXES:
        row = conn.execute(f"SELECT name, {col} FROM recipes WHERE id=?", (rid,)).fetchone()
        if row is None:
            skipped.append((rid, col, "no such recipe"))
        elif row[1] == junk:
            to_clear.append((rid, col, junk, row[0]))
        else:
            skipped.append((rid, col, f"holds {row[1]!r}, not {junk!r}"))
    return to_clear, skipped


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report and write nothing")
    args = ap.parse_args(argv[1:])

    conn = sqlite3.connect(DB)
    try:
        to_clear, skipped = plan(conn)
        print(f"to clear: {len(to_clear)}    skipped: {len(skipped)}")
        for rid, col, junk, name in to_clear:
            print(f"  {rid}  ({name})\n      {col}: {junk!r} -> NULL")
        for rid, col, why in skipped:
            print(f"  SKIP {rid} {col}: {why}")
        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0
        for rid, col, junk, _name in to_clear:
            conn.execute(f"UPDATE recipes SET {col}=NULL WHERE id=? AND {col}=?", (rid, junk))
        conn.commit()
        print(f"\ncleared {len(to_clear)} value(s)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
