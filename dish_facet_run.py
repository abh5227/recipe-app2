#!/usr/bin/env python3
"""dish_facet_run.py - resolve all eight dish facets over the corpus, to an inspectable file.

⚠️ TWO PASSES, AND THE REASON IS THE ROUTING. Whether `baked` belongs to the dish name or to the
method facet depends on how often `baked X` appears against `X`, which is a corpus frequency and
is not known until the corpus has been read once. Pass one tallies unrouted dish strings. Pass two
resolves everything.

⚠️ A THIRD PASS BUILDS THE DISH x INGREDIENT PROFILE, and it is separate for a memory reason
rather than a logical one. Without a floor the profile holds a projected 9.1 million cells, and
the floor cannot be applied until the FINAL dish counts exist, which is what pass two produces.
Routing merges dish strings, so a string under the floor in pass one can land in a dish above it.
Gating pass three on the pass-two counts is the only ordering that is both bounded and correct.

⚠️ NO RECIPE TEXT IS STORED. The output holds a cleaned dish string, vocabulary words and
library_ids. The title goes out of scope inside the loop. Nothing refers to a recipe.
"""
import argparse, collections, csv, json, re, sqlite3, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import ast
import brand_guard as BG
import dish_facets as F
import nonfood_filter as NF
import linkage_matcher as LM
import mining_probe as MP
from recipe_line_parser import parse

csv.field_size_limit(10_000_000)
SPLIT = re.compile(r"\s+(?:with|w/|over|on|in|and served with|served with|topped with|"
                   r"smothered in|drizzled with|alongside)\s+", re.I)
TAIL = re.compile(r"\s*\b(recipes?|i{1,3})\s*$", re.I)


def accompaniment_phrase(title):
    t = F.PAREN.sub(" ", F.fold(title or ""))
    parts = SPLIT.split(t, maxsplit=1)
    if len(parts) < 2:
        return ""
    return re.sub(r"[\"“”!?*#]+", " ", TAIL.sub("", parts[1].strip())).strip(" ,.-")


def titles(path, limit):
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= limit:
                break
            yield row.get("title") or ""


def records(path, limit):
    """⚠️ TITLE AND INGREDIENT NAMES, the same two columns pairing_run.py reads and no others.
    Directions and link are never touched."""
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= limit:
                break
            raw = row.get("NER") or ""
            try:
                items = ast.literal_eval(raw) if raw.startswith("[") else []
            except (ValueError, SyntaxError):
                items = []
            yield (row.get("title") or "",
                   [x for x in items if isinstance(x, str) and x.strip()])


