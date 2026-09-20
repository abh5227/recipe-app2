#!/usr/bin/env python3
"""pairing_run.py - phase 3c part 1. Co-occurrence and lift over the corpus.

⚠️ IT WRITES FILES, NOT THE DATABASE. Same discipline as occurrence_run.py. The counts go to
JSON so the min-n floor and the long-record cap can be decided on real numbers.

⚠️ THE TALLY IS BOUNDED IN PRACTICE, NOT IN THEORY. C(3018,2) is 4.5 million cells, but the
median recipe carries 6 matched ingredients, so it emits C(6,2)=15 pairs and the same common
ingredients recur. Measured growth exponent 0.39, projecting roughly 168,000 distinct pairs at
full scale. The ceiling is set by recipe length, not by catalog size.

⚠️ LIFT USES THE FROZEN DENOMINATOR. n_a and n_b come from mined_occurrences, which was built by
occurrence_run.py over this same corpus with this same matcher. The corpus is frozen at
recipenlg-2020 and is never updated, so the stored lift cannot go stale. That is why it is stored
rather than recomputed on read.

⚠️ THIS READER YIELDS THE TITLE, AND mining_probe's DOES NOT. That is deliberate on both sides.
mining_probe.from_recipenlg reads one column and never yields the others, and it stays that way.
Here the title is read for ONE purpose: to report what the >40-ingredient records actually are, so
a cap excludes them on evidence rather than on assumption. Titles go to a SEPARATE inspection file
and never to a mined table. docs/mining-decision.md boundary (d): a generic dish type is a fact,
a title is expression, and expression is never stored.
"""
import argparse, ast, collections, csv, itertools, json, sqlite3, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import linkage_matcher as LM
import mining_probe as MP
import nonfood_filter as NF
from recipe_line_parser import parse

csv.field_size_limit(10_000_000)
# ⚠️ THE DATABASE AND THE SOURCE ARE PARAMETERS, AND THEY USED TO BE NEITHER. This script read
#    BASE/'recipes.db' by name, which is the LIVE database. A run aimed at a copy still matched
#    against live's catalog, so the counts looked right and were wrong: live holds 10,490 names
#    where the working copy holds 10,020. The loaders beside it already took --db.
#
#    ⚠️ THE DEFAULTS ARE TODAY'S VALUES AND THE ACCEPTANCE TEST IS THAT THEY STAY THAT WAY.
SOURCE_SLUG = "recipenlg-2020"
LONG_K = 25                 # settled: 99.9% of recipes sit at k<=20, clean gap above


