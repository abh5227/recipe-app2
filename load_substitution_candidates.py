#!/usr/bin/env python3
"""load_substitution_candidates.py - put substitution_run.py's JSON into the review queue.

⚠️ IT LOADS A QUEUE, NOT FACTS. mined_substitution_candidates is what the corpus proposes.
library_substitutions is what a person confirmed, and it is written only by
load_substitutions.py replaying hand_substitutions.csv. Nothing here touches it.

⚠️ THE TABLE IS REBUILT WHOLE for its source_slug, because it is disposable. Losing it costs 622
seconds of CPU. Decisions are not in it: a confirm or a reject is a line in the hand file, so a
reload re-proposes nothing that was already answered.

⚠️ IT REFUSES AN ID THAT IS NOT A CATALOG ROW, the same rule load_relations.py uses. The
extractor only ever emits library_ids from the built catalog, so an orphan means the catalog
moved under the candidates, and a skipped row would be a silent no-op.

⚠️ THE REVERSE COUNT IS COMPUTED HERE, from the candidate set itself. 631 pairs were seen both
ways. Storing each direction with the other's count beside it is what lets a reviewer read
water -> chicken broth at 137 against 5 the other way without writing a self-join.
"""
import argparse, collections, json, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent


def shape(d):
    """The JSON turned into rows, with n_reverse filled and the one-to-many cases folded in."""
    slug = d["source_slug"]
    n_by = {(r["from_id"], r["to_id"]): r["n"] for r in d["candidates"]}
    rows = [(r["from_id"], r["to_id"], r["n"], n_by.get((r["to_id"], r["from_id"]), 0), 0,
             "+".join(r["patterns"]), slug) for r in d["candidates"]]
    # ⚠️ ONE-TO-MANY IS MERGED PER from_id. The extractor keys these on (from_id, pattern), and
    #    the queue asks a single question about each ingredient: what does the corpus say replaces
    #    it that this schema cannot hold? Two patterns saying so about `water` is one gap, not two.
    merged, pats = collections.Counter(), {}
    for r in d["unrepresentable"]:
        merged[r["from_id"]] += r["n"]
        pats.setdefault(r["from_id"], set()).add(r["pattern"])
    rows += [(f, None, n, 0, 1, "+".join(sorted(pats[f])), slug) for f, n in merged.most_common()]
    return slug, rows


def load(db, path, dry=False):
    d = json.load(open(path))
    slug, rows = shape(d)
    conn = sqlite3.connect(db)
    ids = {r[0] for r in conn.execute("SELECT library_id FROM library_names")}
    orphans = {i for r in rows for i in (r[0], r[1]) if i is not None and i not in ids}
    if orphans:
        raise SystemExit(f"REFUSED: {len(orphans)} candidate ids are not catalog rows, "
                         f"e.g. {sorted(orphans)[:5]}. The catalog moved under these candidates.")
    n_pair = sum(1 for r in rows if not r[4])
    n_gap = sum(1 for r in rows if r[4])
    n_rev = sum(1 for r in rows if r[3])
    print(f"  {n_pair:,} ordered pairs, {n_gap:,} one-to-many gaps, 0 orphans")
    print(f"  {n_rev:,} of the pairs were also seen the other way round")
    if dry:
        print("  dry run, nothing written")
        return
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM mined_substitution_candidates WHERE source_slug=?", (slug,))
        conn.executemany(
            "INSERT INTO mined_substitution_candidates "
            "(from_id,to_id,n,n_reverse,one_to_many,pattern,source_slug) VALUES (?,?,?,?,?,?,?)",
            rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    n = conn.execute("SELECT COUNT(*) FROM mined_substitution_candidates WHERE source_slug=?",
                     (slug,)).fetchone()[0]
    assert n == len(rows), f"wrote {n}, expected {len(rows)}"
    print(f"  committed. the queue holds {n:,} rows for {slug}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="?", default="previews/substitution-candidates.json")
    ap.add_argument("--db", default=str(BASE / "recipes.db"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load(a.db, a.json, a.dry_run)