def run(corpus, limit, out, floor=10):
    conn = sqlite3.connect(f"file:{BASE/'recipes.db'}?mode=ro", uri=True)
    cat = LM.load_catalog(conn)
    decided, _ = LM.load_decisions(cat)
    canon = {r[0]: r[1] for r in conn.execute("SELECT library_id, canonical FROM library_names")}
    is_cat = BG.catalog_name_check(conn)
    brands = BG.load_brands()
    # ⚠️ base NOW RESOLVES TO A CATALOG ID BEFORE ANYTHING IS EMITTED. It used to emit the
    #    vocabulary word into a column named library_id, and 142 of 146 values were not catalog
    #    rows. A word with no row is a recorded gap and the dish keeps every other facet.
    base_ids, base_gaps = F.base_id_map(conn)
    conn.close()
    print(f"  base vocabulary: {len(base_ids)} resolve to a catalog id, "
          f"{len(base_gaps)} are catalog gaps", flush=True)

    t0 = time.time()
    tally = collections.Counter()
    n = 0
    for title in titles(corpus, limit):
        n += 1
        d = F.specific_dish(title, brands, is_cat)
        if d:
            tally[d] += 1
    p1 = time.time() - t0
    print(f"  pass 1: {n:,} titles, {len(tally):,} unrouted dish strings, {p1:.0f}s", flush=True)

    _acc = {}
    def acc_ids(phrase):
        """⚠️ EVERY catalog row the phrase names, memoized. 88.2% yield at least one."""
        key = phrase.lower().strip()
        if key in _acc:
            return _acc[key]
        w = re.sub(r"[^\w\s'-]", " ", phrase).split()
        found, i = [], 0
        while i < len(w):
            hit = None
            for k in range(min(4, len(w) - i), 0, -1):
                core, _, _ = parse(" ".join(w[i:i+k]))
                if not core:
                    continue
                tier, _, rows_, _ = LM.match(core, cat, decided)
                if tier in MP.MATCHED and len(rows_) == 1:
                    hit = (rows_[0][0], k); break
            if hit:
                if hit[0] not in found:
                    found.append(hit[0])
                i += hit[1]
            else:
                i += 1
        _acc[key] = found
        return found

    dish = collections.Counter()
    facets = {k: collections.Counter() for k in
              ("form", "base", "method", "diet", "structural", "appliance", "accompaniment")}
    cov = collections.Counter()
    gap_hits = collections.Counter()
    cleaned_brand = cleaned_name = 0
    samples = []
    t1 = time.time()
    for idx, title in enumerate(titles(corpus, limit)):
        raw_norm = F.specific_dish(title, None, None)
        d = F.specific_dish(title, brands, is_cat)
        if raw_norm != d:
            if F.NAME_TITLE.search(F.fold(title)):
                cleaned_name += 1
            else:
                cleaned_brand += 1
        if not d:
            cov["no dish at all"] += 1
            continue
        kept, routed = F.route(d, tally)
        if not kept:
            kept = d
        did = F.dish_id(kept)
        dish[(did, kept)] += 1
        ws = F.words(title)
        row = {"title": title, "dish": kept, "dish_id": did}
        f = F.form_of(ws)
        if f:
            facets["form"][(did, f)] += 1
        row["form"] = f
        bs = F.bases_of(ws)
        for b in bs:
            if b in base_ids:
                facets["base"][(did, base_ids[b])] += 1
            else:
                gap_hits[b] += 1
        row["base"] = [canon.get(base_ids[b], b) for b in bs if b in base_ids]
        row["base_gap"] = [b for b in bs if b not in base_ids]
        for name in ("method", "diet", "structural", "appliance"):
            hits = [h for h in F.vocab_hits(title, name)]
            for h in hits:
                facets[name][(did, h)] += 1
            row[name] = hits
        ph = accompaniment_phrase(title)
        aids = acc_ids(ph) if ph else []
        for a in aids:
            facets["accompaniment"][(did, a)] += 1
        row["accompaniment"] = [canon.get(a, a) for a in aids]
        for k in ("form", "base", "method", "diet", "structural", "appliance", "accompaniment"):
            if row.get(k):
                cov[k] += 1
        cov["a dish string"] += 1
        # ⚠️ THE STRIDE SPANS THE FILE AND THE CAP DOES NOT TRUNCATE IT. The old rule collected
        #    the first 4,000 of every 137th record and then kept samples[:400], which is records
        #    0 to 54,800. That is the first 2.5% of the corpus presented as a sample of it, and
        #    this corpus is not uniform: curly apostrophes appear only after row 956,202, so a
        #    head sample reports zero for a character that occurs 5,000 times.
        if idx % 1115 == 0:
            samples.append(row)
    p2 = time.time() - t1
    print(f"  pass 2: {p2:.0f}s   {len(dish):,} distinct dishes", flush=True)

    # ── pass 3, the dish x ingredient profile ────────────────────────────────────────────────
    # ⚠️ GATED ON THE FINAL DISH COUNTS, which is why it cannot be folded into pass 2. Ungated
    #    this counter holds a projected 9.1 million cells. Gated at the floor it holds about 1.5
    #    million, and the rows it drops are the thin cells boundary (c) exists to refuse.
    dcount = {i: c for (i, _s), c in dish.items()}
    above = {i for i, c in dcount.items() if c >= floor}
    print(f"  pass 3: profiling {len(above):,} dishes at n >= {floor} "
          f"({sum(dcount[i] for i in above):,} recipes)", flush=True)
    conn = sqlite3.connect(f"file:{BASE/'recipes.db'}?mode=ro", uri=True)
    cat2 = LM.load_catalog(conn)
    decided2, _ = LM.load_decisions(cat2)
    conn.close()
    prof = collections.Counter()
    nonfood = 0
    t2 = time.time()
    _seen = {}
    for idx, (title, names) in enumerate(records(corpus, limit)):
        d = F.specific_dish(title, brands, is_cat)
        if not d:
            continue
        kept, _ = F.route(d, tally)
        did = F.dish_id(kept or d)
        if did not in above:
            continue
        # ⚠️ EXCLUDED AT THE RECIPE LEVEL, the same rule pairing_run.py uses. A cosmetic record
        #    would otherwise put paraffin and lye into a dish profile.
        if NF.classify(title, names)[0] == "nonfood":
            nonfood += 1
            continue
        ids = set()
        for nm in names:
            key = nm.lower().strip()
            if key in _seen:
                got = _seen[key]
            else:
                core, _, _ = parse(nm)
                got = ()
                if core:
                    tier, _, rr, _ = LM.match(core, cat2, decided2)
                    if tier in MP.MATCHED:
                        got = tuple(lid for lid, _c in rr)
                if len(_seen) < 400000:
                    _seen[key] = got
            ids.update(got)
        for lid in ids:
            prof[(did, lid)] += 1
        if idx and idx % 500000 == 0:
            print(f"    {idx:>9,} records  cells {len(prof):,}  {time.time()-t2:.0f}s", flush=True)
    p3 = time.time() - t2
    print(f"  pass 3: {p3:.0f}s   {len(prof):,} cells, {nonfood:,} non-food records excluded",
          flush=True)

    payload = {
        "source_slug": F.SOURCE_SLUG, "titles_read": n,
        "seconds": round(p1 + p2 + p3, 1),
        "coverage": {k: cov[k] for k in sorted(cov)},
        "cleaned_brand": cleaned_brand, "cleaned_name": cleaned_name,
        "distinct_dishes": len(dish),
        "facet_rows": {k: len(v) for k, v in facets.items()},
        "dishes": [{"dish_id": i, "dish": s, "n": c} for (i, s), c in dish.most_common()],
        "facets": {k: [{"dish_id": i, "value": v, "n": c} for (i, v), c in vv.most_common()]
                   for k, vv in facets.items()},
        "samples": samples,
        "base_resolved": len(base_ids), "base_gaps": base_gaps,
        "base_gap_hits": dict(gap_hits.most_common()),
        "dish_floor_pass3": floor,
        "profile_cells": len(prof),
        "profiles": [{"dish_id": i, "library_id": l, "n": c, "n_dish": dcount[i]}
                     for (i, l), c in prof.most_common()],
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(out, "w"))
    print(f"  wrote {out}", flush=True)
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("-n", type=int, default=10**9)
    ap.add_argument("--out", default="previews/dish-facets.json")
    ap.add_argument("--floor", type=int, default=10,
                    help="dish floor for the pass-3 profile. The loader applies it to every table.")
    a = ap.parse_args()
    p = run(a.corpus, a.n, a.out, a.floor)
    print(f"\n  titles {p['titles_read']:,}  dishes {p['distinct_dishes']:,}")
    for k, v in p["coverage"].items():
        print(f"    {k:<20}{v:>9,}{v/p['titles_read']:>8.1%}")
