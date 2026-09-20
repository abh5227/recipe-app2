#!/usr/bin/env python3
"""load_dish_facets.py - put dish_facet_run.py's JSON into the eight facet tables.

⚠️ SEPARATE FROM THE MIGRATION and separate from the run. migrations/038 creates the tables, the
run produces an inspectable file, and this is the only step that writes rows. A clone without the
corpus correctly ends up with eight empty tables.

⚠️ IT REFUSES AN ID THAT IS NOT A CATALOG ROW. base and accompaniment hold library_ids, and an
orphan would mean the catalog moved under the facets. Same rule as load_relations.py: stop rather
than skip, because a skipped row is a silent no-op.

⚠️ IT REFUSES A DISH THAT STILL CARRIES A BRAND OR A NAME. mined_dish.dish is the one free-text
exception in the mined schema and the grant is conditional on the cleaning. Checking here as well
as in the test means a bad load never reaches the database in the first place.

⚠️ THE FLOOR LIVES HERE, NOT IN THE SCHEMA, AND THAT IS DELIBERATE. Boundary (c) says a row at
n=1 is not an aggregate. The right number is a judgement rather than a fact, so it sits in one
constant that can move, and tests/test_mining_boundaries.py::MIN_N_FLOORS holds the loaded tables
to whatever it currently is. Measured at the default of 10: the 716,535 dish rows at n=1 go,
which is 81.8% of them and 253 of the 260 rows carrying a personal name. A floor cleans this
column better than any regex can, since a name has to appear in 10 separate recipes to survive.

⚠️ EVERYTHING BELOW THE FLOOR STAYS IN THE JSON. The file is the inspectable record and keeps
every row the extractor found. Raising or lowering the floor is a reload, not a re-extract.
"""
import argparse, json, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import brand_guard as BG
import dish_facets as F

# ⚠️ THE DISH FLOOR IS 2, AND IT IS A DELIBERATE CHOICE RATHER THAN A LOOSE ONE. It was 10.
#
#    A dish seen twice is a thin record and it is kept on purpose, as an ELEVATION HOOK. `matar
#    paneer` at 4, `mongolian chicken` at 8 and `chana chaat` at 2 are real dishes that this
#    English-language corpus happens to barely name. When a second source lands, a real regional
#    dish gains recipes across sources and rises. A one-off like `ahmad rashad banana pancake`
#    stays at 2 in one source forever, and THAT is the evidence that makes it safe to cut.
#
#    ⚠️ CUTTING IS DEFERRED ON PURPOSE, NOT FORGOTTEN. The alternative was filtering junk now by
#    guessing at personal names, and the probe written to do that matched `memphis style pork ribs`
#    and `ethiopian style samosa`. A filter that cannot tell a cuisine from a person is not a
#    filter. source_slug is in every mined primary key, so "still n=2 in one source after N
#    sources" is a query rather than a guess. See docs/open-library-queues.md section 12.
#
#    ⚠️ BOUNDARY (c) STILL HOLDS. A row at n=2 is an aggregate over two recipes. n=1 is what the
#    boundary forbids and the floor never admits it.
FLOOR = 2           # ⚠️ the DISH floor, and the floor on the seven vocabulary/id facet tables.

# ⚠️ THE PROFILE CELL FLOOR IS ITS OWN RULE, and it is not the dish floor. Keep an ingredient cell
#    if it appears in at least 3 recipes of the dish, OR in at least 2 AND at least 10% of them.
#
#    The share arm exists because a flat count punishes a rare dish for being rare. `doro wat` is
#    Ethiopian and appears 10 times in 2,231,142 recipes. At a flat cell floor of 10 it stored
#    nothing at all, along with 3,322 other dishes.
#
#    ⚠️ THE `n >= 2` CLAUSE IS THE PART THAT LOOKS REDUNDANT AND IS NOT. Without it, 1 of 10 IS
#    10%, so every one of the 1,871 dishes sitting at exactly 10 recipes kept 100% of its cells
#    unfiltered. That was 25,166 rows at n = 1, and boundary (c) says a row at n = 1 is not an
#    aggregate. With the clause the minimum n in the table is 2, which is what
#    MIN_N_FLOORS["mined_dish_ingredient"] declares.
def CELL(n, n_dish):
    return n >= 3 or (n >= 2 and n / n_dish >= 0.10)