def stream(path, limit):
    """Yield (title, [ingredient names]) per recipe. Directions and link are never read."""
    with open(path, newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        n = 0
        for row in r:
            raw = row.get("NER") or ""
            try:
                items = ast.literal_eval(raw) if raw.startswith("[") else []
            except (ValueError, SyntaxError):
                items = []
            yield row.get("title") or "", [i for i in items if isinstance(i, str) and i.strip()]
            n += 1
            if n >= limit:
                return


def run(csv_path, limit, cap=LONG_K, db=None, reader_key="recipenlg", source_slug=None):
    rd = MP.reader(reader_key)
    slug = source_slug or rd["slug"]
    conn = sqlite3.connect(f"file:{db or BASE/'recipes.db'}?mode=ro", uri=True)
    # ⚠️ THE CATALOG IS LOADED AT THE SOURCE'S SCOPE. A source-scoped alias exists because
    #    two corpora disagree about what a name means, so loading unscoped here would leave
    #    india's 'corn flour' -> cornstarch inert and the name would reach nothing. Measured
    #    before this line: cornstarch counted 0 india recipes with the scope dropped.
    cat = LM.load_catalog(conn, source_slug=slug)
    decided, _ = LM.load_decisions(cat)
    # ⚠️ THE MARGINALS ARE THIS SOURCE'S OWN, AND THIS LINE USED TO NAME THE MODULE CONSTANT.
    #    lift = n * N / (n_a * n_b), and n_a has to be counted over the same corpus as n. With
    #    the constant here a wikibooks or india run divided its own co-occurrence counts by
    #    RecipeNLG's marginals, which is 2.2 million recipes under a 5,938-recipe numerator. The
    #    lifts came out near zero and nothing errored, because every id in a small source also
    #    appears in the large one. The --source flag existed and one of its two uses was missed.
    singles = {r[0]: r[1] for r in conn.execute(
        "SELECT library_id, n_recipes FROM mined_occurrences WHERE source_slug=?", (slug,))}
    conn.close()
    if not singles:
        raise SystemExit(f"mined_occurrences holds no row for source_slug {slug!r}. Run "
                         f"occurrence_run.py over this source and load it before pairing.")

    pairs = collections.Counter()       # pairs from records at or under the cap
    over = collections.Counter()        # pairs ONLY the over-cap records would add
    klen = collections.Counter()
    longs = []                          # (title, k) for the over-cap records
    nonfood = []                        # (title, reason) for the excluded non-food records
    n_recipes = 0
    t0 = time.time()
    def _resolves(name):
        core, _, _ = parse(name)
        if not core:
            return False
        tier, _, _, _ = LM.match(core, cat, decided)
        return tier in MP.MATCHED
    _recs = rd["records"] or stream
    if rd.get("needs_resolver"):
        _recs = (lambda p, n, _f=rd["records"]: _f(p, n, _resolves))
    for title, names in _recs(csv_path, limit):
        n_recipes += 1
        # ⚠️ EXCLUDED AT THE RECIPE LEVEL, NOT BY BANNING AN INGREDIENT. Almost every cosmetic
        #    marker has a real food use, measured: paraffin is in 1,534 candy recipes, lye makes
        #    hominy, argan oil is Moroccan food, and beeswax lines a canelé mould. The rule asks
        #    what the record is MAKING. See nonfood_filter.py.
        verdict, why = NF.classify(title, names)
        if verdict == "nonfood":
            nonfood.append((title, why))
            continue
        ids = set()
        for nm in names:
            core, _, _ = parse(nm)
            if not core:
                continue
            tier, _, rows, _ = LM.match(core, cat, decided)
            if tier in MP.MATCHED:
                for lid, _c in rows:
                    ids.add(lid)
        k = len(ids)
        klen[k] += 1
        if k > cap:
            longs.append((title, k, len(names)))
            for a, b in itertools.combinations(sorted(ids), 2):
                over[(a, b)] += 1
        else:
            for a, b in itertools.combinations(sorted(ids), 2):
                pairs[(a, b)] += 1
        if n_recipes % 250000 == 0:
            print(f"    {n_recipes:>9,} recipes  {time.time()-t0:>6.0f}s  "
                  f"pairs {len(pairs):,}  over-cap records {len(longs)}", flush=True)
        ids = None                       # dropped with the recipe
    return pairs, over, klen, longs, nonfood, singles, n_recipes, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("-n", type=int, default=10**9)
    ap.add_argument("--cap", type=int, default=LONG_K)
    ap.add_argument("--out", default="previews/pairings.json")
    ap.add_argument("--longs-out", default="previews/long-records.json")
    ap.add_argument("--db", default=None, help="database to match against. Default recipes.db")
    ap.add_argument("--reader", default="recipenlg", help="corpus format. See mining_probe.READERS")
    ap.add_argument("--source", default=None, help="source_slug to stamp. Default the reader's")
    a = ap.parse_args()
    slug = a.source or MP.reader(a.reader)["slug"]
    pairs, over, klen, longs, nonfood, singles, N, el = run(a.corpus, a.n, a.cap, db=a.db,
                                                            reader_key=a.reader, source_slug=slug)

    def lift(ab, n_ab):
        na, nb = singles.get(ab[0], 0), singles.get(ab[1], 0)
        return (n_ab * N) / (na * nb) if na and nb else 0.0

    rows = [{"a_id": a_, "b_id": b_, "n": v, "n_a": singles.get(a_, 0),
             "n_b": singles.get(b_, 0), "lift": round(lift((a_, b_), v), 4)}
            for (a_, b_), v in pairs.items()]
    rows.sort(key=lambda r: -r["n"])
    json.dump({"source_slug": slug, "recipes_read": N, "cap_k": a.cap,
               "nonfood_excluded": len(nonfood),
               "distinct_pairs": len(rows), "seconds": round(el, 1), "pairs": rows},
              open(a.out, "w"))
    # the inspection file, kept separate. Titles never reach a mined table.
    json.dump({"note": "inspection only. Titles are expression and never enter a mined table.",
               "cap_k": a.cap, "records_over_cap": len(longs),
               "pairs_they_would_add": len(set(over) - set(pairs)),
               "pair_emissions_they_would_add": sum(over.values()),
               "k_distribution": dict(sorted(klen.items())),
               "records": [{"title": t, "matched_k": k, "raw_names": rn}
                           for t, k, rn in sorted(longs, key=lambda x: -x[1])],
               "nonfood_excluded": [{"title": t, "why": w} for t, w in nonfood]},
              open(a.longs_out, "w"), indent=1)
    print(f"\n  {N:,} recipes, {el:.0f}s")
    print(f"  distinct pairs {len(rows):,}   over-cap records {len(longs)}   "
          f"non-food excluded {len(nonfood)}")
    print(f"  wrote {a.out} and {a.longs_out}")


if __name__ == "__main__":
    main()
