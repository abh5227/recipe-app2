#!/usr/bin/env python3
"""occurrence_run.py - phase 3b part 1. Count how often each catalog row appears in the corpus.

⚠️ IT WRITES A FILE, NOT THE DATABASE. The counts go to JSON so they can be read before anything
is stored. A fifteen minute run that ends in an inspectable file is cheap to repeat. One that
ends in a DB write is not.

⚠️ THE TALLY IS BOUNDED, AND THIS IS THE POINT OF THE REKEY. mining_probe.Tally counts per
ingredient NAME, which grows by Heaps' law: 3,860 distinct names at 10k recipes, 21,556 at 200k,
roughly 82,000 at the full 2.2M. 3b does not need per-name counts. Counting per library_id caps
every structure at the 10,474 rows the catalog holds, whatever the corpus size. Nothing here
grows with the number of recipes read.

⚠️ NO RECIPE TEXT SURVIVES THE LOOP. docs/mining-decision.md (b) and (f). A row is read, its NER
names are folded into two integer counters keyed on library_id, and the row is dropped before the
next is read. The title, the directions and the link are never yielded by the reader at all.
"""
import argparse, collections, json, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import linkage_matcher as LM
import mining_probe as MP
from recipe_line_parser import parse

SOURCE_SLUG = "recipenlg-2020"          # pins which corpus produced these counts


class RowTally:
    """Counters keyed on library_id. Bounded by the catalog, not by the corpus."""
    def __init__(self):
        self.n = collections.Counter()          # occurrences, a row may repeat within a recipe
        self.n_recipes = collections.Counter()  # distinct recipes the row appears in
        self.recipes = 0
        self.lines = 0
        self.unparsed = 0
        self.unmatched = 0

    def fold(self, ids_this_recipe):
        for lid in ids_this_recipe:
            self.n_recipes[lid] += 1


def run(csv_path, limit, column="NER"):
    conn = __import__("sqlite3").connect(f"file:{BASE/'recipes.db'}?mode=ro", uri=True)
    cat = LM.load_catalog(conn)
    decided, problems = LM.load_decisions(cat)
    for p in problems:
        print(f"  decision problem: {p}")
    conn.close()

    t = RowTally()
    seen_here = set()
    t0 = time.time()
    for line in MP.from_recipenlg(csv_path, limit, column):
        if line is MP.SENTINEL:
            t.recipes += 1
            t.fold(seen_here)
            seen_here = set()                   # dropped with the recipe
            if t.recipes % 250000 == 0:
                print(f"    {t.recipes:>9,} recipes  {time.time()-t0:>6.0f}s  "
                      f"rows counted {len(t.n):,}", flush=True)
            continue
        t.lines += 1
        core, _, _ = parse(line)
        if not core:
            t.unparsed += 1
            continue
        tier, _, rows, _ = LM.match(core, cat, decided)
        if tier not in MP.MATCHED:
            t.unmatched += 1
            continue
        for lid, _canon in rows:
            t.n[lid] += 1
            seen_here.add(lid)
        # line, core and rows go out of scope here
    t.fold(seen_here)
    return t, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("-n", type=int, default=10**9, help="recipes to read, default all")
    ap.add_argument("-o", "--out", default="previews/occurrence-counts.json")
    a = ap.parse_args()
    t, el = run(a.corpus, a.n)
    out = {
        "source_slug": SOURCE_SLUG,
        "corpus_file": Path(a.corpus).name,
        "recipes_read": t.recipes,
        "ingredient_lines": t.lines,
        "unparsed": t.unparsed,
        "unmatched": t.unmatched,
        "rows_counted": len(t.n),
        "seconds": round(el, 1),
        "counts": {lid: {"n": t.n[lid], "n_recipes": t.n_recipes[lid]}
                   for lid in sorted(t.n, key=lambda k: -t.n[k])},
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"\n  {t.recipes:,} recipes, {t.lines:,} lines, {el:.0f}s")
    print(f"  rows counted {len(t.n):,} of 10,474")
    print(f"  wrote {a.out}")


if __name__ == "__main__":
    main()
