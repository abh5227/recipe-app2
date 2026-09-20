#!/usr/bin/env python3
"""mining_probe.py - Phase 2. Does the corpus vocabulary overlap the built catalog?

⚠️ THIS IS A PROBE, NOT A PIPELINE. It answers one question cheaply, before anything is built on
the answer: of the distinct ingredient names a corpus sample uses, how many reach a catalog row?
It extracts no facts, writes no table and creates no file.

⚠️ THE BOUNDARY IS IN THE SHAPE OF THE CODE, not in a promise. docs/mining-decision.md boundary (b)
and (f). This is a streaming reducer. One recipe is read, its ingredient names are folded into
counters, and the row is dropped before the next is read. No recipe text, no title, no instruction
and no per-recipe list survives the loop that read it. The only things that outlive a row are
integer counters and a set of normalized INGREDIENT NAMES, which are food names rather than
anybody's writing, and which are what a coverage number is made of.

⚠️ IT MATCHES THE BUILT CATALOG, NOT join.db, for the reason linkage_matcher.py gives: build_library
moves roughly 4,000 names between rows, so a name's row in the raw join is an input to the build and
not its output. library_names in recipes.db is the shipped catalog and the only correct target.

    python3.13 mining_probe.py --selftest          measure the harness on the 298 local recipes
    python3.13 mining_probe.py PATH.csv -n 10000   measure a RecipeNLG sample
"""
import argparse, ast, collections, csv, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import linkage_matcher as LM
from recipe_line_parser import parse

csv.field_size_limit(10_000_000)


class Tally:
    """Counters only. Nothing here can hold a recipe."""
    def __init__(self):
        self.recipes = 0
        self.lines = 0
        self.unparsed = 0
        self.tier = collections.Counter()          # EXACT / FORM_STRIP / DECIDED / AMBIGUOUS / ...
        self.name_hits = collections.Counter()     # normalized ingredient name -> times seen
        self.name_tier = {}                        # normalized ingredient name -> best tier
        self.rows_hit = set()                      # catalog library_ids reached

    def add(self, core, tier, rows):
        self.lines += 1
        self.tier[tier] += 1
        self.name_hits[core] += 1
        if core not in self.name_tier or tier in ("EXACT", "DECIDED"):
            self.name_tier[core] = tier
        for lid, _ in rows:
            self.rows_hit.add(lid)


MATCHED = {"EXACT", "DECIDED", "FORM_STRIP"}


def probe_lines(line_iter, cat, decided, tally, recipe_boundary=None):
    """Fold an iterator of ingredient lines into the tally. The line is not retained."""
    for line in line_iter:
        if recipe_boundary is not None and line is recipe_boundary:
            tally.recipes += 1
            continue
        core, _rules, _flags = parse(line)      # (core, rules, flags); core=='' means no ingredient
        if not core:
            tally.unparsed += 1
            tally.lines += 1
            continue
        tier, _, rows, _ = LM.match(core, cat, decided)
        tally.add(LM.fold(core), tier, rows)
        # `line` and `core` go out of scope here. Nothing downstream can see them.


