#!/usr/bin/env python3
"""load_mined_pairings.py - put pairing_run.py's JSON into mined_pairings.

⚠️ SEPARATE FROM THE MIGRATION. migrations/036 creates the table, and a clone without the corpus
correctly ends up with it empty. This is the step that only runs where the corpus and its pairs
exist. Idempotent per source_slug, which is half the primary key.

⚠️ IT REFUSES AN ID THAT IS NOT A CATALOG ROW. The reducer only ever emits library_ids from the
built catalog, so an orphan would mean the catalog moved under the pairs.
"""
import argparse, json, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load(db, path, dry=False):
    d = json.load(open(path))
    slug, rows_in = d["source_slug"], d["pairs"]
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    ids = {r[0] for r in conn.execute("SELECT library_id FROM library_names")}
    orphans = {r["a_id"] for r in rows_in if r["a_id"] not in ids} | \
              {r["b_id"] for r in rows_in if r["b_id"] not in ids}
    if orphans:
        raise SystemExit(f"REFUSED: {len(orphans)} paired ids are not catalog rows, "
                         f"e.g. {sorted(orphans)[:5]}. The catalog moved under these pairs.")
    rows = [(r["a_id"], r["b_id"], r["n"], r["n_a"], r["n_b"], r["lift"], slug) for r in rows_in]
    print(f"  {len(rows):,} pairs for source_slug {slug!r}, 0 orphans")
    if dry:
        print("  dry run, nothing written")
        return
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM mined_pairings WHERE source_slug=?", (slug,))
        conn.executemany("INSERT INTO mined_pairings "
                         "(a_id,b_id,n,n_a,n_b,lift,source_slug) VALUES (?,?,?,?,?,?,?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    n = conn.execute("SELECT COUNT(*) FROM mined_pairings WHERE source_slug=?", (slug,)).fetchone()[0]
    print(f"  committed. mined_pairings now holds {n:,} rows for {slug}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="?", default="previews/pairings.json")
    ap.add_argument("--db", default=str(BASE / "recipes.db"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load(a.db, a.json, a.dry_run)
