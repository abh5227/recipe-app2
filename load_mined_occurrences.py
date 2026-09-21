#!/usr/bin/env python3
"""load_mined_occurrences.py - put occurrence_run.py's JSON into mined_occurrences.

⚠️ SEPARATE FROM THE MIGRATION ON PURPOSE. migrations/035 creates the table and a clone without
the corpus correctly ends up with it empty. This is the step that only runs where the corpus and
its counts exist. Idempotent: it replaces the rows for one source_slug and leaves any other
corpus's rows alone, since source_slug is half the primary key.

⚠️ IT REFUSES A COUNT THAT IS NOT A CATALOG ROW. The reducer only ever emits library_ids from the
built catalog, so an orphan would mean the catalog moved under the counts. That is worth stopping
for rather than storing.
"""
import argparse, json, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load(db, path, dry=False):
    d = json.load(open(path))
    slug, counts = d["source_slug"], d["counts"]
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    ids = {r[0] for r in conn.execute("SELECT library_id FROM library_names")}
    orphans = [k for k in counts if k not in ids]
    if orphans:
        raise SystemExit(f"REFUSED: {len(orphans)} counted ids are not catalog rows, "
                         f"e.g. {orphans[:5]}. The catalog moved under these counts.")
    rows = [(k, v["n"], v["n_recipes"], slug) for k, v in counts.items()]
    print(f"  {len(rows):,} rows for source_slug {slug!r}, 0 orphans")
    if dry:
        print("  dry run, nothing written")
        return
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM mined_occurrences WHERE source_slug=?", (slug,))
        conn.executemany("INSERT INTO mined_occurrences (library_id,n,n_recipes,source_slug) "
                         "VALUES (?,?,?,?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    n = conn.execute("SELECT COUNT(*) FROM mined_occurrences WHERE source_slug=?", (slug,)).fetchone()[0]
    print(f"  committed. mined_occurrences now holds {n:,} rows for {slug}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="?", default="previews/occurrence-counts.json")
    ap.add_argument("--db", default=str(BASE / "recipes.db"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load(a.db, a.json, a.dry_run)