def from_recipenlg(path, limit, column=None):
    """Stream the published CSV. Yields ingredient lines and drops every other column.

    ⚠️ The title, the directions and the link columns are never yielded and never stored. The
    `ingredients` column is read, split into lines, and the row is discarded."""
    with open(path, newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        want = [column] if column else ["ingredients", "NER", "ingredient"]
        col = next((c for c in want if c in (r.fieldnames or [])), None)
        if col is None:
            raise SystemExit(f"no ingredient column in {r.fieldnames}")
        n = 0
        for row in r:
            raw = row.get(col) or ""
            try:
                items = ast.literal_eval(raw) if raw.startswith("[") else raw.split("\n")
            except (ValueError, SyntaxError):
                items = raw.split("\n")
            for it in items:
                if isinstance(it, str) and it.strip():
                    yield it.strip()
            n += 1
            yield SENTINEL
            if n >= limit:
                return


SENTINEL = object()


# ⚠️ THE READER REGISTRY. A run script used to name from_recipenlg directly, which pinned every
#    mining pass to one corpus and one file format. A source is now a key here, and adding one is
#    a registry entry rather than an edit to four scripts.
#
#    'lines'   yields ingredient lines with SENTINEL between recipes, what occurrence_run,
#              pairing_run and substitution_run consume.
#    'records' yields (title, [ingredient names]) pairs, what dish_facet_run consumes.
#    'titles'  yields titles alone.
#    'slug'    the default source_slug for this reader, so --source stays optional.
#
#    ⚠️ recipenlg-2020 IS THE DEFAULT AND ITS ENTRY MUST NOT CHANGE BEHAVIOR. Every value here
#    is the value the scripts hardcoded before this registry existed.
READERS = {}


def register_reader(key, *, lines=None, records=None, titles=None, slug=None):
    """Add a corpus to the registry. Called at import by whichever module owns the format."""
    READERS[key] = {"lines": lines, "records": records, "titles": titles, "slug": slug}


def _rn_records(path, limit):
    """(title, ingredient names) for RecipeNLG. Directions and link are never touched."""
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= limit:
                return
            raw = row.get("NER") or ""
            try:
                items = ast.literal_eval(raw) if raw.startswith("[") else []
            except (ValueError, SyntaxError):
                items = []
            yield (row.get("title") or "",
                   [x for x in items if isinstance(x, str) and x.strip()])


def _rn_titles(path, limit):
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i >= limit:
                return
            yield row.get("title") or ""


register_reader("recipenlg", lines=lambda p, n: from_recipenlg(p, n, "NER"),
                records=_rn_records, titles=_rn_titles, slug="recipenlg-2020")


def reader(key):
    """The registry entry, or a SystemExit naming what is available. Never a silent default.

    """
    if key not in READERS:
        raise SystemExit(f"unknown --reader {key!r}. Registered: {sorted(READERS)}")
    return READERS[key]


def from_local(conn, limit):
    """Self-test source. The 298 local recipes, read-only, to prove the harness measures."""
    q = ("SELECT COALESCE(NULLIF(label,''), raw_text) FROM recipe_ingredients "
         "WHERE COALESCE(is_heading,0)=0 LIMIT ?")
    for (t,) in conn.execute(q, (limit,)):
        if t and t.strip():
            yield t.strip()


def report(tally, cat, label):
    distinct = len(tally.name_hits)
    matched_names = [k for k, t in tally.name_tier.items() if t in MATCHED]
    amb = [k for k, t in tally.name_tier.items() if t == "AMBIGUOUS"]
    unm = [k for k, t in tally.name_tier.items() if t not in MATCHED and t != "AMBIGUOUS"]
    occ_total = sum(tally.name_hits.values())
    occ_matched = sum(tally.name_hits[k] for k in matched_names)
    print(f"\n=== {label} ===")
    print(f"  recipes read           {tally.recipes:>9,}")
    print(f"  ingredient lines       {tally.lines:>9,}   unparsed {tally.unparsed:,}")
    print(f"  distinct names         {distinct:>9,}")
    print(f"\n  BY DISTINCT NAME (does the vocabulary overlap?)")
    print(f"    matched              {len(matched_names):>9,}  {len(matched_names)/max(1,distinct)*100:5.1f}%")
    print(f"    ambiguous            {len(amb):>9,}  {len(amb)/max(1,distinct)*100:5.1f}%")
    print(f"    unmatched            {len(unm):>9,}  {len(unm)/max(1,distinct)*100:5.1f}%")
    print(f"\n  BY OCCURRENCE (does the vocabulary overlap where it is USED?)")
    print(f"    matched              {occ_matched:>9,}  {occ_matched/max(1,occ_total)*100:5.1f}% of {occ_total:,}")
    print(f"\n  CATALOG REACH")
    print(f"    rows hit             {len(tally.rows_hit):>9,}  of {len(set(r[0] for v in cat.values() for r in v)):,}")
    print(f"\n  tiers: {dict(tally.tier)}")
    if unm:
        top = sorted(unm, key=lambda k: -tally.name_hits[k])[:15]
        print(f"\n  most-used names the catalog does NOT hold (vocabulary, not recipe text):")
        for k in top:
            print(f"    {tally.name_hits[k]:>6,}  {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", nargs="?", help="RecipeNLG CSV")
    ap.add_argument("-n", type=int, default=10000, help="recipes to sample")
    ap.add_argument("--selftest", action="store_true", help="run on the 298 local recipes instead")
    ap.add_argument("--column", help="which CSV column to read (default: ingredients)")
    ap.add_argument("--misses", type=int, default=0,
                    help="emit the top N unmatched NAMES with counts, as TSV, to stdout")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{BASE/'recipes.db'}?mode=ro", uri=True)
    cat = LM.load_catalog(conn)
    decided, problems = LM.load_decisions(cat)
    for p in problems:
        print(f"  decision problem: {p}")
    t = Tally()
    if a.selftest:
        probe_lines(from_local(conn, a.n), cat, decided, t)
        t.recipes = conn.execute(
            "SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredients").fetchone()[0]
        report(t, cat, f"SELF-TEST, the {t.recipes} local recipes")
    elif a.corpus:
        probe_lines(from_recipenlg(a.corpus, a.n, a.column), cat, decided, t,
                    recipe_boundary=SENTINEL)
        report(t, cat, f"RecipeNLG sample, {a.n:,} recipes, column={a.column or 'ingredients'}")
    else:
        raise SystemExit("give a corpus path or --selftest")
    if a.misses:
        # ⚠️ NAMES AND COUNTS ONLY. An ingredient name is a food name, not anybody's writing, and a
        #    count is a fact. No line, title or instruction is emitted here or anywhere.
        unm = [(k, v) for k, v in t.name_hits.items()
               if t.name_tier.get(k) not in MATCHED and t.name_tier.get(k) != "AMBIGUOUS"]
        unm.sort(key=lambda kv: -kv[1])
        print("\n#MISSES\tname\tcount")
        for k, v in unm[:a.misses]:
            print(f"#M\t{k}\t{v}")
        print(f"#TOTALS\tunmatched_distinct\t{len(unm)}")
        print(f"#TOTALS\tunmatched_occurrences\t{sum(v for _, v in unm)}")
        print(f"#TOTALS\tall_occurrences\t{sum(t.name_hits.values())}")
    conn.close()


if __name__ == "__main__":
    main()
