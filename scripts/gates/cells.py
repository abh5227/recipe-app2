#!/usr/bin/env python3
"""Which CELLS of a table moved, against what the round said may move.

    python3.13 scripts/gates/cells.py --a before.db --b after.db \
                                      --round golive/rounds/<round>.json

⚠️ AN EXCEPTED TABLE IS NOT COMPARED AT ALL, AND THAT IS A HOLE IN EVERY ROUND THAT HAS ONE.
`rounds.py` compares whole tables row for row, so a table the round writes to has to go in
`tables.except` or the comparison fails on every write. The cost is that the gate then says nothing
about the OTHER cells of that table, which are the ones nobody is watching. The 2026-10-07 round
closed the hole for its one table with a check written inline in the go-live file. This is that check,
stated over any table and any round, so the next one does not write it again.

⚠️ THE ALLOWANCE LIVES IN THE ROUND'S OWN FILE, under a "cells" key, beside the declaration
rounds.py reads. It was a second file for about ten minutes, which broke
tests/test_gates.py::test_every_committed_round_file_loads, because every .json in golive/rounds/ is
a round file and that one was not. One round, one declaration.

The "cells" key, one entry per table:

    "cells": {
      "recipe_steps": {
        "columns": ["heading_level", "text", "position"],
        "ids":      [2536, 2623, ...],
        "deleted":  [3651],
        "inserted": 0
      }
    }

  columns   the only columns whose values may differ. A column named here that moved on NO row FAILS,
            because a declaration describing nothing is how a gate passes for lack of a question.
  ids       the only rows whose values may differ. The set must match EXACTLY in both directions: a
            row that moved and is not named is a stray write, and a row named that did not move is a
            decision that did not happen.
  deleted   row ids that may disappear. Any other disappearance fails.
  inserted  how many rows may appear. A different number fails. The ids are not named because the
            database mints them on the way in, so naming one would mean knowing it before the run.

⚠️ `position` IS A COLUMN LIKE ANY OTHER AND IS DECLARED LIKE ANY OTHER. A row added or taken away
shifts every row after it, so those rows really did move and the gate says so. Hiding that behind a
"positions may shift" flag would hide a reorder as well.

⚠️ READ-ONLY BY CONSTRUCTION. Both sides are opened through state.open_ro, which spells
`file:<path>?mode=ro`, so SQLite refuses a write rather than this file promising not to make one.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import state as gstate                    # noqa: E402


class BadAllowance(Exception):
    """The declaration itself is wrong, which is not the same as the gate failing."""


def load_allowance(path):
    p = pathlib.Path(path)
    if not p.is_file():
        raise BadAllowance(f"no round file at {p}\n"
                           f"  An excepted table is unwatched until something says what may move "
                           f"in it. There is no default.")
    whole = json.loads(p.read_text())
    if not isinstance(whole, dict) or "cells" not in whole:
        raise BadAllowance(f"{p} carries no \"cells\" key. A round that excepts a table from "
                           f"rounds.py has to say what may move inside it.")
    spec = whole["cells"]
    if not isinstance(spec, dict) or not spec:
        raise BadAllowance(f"{p}: \"cells\" must be a non-empty object keyed by table name")
    for table, allow in spec.items():
        for key in ("columns", "ids", "deleted", "inserted"):
            if key not in allow:
                raise BadAllowance(f"{p}: {table} leaves out {key!r}. Every key is required, so "
                                   f"silence is never consent.")
        if not isinstance(allow["inserted"], int):
            raise BadAllowance(f"{p}: {table}'s 'inserted' must be a count, not "
                               f"{allow['inserted']!r}")
    return spec


def _rows(conn, table, pk):
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
    if not cols:
        raise BadAllowance(f"there is no table called {table!r}")
    sel = ",".join('"' + c + '"' for c in cols)
    return cols, {r[pk]: dict(r) for r in conn.execute(f"SELECT {sel} FROM {table}")}


def check(a_db, b_db, spec, pk="id"):
    """-> (ok, [lines to print])."""
    ca, cb = gstate.open_ro(a_db), gstate.open_ro(b_db)
    out, ok = [], True
    for table, allow in spec.items():
        cols_a, ra = _rows(ca, table, pk)
        cols_b, rb = _rows(cb, table, pk)
        if cols_a != cols_b:
            out.append(f"  {table}: the COLUMNS moved, -{sorted(set(cols_a) - set(cols_b))} "
                       f"+{sorted(set(cols_b) - set(cols_a))}")
            ok = False
            continue
        gone, new = sorted(set(ra) - set(rb)), sorted(set(rb) - set(ra))
        moved = {}
        for rid in set(ra) & set(rb):
            for c in cols_a:
                if ra[rid][c] != rb[rid][c]:
                    moved.setdefault(c, []).append((rid, ra[rid][c], rb[rid][c]))
        cells = sum(len(v) for v in moved.values())
        out.append(f"  {table}: {len(ra)} rows x {len(cols_a)} columns = {len(ra) * len(cols_a)} "
                   f"cells, {cells} moved over {len({r for v in moved.values() for r, _x, _y in v})} "
                   f"row(s); {len(gone)} deleted, {len(new)} inserted")
        for c in sorted(moved):
            out.append(f"      {c}: {len(moved[c])}")

        bad_cols = sorted(set(moved) - set(allow["columns"]))
        if bad_cols:
            out.append(f"      REFUSING: {bad_cols} moved and the round did not declare them")
            for c in bad_cols:
                for m in moved[c][:4]:
                    out.append(f"          {c} on row {m[0]}: {m[1]!r} -> {m[2]!r}")
            ok = False
        # ⚠️ AND THE OTHER DIRECTION, WHICH IS THE ANTI-VACUITY HALF. A column declared that moved on
        #    no row means the declaration describes something that did not happen.
        idle = sorted(set(allow["columns"]) - set(moved))
        if idle:
            out.append(f"      REFUSING: {idle} declared and moved on no row, so the declaration "
                       f"describes something this run did not do")
            ok = False

        moved_ids = {r for v in moved.values() for r, _x, _y in v}
        declared_ids = set(allow["ids"])
        if moved_ids != declared_ids:
            out.append(f"      REFUSING: the rows that moved are not the rows declared. "
                       f"undeclared={sorted(moved_ids - declared_ids)[:12]} "
                       f"declared_but_still={sorted(declared_ids - moved_ids)[:12]}")
            ok = False
        if gone != sorted(allow["deleted"]):
            out.append(f"      REFUSING: deleted {gone}, declared {sorted(allow['deleted'])}")
            ok = False
        if len(new) != allow["inserted"]:
            out.append(f"      REFUSING: {len(new)} row(s) inserted, {allow['inserted']} declared "
                       f"({new[:6]})")
            ok = False
    ca.close()
    cb.close()
    return ok, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", required=True, help="the BEFORE database")
    ap.add_argument("--b", required=True, help="the AFTER database")
    ap.add_argument("--round", dest="round_file", required=True,
                    help="the round file, whose \"cells\" key is the allowance")
    a = ap.parse_args(argv)
    try:
        spec = load_allowance(a.round_file)
    except BadAllowance as e:
        print(f"BAD ALLOWANCE: {e}")
        return 2
    try:
        ok, lines = check(a.a, a.b, spec)
    except BadAllowance as e:
        print(f"BAD ALLOWANCE: {e}")
        return 2
    print(f"allowance: {a.round_file} -> cells")
    for line in lines:
        print(line)
    print("EVERY MOVED CELL WAS DECLARED" if ok else "STOP")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