TABLES = {"form": ("mined_dish_form", "dish_type"),
          "base": ("mined_dish_base", "library_id"),
          "method": ("mined_dish_method", "method"),
          "diet": ("mined_dish_diet", "diet"),
          "structural": ("mined_dish_structural", "structural"),
          "appliance": ("mined_dish_appliance", "appliance"),
          "accompaniment": ("mined_dish_accompaniment", "library_id"),
          # migration 043. A source whose run produces neither key simply loads no rows for them.
          "cuisine": ("mined_dish_cuisine", "cuisine"),
          "course": ("mined_dish_course", "course")}


# ⚠️ THE FLOOR IS ON THE COMBINED COUNT, NOT THE PER-SOURCE COUNT, and the owner ruled it so.
#    A cell is not thin because ONE of its sources is small. `pecan pie` has 3,110 RecipeNLG
#    recipes and 2 Wikibooks ones, and judging the Wikibooks row on its own 2 against a floor
#    meant for a whole corpus discarded 336 of the 480 dishes the two sources actually share.
#
#    Measured on the Wikibooks load: per-source keeps 257 dishes and 768 profile cells, combined
#    keeps 1,721 dishes and 8,175 cells.
#
#    ⚠️ BOUNDARY (c) STILL HOLDS, AND IT ALWAYS MEANT THE FACT RATHER THAN THE ROW. "A row at
#    n=1 is not an aggregate" is a claim about evidence: one recipe cannot support a stored fact.
#    A Wikibooks row at n=1 sitting beside a RecipeNLG row at n=500 for the same dish and
#    ingredient is one fact carrying 501 recipes, split across two rows because source_slug is in
#    the key. Reading the floor per row would have been reading the storage layout, not the
#    evidence. tests/test_mining_boundaries.py checks the combined count for this reason.
#
#    A source loaded ALONE is unaffected: with nothing else in the table the combined count is
#    its own, which is why RecipeNLG's 159,496 dishes are identical before and after this change.
# ⚠️ CUISINE AND COURSE ARE ASSERTED, NOT COUNTED, AND THEIR FLOOR IS 1 FOR THAT REASON.
#    Every other facet is a FREQUENCY: mined_dish_diet holds `vegan` at n=5 because five recipe
#    titles said vegan, and n measures how much evidence there is. A cuisine row is different in
#    kind. An editor categorized the page as Thai, once, and `n` records how many pages of that
#    dish carry the tag. That is a count of PAGES, not of evidence, and on a 3,774-recipe source
#    where nearly every dish appears once it is structurally 1 no matter how certain the claim.
#
#    ⚠️ MEASURED, AND THE NUMBER IS WHY THIS IS NOT A CONVENIENCE. At a floor of 2 the cuisine
#    facet keeps 66 rows and 32 values out of 1,047 rows and 114 values. 82 of the 114 cuisines
#    disappear completely, chinese, thai, louisiana and caribbean among them. A table that has
#    lost Chinese food is not a populated facet, and the owner's ruling was to keep the values
#    across all five granularity levels because coarse and true beats missing.
#
#    ⚠️ THE DISH STILL HAS TO CLEAR THE COMBINED FLOOR OF 2. The claim rides on an attested dish,
#    so nothing here admits a dish that one page invented. Only the assertion about that dish is
#    allowed to rest on a single editor, which is the only place an assertion can rest.
#    tests/test_mining_boundaries.MIN_N_FLOORS declares both at 1 so the exception stays countable.
FLOOR_BY_TABLE = {"mined_dish_cuisine": 1, "mined_dish_course": 1}


def prior(conn, table, keys, slug):
    """SUM(n) per key across every source EXCEPT this one. Empty table means an empty dict."""
    cols = ", ".join(keys)
    try:
        rows = conn.execute(f"SELECT {cols}, SUM(n) FROM {table} WHERE source_slug <> ? "
                            f"GROUP BY {cols}", (slug,)).fetchall()
    except Exception:
        return {}
    return {(r[0] if len(keys) == 1 else tuple(r[:-1])): r[-1] for r in rows}


