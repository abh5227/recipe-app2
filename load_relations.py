#!/usr/bin/env python3
"""load_relations.py - load hand_links.csv into library_categories + library_relations.

⚠️ library_categories HOLDS ONLY FILTER CATEGORIES, terms that are not catalog rows. A kind_of
parent IS a catalog row, so a kind_of edge's parent_id is a library_id and an in_category edge's
parent_id is a category slug. "Is X a kind_of parent" is derived by asking whether any kind_of
edge points at X, not stored as a flag.

⚠️ THE HAND FILE IS THE ONLY WRITER. Everything else in the catalog is replayed from a hand file
on every build, and an edge stored only in recipes.db would be orphaned by the next fold with
nothing in the build to notice. Phase C proved the shape: its 41 folds live in hand_removals.csv,
so a rebuild reproduces them.

⚠️ THE DUAL-KEY SNAPSHOT IS TAKEN HERE. child_canonical and parent_canonical record what the names
were at load time, reusing the pattern library_entries already proves (52 of 56 'linked', 1
'canonical_drift', 0 dangling). A re-keyed row is then diagnosable by reading the edge rather than
by re-deriving it.

⚠️ AN EDGE WHOSE child_id DOES NOT RESOLVE STOPS THE LOAD rather than being skipped. A skipped edge
is a silent no-op, and Phase C showed how expensive those are: a fold with a wrong anchor did
nothing, said nothing, and was caught only because a row count came back one higher than expected.
"""
import csv, sqlite3

DB = "recipes.db"
HAND = "hand_links.csv"


def _rows(path):
    """Split the hand file into its two sections. Comments and blanks are skipped."""
    cats, rels, cur = [], [], None
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("category_id,"):
            cur = "c"; continue
        if s.startswith("child,"):
            cur = "r"; continue
        (cats if cur == "c" else rels).append(next(csv.reader([line])))
    return cats, rels


def load(db=DB, hand=HAND, verbose=True):
    conn = sqlite3.connect(db)
    canon = {l: n for l, n in conn.execute("SELECT library_id, canonical FROM library_names")}
    cats, rels = _rows(hand)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM library_relations")
        conn.execute("DELETE FROM library_categories")
        for r in cats:
            conn.execute("INSERT INTO library_categories (category_id,name,parent_slug,note)"
                         " VALUES (?,?,?,?)", (r[0], r[1], r[2] or None, r[3] or None))
        slugs = {r[0] for r in cats}
        for r in rels:
            child, parent, kind, source, conf, note = (r + [""] * 6)[:6]
            if child not in canon:
                raise SystemExit(f"⚠️  edge child {child!r} does not resolve in library_names. "
                                 "Fix the hand file rather than skipping the row.")
            if kind == "in_category":
                if parent not in slugs:
                    raise SystemExit(f"⚠️  in_category edge points at {parent!r}, which is not a "
                                     "category in this file.")
                pc = next(c[1] for c in cats if c[0] == parent)
            else:
                if parent not in canon:
                    raise SystemExit(f"⚠️  {kind} edge parent {parent!r} does not resolve in "
                                     "library_names.")
                pc = canon[parent]
            conn.execute("INSERT INTO library_relations (child_id,parent_id,kind,child_canonical,"
                         "parent_canonical,source,confidence,note) VALUES (?,?,?,?,?,?,?,?)",
                         (child, parent, kind, canon[child], pc, source, conf, note or None))
        nc = conn.execute("SELECT COUNT(*) FROM library_categories").fetchone()[0]
        nr = conn.execute("SELECT COUNT(*) FROM library_relations").fetchone()[0]
        assert nc == len(cats) and nr == len(rels), f"wrote {nc}/{nr}, expected {len(cats)}/{len(rels)}"
        conn.execute("COMMIT")
        if verbose:
            print(f"loaded {nc} categories, {nr} relations from {hand}")
        return nc, nr
    except Exception:
        conn.execute("ROLLBACK"); raise
    finally:
        conn.close()


if __name__ == "__main__":
    load()
