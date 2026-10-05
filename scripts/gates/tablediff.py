#!/usr/bin/env python3
"""Compare two databases table by table, row for row, column for column.

    python3.13 scripts/gates/tablediff.py <a.db> <b.db>

Exit status is 0 when every table is identical and 1 otherwise. Both databases are opened read-only.

⚠️ STATED OVER THE TABLE, NOT OVER A LIST OF COLUMNS SOMEBODY REMEMBERED. The columns come from
PRAGMA table_info, so a column added tomorrow is compared without anyone editing this file. Every
hand-written column list in this repo has been short at least once, and `copy_recipe` dropped the
library linkage of 2,851 ingredient rows that way.

⚠️ AND OVER EVERY TABLE, NOT A CHOSEN LIST OF CONTENT TABLES. The version this grew from named
eleven. Run over the whole database instead, it answered a question the eleven could not: after a
go-live spot-check every content table was identical, and `sqlite_sequence` was not, which is what
showed that rows had been created and removed rather than nothing having happened. A table only one
side has is reported rather than skipped.

⚠️ THE ROWS ARE COMPARED SORTED, SO STORAGE ORDER IS NOT MISTAKEN FOR A CHANGE. Two databases
holding the same rows in a different physical order are the same data. A genuine reorder shows up in
the `position` column, which is part of the row.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from state import open_ro        # noqa: E402  the one read-only open


def table_names(con):
    return sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_stat%'"))


def columns(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def rows_of(con, table, cols):
    picked = ", ".join(f'"{c}"' for c in cols)
    return sorted(tuple(r) for r in con.execute(f'SELECT {picked} FROM "{table}"'))


def differences(a_db, b_db, report=print):
    """Every table that disagrees, as a list of names. Empty means the two databases match."""
    a, b = open_ro(a_db), open_ro(b_db)
    try:
        ta, tb = table_names(a), table_names(b)
        bad = []
        for t in sorted(set(ta) | set(tb)):
            if t not in ta or t not in tb:
                report(f"  {t:28} ONLY IN {'a' if t in ta else 'b'}")
                bad.append(t)
                continue
            ca, cb = columns(a, t), columns(b, t)
            if ca != cb:
                report(f"  {t:28} COLUMNS DIFFER")
                report(f"      a={ca}")
                report(f"      b={cb}")
                bad.append(t)
                continue
            ra, rb = rows_of(a, t, ca), rows_of(b, t, ca)
            if ra == rb:
                report(f"  {t:28} identical ({len(ra)} rows, {len(ca)} columns)")
                continue
            bad.append(t)
            only_a = [r for r in ra if r not in rb]
            only_b = [r for r in rb if r not in ra]
            report(f"  {t:28} DIFFERS  a={len(ra)} b={len(rb)}  "
                   f"only_in_a={len(only_a)} only_in_b={len(only_b)}")
            for r in only_a[:3]:
                report(f"      only in a: {str(r)[:150]}")
            for r in only_b[:3]:
                report(f"      only in b: {str(r)[:150]}")
        return bad
    finally:
        a.close()
        b.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="compare two databases row for row, read-only")
    ap.add_argument("a", help="one database")
    ap.add_argument("b", help="the other database")
    args = ap.parse_args(argv)
    bad = differences(args.a, args.b)
    print()
    print("EVERY TABLE IS IDENTICAL" if not bad else f"TABLES THAT DIFFER: {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
