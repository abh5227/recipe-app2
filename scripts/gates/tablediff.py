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
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from state import open_ro        # noqa: E402  the one read-only open


def table_names(con):
    return sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_stat%'"))


def columns(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def rows_of(con, table, cols):
    """The table's rows as a MULTISET of tuples.

    ⚠️ NOT SORTED, AND THAT IS A BUG FIX RATHER THAN A STYLE CHOICE. The first version sorted the
    rows to compare them, which raises TypeError the moment one column holds both NULL and text in
    the same table: Python 3 will not order None against str. Every fixture here happened to be
    uniform, so it passed its own tests and then died on the first real database, on
    recipes.author. A multiset needs no ordering, answers the same question, and turns the
    "only in a" scan from quadratic into a subtraction.

    ⚠️ AND A MULTISET, NOT A SET, so two identical rows are not silently one. recipe_steps and
    recipe_ingredients carry no uniqueness on (recipe_id, position), and a duplicate appearing or
    disappearing is exactly the kind of thing this is for."""
    picked = ", ".join(f'"{c}"' for c in cols)
    return Counter(tuple(r) for r in con.execute(f'SELECT {picked} FROM "{table}"'))


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
                report(f"  {t:28} identical ({sum(ra.values())} rows, {len(ca)} columns)")
                continue
            bad.append(t)
            only_a = list((ra - rb).elements())
            only_b = list((rb - ra).elements())
            report(f"  {t:28} DIFFERS  a={sum(ra.values())} b={sum(rb.values())}  "
                   f"only_in_a={len(only_a)} only_in_b={len(only_b)}")
            # sorted by repr, which is a total order over mixed types, purely so the printed
            # sample is stable between runs. The comparison above never sorts.
            for r in sorted(only_a, key=repr)[:3]:
                report(f"      only in a: {str(r)[:150]}")
            for r in sorted(only_b, key=repr)[:3]:
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
