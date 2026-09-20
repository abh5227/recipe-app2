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

# ⚠️ THE DATABASE AND THE SOURCE ARE PARAMETERS, AND THEY USED TO BE NEITHER. This script read
#    BASE/'recipes.db' by name, which is the LIVE database, and pinned SOURCE_SLUG to one corpus.
#    A run aimed at a copy still matched against live's catalog, so the counts looked right and
#    were wrong: live holds 10,490 names where the working copy holds 10,020. The loaders beside
#    this script already took --db. This brings the run scripts level with them.
#
#    ⚠️ THE DEFAULTS ARE TODAY'S VALUES AND THE ACCEPTANCE TEST IS THAT THEY STAY THAT WAY.
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


def run(csv_path, limit, column="NER", db=None, reader_key="recipenlg", source_slug=None):
    rd = MP.reader(reader_key)
    conn = __import__("sqlite3").connect(f"file:{db or BASE/'recipes.db'}?mode=ro", uri=True)
    # ⚠️ THE CATALOG IS LOADED AT THE SOURCE'S SCOPE. A source-scoped alias exists because
    #    two corpora disagree about what a name means, so loading unscoped here would leave
    #    india's 'corn flour' -> cornstarch inert and the name would reach nothing. Measured
    #    before this line: cornstarch counted 0 india recipes with the scope dropped.
    cat = LM.load_catalog(conn, source_slug=source_slug or rd["slug"])
    decided, problems = LM.load_decisions(cat)
    for p in problems:
        print(f"  decision problem: {p}")
    conn.close()

    t = RowTally()
    seen_here = set()
    t0 = time.time()
    # ⚠️ A READER THAT DECLARES needs_resolver GETS THE MATCHER. India's own cleaning deletes
    #    ingredients from its cleaned column, so it repairs itself from the raw column, and
    #    whether a name needs repairing is a fact about the catalog rather than about the file.
    #    A reader that does not declare it is called with two arguments, exactly as before.
    def _resolves(name):
        core, _, _ = parse(name)
        if not core:
            return False
        tier, _, _, _ = LM.match(core, cat, decided)
        return tier in MP.MATCHED
    _rd_args = (lambda p, n: rd["lines"](p, n, _resolves)) if rd.get("needs_resolver") \
        else rd["lines"]
    for line in _rd_args(csv_path, limit):
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
    ap.add_argument("--db", default=None, help="database to match against. Default recipes.db")
    ap.add_argument("--reader", default="recipenlg", help="corpus format. See mining_probe.READERS")
    ap.add_argument("--source", default=None, help="source_slug to stamp. Default the reader's")
    a = ap.parse_args()
    slug = a.source or MP.reader(a.reader)["slug"]
    t, el = run(a.corpus, a.n, db=a.db, reader_key=a.reader, source_slug=slug)
    out = {
        "source_slug": slug,
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
