#!/usr/bin/env python3
"""backfill_count_noun_units.py — one-off backfill: re-split stored ingredient rows now that a
counting noun beside an ingredient is read as the unit ("1 clove garlic" -> clove + garlic).

The qty/unit/name split is STORED, so the parser fix reaches NEW imports only. Existing rows keep
whatever the parser produced when they were written. This re-derives the split from `raw_text`.

⚠️ IT ONLY TOUCHES ROWS IT CAN PROVE ARE PARSER-DERIVED, and that guard is the whole design.
A row is eligible only when its stored (qty, quantity, unit, label) is EXACTLY what the PREVIOUS
parser produces from its own raw_text. Two things make that necessary:

  - The editor writes the split directly. static/app.js has a `unit` field and app._row_qty_parts
    treats explicit parts as authoritative, so a hand-edited split is real user data. It does not
    match the old parser's output, so it is skipped.
  - raw_text is NOT always the original line. app.write_recipe_rows rebuilds it as
    "{qty} {label}{note}" on every edit, and Paprika rows never had the amount in it. Measured:
    321 rows carry a stored quantity their raw_text does not contain, so re-parsing those would
    silently delete the count. They fail the same eligibility test and are skipped.

raw_text is never written. `quantity` is asserted unchanged on every row, so a count can never move.
A change is refused unless it is exactly a counting-noun lift (old unit empty, new unit a count
noun), so parser drift since those rows were written would stop the run rather than mass-rewrite.

Idempotent by construction: once a row is re-split, its stored value no longer matches the OLD
parser, so a second run skips it. Verified — the second run reports 0.

Applied 2026-09-23 against recipes.db 40d3d0f0: 79 rows over two passes (73, then 6 more after the
lift was moved after the gram-paren strip), 0 rows changed for any other reason.

Run FIRST:  python3 backup.py
Then:       python3 scripts/backfill_count_noun_units.py --dry-run
            python3 scripts/backfill_count_noun_units.py
"""
import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import import_cleanup                                             # noqa: E402
import import_write                                               # noqa: E402

DB = REPO / "recipes.db"


def columns_for(raw, parser=import_cleanup):
    """The four columns import_write would write for this line. None when it reads as a section."""
    line = parser.classify_line(raw, set())
    if line["kind"] == "section":
        return None
    return (import_write._qty_text(line), line.get("amount") or "",
            line.get("unit") or "", line["name"] or None)


def plan(conn, previous):
    """(updates, skipped) — `previous` is the pre-fix parser module, for the eligibility test."""
    rows = conn.execute("""SELECT id, qty, quantity, unit, label, raw_text FROM recipe_ingredients
                            WHERE is_heading=0 AND raw_text IS NOT NULL AND raw_text<>''""").fetchall()
    updates, skipped = [], 0
    for rid, qty, quantity, unit, label, raw in rows:
        old = columns_for(raw, previous)
        if old is None or (qty or "", quantity or "", unit or "", label) != \
                (old[0] or "", old[1], old[2], old[3]):
            skipped += 1                                          # hand-edited, or raw_text is not the line
            continue
        new = columns_for(raw)
        if new == old:
            continue
        if not (old[2] == "" and new[2].lower() in import_cleanup._COUNT_NOUNS):
            raise SystemExit(f"REFUSING: not a counting-noun lift -> {raw!r}\n  {old}\n  {new}")
        if new[1] != old[1]:
            raise SystemExit(f"REFUSING: the amount moved -> {raw!r}\n  {old}\n  {new}")
        updates.append((new[0], new[1], new[2], new[3], rid, raw, old))
    return updates, skipped


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report and write nothing")
    ap.add_argument("--previous", default=None,
                    help="path to the pre-fix import_cleanup.py (the eligibility baseline)")
    args = ap.parse_args(argv[1:])

    if args.previous:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ic_previous", args.previous)
        previous = importlib.util.module_from_spec(spec)
        sys.modules["ic_previous"] = previous
        spec.loader.exec_module(previous)
    else:
        raise SystemExit("--previous is required: the eligibility test compares against the parser "
                         "that WROTE the stored rows, so it needs that exact file "
                         "(git show <sha>:import_cleanup.py > /tmp/prev.py)")

    conn = sqlite3.connect(DB)
    try:
        updates, skipped = plan(conn, previous)
        print(f"eligible-and-changed: {len(updates)}    skipped (not parser-derived): {skipped}")
        for _q, _quantity, u, lab, _rid, raw, old in updates:
            print(f"  {raw!r}\n     {old[2]!r} + {old[3]!r}  ->  {u!r} + {lab!r}")
        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0
        for q, quantity, u, lab, rid, _raw, _old in updates:
            conn.execute("UPDATE recipe_ingredients SET qty=?, quantity=?, unit=?, label=? WHERE id=?",
                         (q, quantity, u, lab, rid))
        conn.commit()
        print(f"\nwrote {len(updates)} rows; raw_text untouched")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
