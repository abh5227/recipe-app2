#!/usr/bin/env python3
"""load_aliases.py - load hand_aliases.csv into library_aliases.

⚠️ THE HAND FILE IS THE ONLY WRITER, the same contract load_relations.py holds for
library_relations. Everything in the catalog is replayed from a committed file on every build, and
an alias stored only in recipes.db would be orphaned by the next load with nothing to notice it.

⚠️ AN ALIAS ADDS A NAME. IT NEVER MERGES. A merge destroys a library_id, and
mined_dish_ingredient, mined_dish_base and mined_pairings all hold catalog ids, so a merge orphans
mined data. Nothing here writes to library_names, so a merge is not expressible by this loader at
all, which is the point.

⚠️ AN ALIAS THAT WOULD NEWLY RESOLVE TO TWO ROWS STOPS THE LOAD rather than being skipped. The
table deliberately carries no UNIQUE on `alias`, because six names are ALREADY held by two rows
each (brown sauce, gnocchi, ice cream, milkshake, mus, turnip) and linkage_matcher refuses those
by design: "AMBIGUOUS - the name is held by more than one catalog row. REFUSED, never picked." A
UNIQUE would make the table unable to describe a state the catalog already holds. So the CONSTRAINT
is not in the schema, it is here, and it is about what this file ADDS rather than what exists.

⚠️ AN ALIAS THAT COLLIDES WITH ANOTHER ROW'S CANONICAL ALSO STOPS THE LOAD. Writing `stock` as an
alias of some other row would make a name that resolves today resolve to two rows tomorrow, which
is the same failure by a different route.

⚠️ EMPTY IS SAFE AND IS THE NORMAL STATE FOR A FRESH CLONE. library_names is loaded from a
gitignored, server-side CSV, so a clone has no rows for an alias to point at. With no catalog the
loader reports and returns rather than raising, exactly as build_db.seed_library_names does.
"""
import csv, sqlite3, sys

DB = "recipes.db"
HAND = "hand_aliases.csv"


def read(path=HAND):
    """The hand file's rows, comments skipped. The file is the contract, not this function."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(ln for ln in fh if not ln.lstrip().startswith("#")):
            if not (r.get("library_id") or "").strip() or not (r.get("alias") or "").strip():
                continue
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def load(db=DB, hand=HAND, verbose=True):
    conn = sqlite3.connect(db)
    canon = {l: n for l, n in conn.execute("SELECT library_id, canonical FROM library_names")}
    if not canon:
        if verbose:
            print("Note: library_names is empty — aliases left unloaded.")
        conn.close()
        return 0
    by_name = {}
    for lid, nm in canon.items():
        by_name.setdefault(nm.lower(), set()).add(lid)

    rows = read(hand)
    seen = {}
    for r in rows:
        lid, alias = r["library_id"], r["alias"]
        if lid not in canon:
            raise SystemExit(f"⚠️  alias {alias!r} points at {lid!r}, which does not resolve in "
                             "library_names. Fix the hand file rather than skipping the row.")
        # ⚠️ the dual-key check. A canonical that moved since review is a decision to re-read.
        snap = r.get("canonical_at_load") or ""
        if snap and snap != canon[lid]:
            raise SystemExit(f"⚠️  alias {alias!r} was reviewed against {snap!r} and {lid} is now "
                             f"{canon[lid]!r}. Re-read the decision rather than loading it.")
        holders = set(by_name.get(alias.lower(), set())) - {lid}
        if holders:
            raise SystemExit(f"⚠️  alias {alias!r} collides with the canonical of "
                             f"{sorted(holders)}. It would resolve to two rows.")
        if alias.lower() in seen and seen[alias.lower()] != lid:
            raise SystemExit(f"⚠️  alias {alias!r} is claimed by {seen[alias.lower()]} and by "
                             f"{lid} in this file. It would resolve to two rows.")
        seen[alias.lower()] = lid

    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM library_aliases")
        for r in rows:
            conn.execute(
                "INSERT INTO library_aliases "
                "(library_id, alias, canonical_at_load, source, confidence, note) "
                "VALUES (?,?,?,?,?,?)",
                (r["library_id"], r["alias"], canon[r["library_id"]],
                 r.get("source") or "read", r.get("confidence") or "read",
                 r.get("note") or None))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    if verbose:
        print(f"Aliases: {len(rows):,} loaded from {hand}.")
    return len(rows)


if __name__ == "__main__":
    load(*(sys.argv[1:3] or []))