def load(db, path, dry=False, floor=FLOOR):
    d = json.load(open(path))
    slug = d["source_slug"]
    conn = sqlite3.connect(db)
    ids = {r[0] for r in conn.execute("SELECT library_id FROM library_names")}
    chk = BG.catalog_name_check(conn)
    brands = BG.load_brands()

    # ⚠️ THE FLOOR IS APPLIED BEFORE ANY CHECK, so the checks below run on what will actually be
    #    stored rather than on rows that are about to be dropped.
    pd = prior(conn, "mined_dish", ["dish_id"], slug)
    keep = {x["dish_id"] for x in d["dishes"] if x["n"] + pd.get(x["dish_id"], 0) >= floor}
    dishes = [x for x in d["dishes"] if x["dish_id"] in keep]
    facets = {}
    for k, (table, col) in TABLES.items():
        pf = prior(conn, table, ["dish_id", col], slug)
        fl = FLOOR_BY_TABLE.get(table, floor)
        facets[k] = [r for r in d["facets"].get(k, [])
                     if r["dish_id"] in keep
                     and r["n"] + pf.get((r["dish_id"], r["value"]), 0) >= fl]
    pc = prior(conn, "mined_dish_ingredient", ["dish_id", "library_id"], slug)
    profiles = [r for r in d.get("profiles", [])
                if r["dish_id"] in keep
                and CELL(r["n"] + pc.get((r["dish_id"], r["library_id"]), 0),
                         r["n_dish"] + pd.get(r["dish_id"], 0))]
    print(f"  dish floor: COMBINED n >= {floor}: {len(dishes):,} of {len(d['dishes']):,} dishes "
          f"kept ({sum(x['n'] for x in dishes):,} recipes from this source)")
    print(f"  cell floor, on the COMBINED count: {len(profiles):,} profile cells, "
          f"min n from this source = {min((r['n'] for r in profiles), default=0)}")

    orphans = set()
    for facet in ("base", "accompaniment"):
        for r in facets[facet]:
            if r["value"] not in ids:
                orphans.add(r["value"])
    for r in profiles:
        if r["library_id"] not in ids:
            orphans.add(r["library_id"])
    if orphans:
        raise SystemExit(f"REFUSED: {len(orphans)} facet ids are not catalog rows, e.g. "
                         f"{sorted(orphans)[:5]}. The catalog moved under these facets.")

    thin = [x for x in dishes if x["n"] + pd.get(x["dish_id"], 0) < floor]
    if thin:
        raise SystemExit(f"REFUSED: {len(thin)} rows sit under the COMBINED floor after "
                         f"filtering. Boundary (c).")

    import re
    NAME = re.compile(r"(?<![\w-])(?:aunt|uncle|grandma|granny|nana|mrs|mr|miss|chef|grandmother|mom|"
                      r"moms|mother|mama|dad|dads|daddy)(?![\w-])", re.I)
    dirty = [x["dish"] for x in dishes
             if BG.classify(x["dish"], brands=brands, is_catalog_name=chk)[0] == "brand"
             or NAME.search(x["dish"])]
    if dirty:
        raise SystemExit(f"REFUSED: {len(dirty)} dish values still carry a brand or a personal "
                         f"name, e.g. {dirty[:5]}. The free-text exception is conditional on the "
                         f"cleaning. Fix the run rather than the table.")

    rows = {"mined_dish": [(x["dish_id"], x["dish"], x["n"], slug) for x in dishes]}
    for facet, (table, col) in TABLES.items():
        rows[table] = [(r["dish_id"], r["value"], r["n"], slug) for r in facets[facet]]
    print(f"  {len(rows['mined_dish']):,} dishes, 0 orphans, 0 dirty")
    rows["mined_dish_ingredient"] = [(r["dish_id"], r["library_id"], r["n"], r["n_dish"], slug)
                                     for r in profiles]
    for t in sorted(rows):
        if t != "mined_dish":
            print(f"    {t:<28}{len(rows[t]):>9,} rows")
    if dry:
        print("  dry run, nothing written")
        return
    try:
        conn.execute("BEGIN")
        for t in rows:
            conn.execute(f"DELETE FROM {t} WHERE source_slug=?", (slug,))
        conn.executemany("INSERT INTO mined_dish (dish_id,dish,n,source_slug) VALUES (?,?,?,?)",
                         rows["mined_dish"])
        for facet, (table, col) in TABLES.items():
            conn.executemany(f"INSERT INTO {table} (dish_id,{col},n,source_slug) "
                             f"VALUES (?,?,?,?)", rows[table])
        conn.executemany("INSERT INTO mined_dish_ingredient "
                         "(dish_id,library_id,n,n_dish,source_slug) VALUES (?,?,?,?,?)",
                         rows["mined_dish_ingredient"])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise
    for t in sorted(rows):
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE source_slug=?", (slug,)).fetchone()[0]
        assert n == len(rows[t]), f"{t}: wrote {n}, expected {len(rows[t])}"
    print("  committed, every table verified against the file")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="?", default="previews/dish-facets.json")
    ap.add_argument("--db", default=str(BASE / "recipes.db"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--floor", type=int, default=FLOOR)
    a = ap.parse_args()
    load(a.db, a.json, a.dry_run, a.floor)
