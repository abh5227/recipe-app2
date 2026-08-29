#!/usr/bin/env python3
"""build_db.py — refresh the parts of the database that seed.py owns.

The big change now that you can author recipes in the app: this script NO LONGER
wipes everything and rebuilds. Two kinds of data live side by side:

  - seed-owned: the ingredient library + the recipes written in seed.py. These are
    (re)built here from seed.py on every run.
  - app-owned: recipes you create in the app, your ratings, cook history, and your
    per-line "changes" to seed recipes. These are NEVER touched here.

So it upserts seed rows by their stable key (slug) and leaves everything else alone.
Run it with:  python3 build_db.py
"""
import csv
import datetime
import re
import sqlite3
import sys
from pathlib import Path

from seed import INGREDIENTS, RECIPES
from migrate import migrate
from import_cleanup import split_qty   # same qty->quantity+unit split as the app-row backfill
from weights import (
    normalize, parse_reference_volume, build_index, match_weight, has_volume_unit,
)
from stepscale import (
    parse_step, MARKED_SCALE, MARKED_LOCK, HEURISTIC_SCALE, GUARDED, UNITLESS,
)

BASE_DIR = Path(__file__).resolve().parent
DB = BASE_DIR / "recipes.db"
WEIGHTS_CSV = BASE_DIR / "king-arthur-staples-v2.csv"
# ⚠️ SERVER-SIDE AND GITIGNORED, UNLIKE THE WEIGHTS CHART BESIDE IT. See seed_library_names.
LIBRARY_NAMES_CSV = BASE_DIR / "library_names.csv"

# Chart rows that should NOT smart-convert volume->grams in Metric (migration 013). Keyed by
# normalize(display_name) so it matches the lookup_key seed_weights stores. Two kinds:
#   - pure cooking oils & solid fats: you pour/scoop a glug, you don't weigh it (butter is
#     the deliberate exception — it stays TRUE, since baking weighs butter);
#   - raw produce & aromatics: chopped/sliced by the cup, not a weigh-it staple.
# Everything else (flours, sugars, syrups, soft dairy/pastes incl. tomato paste, nuts,
# grated cheese, pourable liquids, chocolate, oats, dried fruit) keeps the TRUE default.
WEIGHT_CONVERT_EXCLUDE = frozenset({
    # oils & solid fats (NOT butter)
    "coconut oil", "olive oil", "vegetable oil", "lard", "vegetable shortening",
    # raw produce & aromatics
    "garlic minced", "garlic peeled and sliced", "ginger fresh sliced", "onions diced",
    "bell peppers fresh", "carrots diced", "carrots grated", "celery diced", "leeks diced",
    "mushrooms sliced", "scallions sliced", "shallots sliced", "chives fresh",
    "olives sliced", "sundried tomatoes",
})


def validate():
    """Catch references to ingredient keys that don't exist in the library."""
    problems = []
    keys = set(INGREDIENTS)
    for r in RECIPES:
        for row in r["ingredients"]:
            item = row.get("item")
            if item and item not in keys:
                problems.append(f"  recipe '{r['id']}' lists unknown ingredient '{item}'")
        for step in r["steps"]:
            if isinstance(step, dict):
                continue
            for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", step):
                key = m.group(1).strip()
                if key not in keys:
                    problems.append(f"  recipe '{r['id']}' step links unknown ingredient '{key}'")
    return problems


def has_table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _insert_lines_and_steps(conn, r):
    """Write one recipe's ingredient lines and steps (its children) from seed."""
    for pos, row in enumerate(r["ingredients"]):
        if "heading" in row:
            conn.execute(
                "INSERT INTO recipe_ingredients (recipe_id, position, is_heading, raw_text) VALUES (?,?,1,?)",
                (r["id"], pos, row["heading"]),
            )
        elif "item" in row:
            quantity, unit = split_qty(row.get("qty"))   # additive split (qty stays as-is)
            conn.execute(
                """INSERT INTO recipe_ingredients
                   (recipe_id, position, qty, quantity, unit, ingredient_id, label, note, raw_text)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    r["id"], pos, row.get("qty"), quantity, unit, row["item"],
                    row.get("label"), row.get("note"),
                    f"{row.get('qty','')} {row.get('label','')}{row.get('note','')}".strip(),
                ),
            )
        else:  # plain text line
            quantity, unit = split_qty(row.get("qty"))
            conn.execute(
                "INSERT INTO recipe_ingredients (recipe_id, position, qty, quantity, unit, raw_text) VALUES (?,?,?,?,?,?)",
                (r["id"], pos, row.get("qty"), quantity, unit, row.get("text", "")),
            )

    for pos, step in enumerate(r["steps"]):
        if isinstance(step, dict):
            conn.execute(
                "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,1,?)",
                (r["id"], pos, step["heading"]),
            )
        else:
            conn.execute(
                "INSERT INTO recipe_steps (recipe_id, position, is_heading, text) VALUES (?,?,0,?)",
                (r["id"], pos, step),
            )


def seed_content(conn):
    """Refresh seed-owned content without disturbing anything app-owned.

    created_at is preserved across the refresh (keyed by the stable slug/key), so
    the first time a row appears it's stamped, and that stamp survives every rebuild.
    Note: this runs with foreign keys OFF (set in build()), so ON DELETE CASCADE does
    not fire here — any child rows we want gone are deleted explicitly.
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ingredient_created = dict(conn.execute("SELECT id, created_at FROM ingredients"))
    recipe_created = dict(conn.execute("SELECT id, created_at FROM recipes"))

    # ---- ingredient library: upsert (never delete, to protect recipe references) ----
    # ⚠️ concept MUST BE SUPPLIED, NOT LEFT TO THE COLUMN DEFAULT (migration 031). The default is ''
    # and the partial unique index permits exactly ONE shared row at any concept, so omitting it here
    # inserts the first seed ingredient and then fails on the second with "UNIQUE constraint failed:
    # ingredients.concept". A seed key IS its concept: these ids are hand-authored name slugs.
    # owner is left NULL, which is the shared marker. Neither is touched on conflict, so a rebuild
    # never rewrites the identity of a row that already exists.
    for key, ing in INGREDIENTS.items():
        conn.execute(
            """INSERT INTO ingredients (id, name, descr, pairs, created_at, concept)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name, descr = excluded.descr, pairs = excluded.pairs""",
            (key, ing["name"], ing.get("descr"), ing.get("pairs"),
             ingredient_created.get(key) or now, key),
        )

    # seasons + regions are fully derived from the library and nothing app-owned
    # references them, so they're safe to rebuild wholesale.
    conn.execute("DELETE FROM ingredient_seasons")
    conn.execute("DELETE FROM ingredient_regions")
    conn.execute("DELETE FROM regions")

    for key, ing in INGREDIENTS.items():
        for month in ing.get("season", []):
            conn.execute(
                "INSERT INTO ingredient_seasons (ingredient_id, month) VALUES (?,?)",
                (key, month),
            )
    region_id = {}
    for ing in INGREDIENTS.values():
        for name in ing.get("regions", []):
            if name not in region_id:
                cur = conn.execute("INSERT INTO regions (name) VALUES (?)", (name,))
                region_id[name] = cur.lastrowid
    for key, ing in INGREDIENTS.items():
        for pos, name in enumerate(ing.get("regions", [])):
            conn.execute(
                "INSERT INTO ingredient_regions (ingredient_id, region_id, position) VALUES (?,?,?)",
                (key, region_id[name], pos),
            )

    # ---- seed-owned recipes (app recipes are left completely alone) ----
    seed_slugs = {r["id"] for r in RECIPES}

    # remove seed recipes that were deleted from seed.py. Their children + history
    # go too (deleted explicitly, since cascades don't fire with FK off here).
    existing_seed = [row[0] for row in conn.execute("SELECT id FROM recipes WHERE source = 'seed'")]
    for slug in existing_seed:
        if slug not in seed_slugs:
            for t in ("ratings", "cook_log", "recipe_ingredients", "recipe_steps"):
                conn.execute(f"DELETE FROM {t} WHERE recipe_id = ?", (slug,))
            conn.execute("DELETE FROM recipes WHERE id = ?", (slug,))

    for r in RECIPES:
        conn.execute(
            """INSERT INTO recipes
               (id, name, author, source_url, category, servings, prep_time,
                cook_time, total_time, descr, notes, image, uid, created_at, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'seed')
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, author=excluded.author, source_url=excluded.source_url,
                   category=excluded.category, servings=excluded.servings, prep_time=excluded.prep_time,
                   cook_time=excluded.cook_time, total_time=excluded.total_time, descr=excluded.descr,
                   notes=excluded.notes, image=excluded.image, uid=excluded.uid, source='seed'""",
            (
                r["id"], r["name"], r.get("author"), r.get("source_url"),
                r.get("category"), r.get("servings"), r.get("prep_time"),
                r.get("cook_time"), r.get("total_time"), r.get("descr"), r.get("notes"),
                r.get("image"), r.get("uid"), recipe_created.get(r["id"]) or now,
            ),
        )
        # rebuild this seed recipe's lines + steps (safe: nothing app-owned points at them)
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (r["id"],))
        conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (r["id"],))
        _insert_lines_and_steps(conn, r)


def seed_weights(conn):
    """Load the King Arthur volume->weight chart into ingredient_weights.

    Pure reference data derived entirely from the CSV (nothing app-owned points at it),
    so — like seasons/regions — it's rebuilt wholesale each run. grams_per_ml is computed
    HERE at seed time: grams / (reference volume in mL). Rows with an unparseable volume
    are skipped. If the CSV is missing, the table is left empty and the converter simply
    declines every line.

    Source: King Arthur Baking Ingredient Weight Chart (king-arthur-staples-v2.csv).
    """
    if not WEIGHTS_CSV.exists():
        print(f"Note: {WEIGHTS_CSV.name} not found — volume->weight table left empty.")
        return
    conn.execute("DELETE FROM ingredient_weights")
    with open(WEIGHTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#"))
        for row in reader:
            name = (row.get("ingredient") or "").strip()
            grams = (row.get("grams") or "").strip()
            ml = parse_reference_volume(row.get("reference_volume") or "")
            if not name or not grams or not ml:
                continue
            key = normalize(name)
            conn.execute(
                "INSERT INTO ingredient_weights "
                "(lookup_key, display_name, grams_per_ml, convert_to_grams) VALUES (?,?,?,?)",
                (key, name, float(grams) / ml, 0 if key in WEIGHT_CONVERT_EXCLUDE else 1),
            )


def seed_library_names(conn):
    """Load the ingredient library's id -> canonical-name lookup into library_names.

    Pure reference data derived entirely from the file (nothing app-owned points at it), so it is
    rebuilt wholesale each run, the same as the weights chart above. Rows missing either column are
    skipped. If the file is missing, the table is left empty.

    ⚠️ THE FILE IS SERVER-SIDE AND GITIGNORED, AND THAT IS THE FEATURE RATHER THAN A GAP. The FILE
    is ~330 KB. (This line used to say ~624 KB, which is the size of the TABLE it loads into, a
    different figure quoted here by mistake. README.md had it right.) It derives from join.db (894 MB)
    and sources.db (5.18 GB), neither of which is ever committed
    or present on a server, so it is placed by hand on a machine that has generated it. A fresh clone
    and CI therefore get an EMPTY table, and the add-on-save gate (stage 5) can only match a row that
    is present. With no rows it never fires and the save path keeps behaving exactly as it does today.
    The feature self-disables wherever the file is absent, which is why nothing here raises on a miss.

    ⚠️ AN ABSENT FILE LEAVES EXISTING ROWS ALONE rather than clearing them, because the early return
    happens before the DELETE. Same semantics as seed_weights. Removing the file does not empty a
    table that was already loaded, so a rebuild on a machine that has since lost the file keeps the
    last-loaded lookup instead of silently disabling the feature mid-flight.

    ⚠️ A DUPLICATE library_id RAISES rather than being skipped, and the difference from the missing-
    column skip is deliberate. An incomplete row carries no data. A duplicate carries CONFLICTING
    data, and quietly keeping whichever came first would make the lookup depend on file order. The
    DELETE has not been committed at that point, so a raise leaves the database untouched.

    ⚠️ POSTGRES IS NOT POPULATED BY THIS, AND THAT IS A DEFERRED TASK, NOT AN OVERSIGHT. build_db.py
    is raw-SQLite by design and is never run against PG (docs/migration-plan.md), so on Postgres the
    Alembic revision creates library_names and nothing fills it. An empty table there self-disables
    the feature exactly as an absent file does, so PG keeps today's behavior rather than
    half-enabling. A dialect-neutral loader is a separate decision.

    Format: a two-column CSV, `library_id,canonical`, with `#` comment lines allowed. Two columns
    because step-link promotion is dropped and nothing needs the reverse slug lookup (migration 029).
    ⚠️ THE GENERATOR IS build_library.write_library_names, shipped in 5aa257a. It writes this file
    from build_library's kept rowset. (This line used to say nothing in the repo generated the file,
    which was true when written.) Running it needs join.db and sources.db, so the file is produced on
    a machine that has them and placed here by hand, and it stays gitignored and private.
    """
    if not LIBRARY_NAMES_CSV.exists():
        print(f"Note: {LIBRARY_NAMES_CSV.name} not found — library-name lookup left empty.")
        return
    conn.execute("DELETE FROM library_names")
    n = 0
    with open(LIBRARY_NAMES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#"))
        for row in reader:
            library_id = (row.get("library_id") or "").strip()
            canonical = (row.get("canonical") or "").strip()
            if not library_id or not canonical:
                continue
            conn.execute("INSERT INTO library_names (library_id, canonical) VALUES (?,?)",
                         (library_id, canonical))
            n += 1
    print(f"Library-name lookup: {n:,} rows loaded from {LIBRARY_NAMES_CSV.name}.")


def compute_coverage(conn):
    """Coverage of the volume->weight converter, computed live from the data (no stored
    counters). Uses the same matcher as the API (weights), so the report can't drift from
    what the converter actually does. Returns (n_distinct, n_matched, unmatched, per_recipe):
      - distinct recipe ingredients grouped by normalized name;
      - unmatched: [(name, line_count), ...] most-used first;
      - per_recipe: {recipe_name: [total_lines, wont_convert_lines]}.
    A line "converts" only if its name matches the table AND its quantity is a volume.
    """
    conn.row_factory = sqlite3.Row
    index = build_index(
        conn.execute(
            "SELECT lookup_key, display_name, grams_per_ml FROM ingredient_weights"
        ).fetchall()
    )
    lines = conn.execute(
        """SELECT r.name AS recipe, ri.label, ri.raw_text, ri.qty
           FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id
           WHERE ri.is_heading = 0"""
    ).fetchall()

    distinct = {}
    per_recipe = {}
    for ln in lines:
        name = (ln["label"] or ln["raw_text"] or "").strip()
        key = normalize(name)
        rec = per_recipe.setdefault(ln["recipe"], [0, 0])
        rec[0] += 1
        if not key:
            rec[1] += 1
            continue
        matched = match_weight(name, index) is not None
        d = distinct.setdefault(key, {"count": 0, "matched": matched})
        d["count"] += 1
        if not (matched and has_volume_unit(ln["qty"])):
            rec[1] += 1

    n_distinct = len(distinct)
    n_matched = sum(1 for d in distinct.values() if d["matched"])
    unmatched = sorted(
        ((key, d["count"]) for key, d in distinct.items() if not d["matched"]),
        key=lambda t: (-t[1], t[0]),
    )
    return n_distinct, n_matched, unmatched, per_recipe


def print_coverage(coverage):
    """Print the conversion-coverage section of the build report."""
    n_distinct, n_matched, unmatched, per_recipe = coverage
    print(
        f"\nConversion coverage (volume -> weight): {n_matched} of {n_distinct} distinct "
        f"recipe ingredients match the weight table."
    )
    if unmatched:
        print("  Unmatched (most-used first — add these to the chart for the most gain):")
        for name, count in unmatched:
            print(f"    {name}  ({count} line{'' if count == 1 else 's'})")
    print("  Lines that won't convert, per recipe:")
    for recipe in sorted(per_recipe):
        total, wont = per_recipe[recipe]
        print(f"    {recipe}: {wont} of {total}")


def compute_step_coverage(conn):
    """Method-text scaling coverage per recipe, from the SAME parser the live renderer uses
    (stepscale.parse_step) — so the report reflects exactly what the page does. Build-time
    only; counts span categories so a bulk import is auditable. No markup is added to the seed
    recipes — the guard + heuristic carry them, and this shows where markup would help."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT r.name AS recipe, s.text
           FROM recipe_steps s JOIN recipes r ON r.id = s.recipe_id
           WHERE s.is_heading = 0
           ORDER BY r.name, s.position"""
    ).fetchall()
    per_recipe = {}
    for row in rows:
        c = per_recipe.setdefault(
            row["recipe"],
            {"marked_scale": 0, "marked_lock": 0, "heuristic": 0, "guarded": 0, "unitless": []},
        )
        for sp in parse_step(row["text"]):
            cat = sp["category"]
            if cat == MARKED_SCALE:
                c["marked_scale"] += 1
            elif cat == MARKED_LOCK:
                c["marked_lock"] += 1
            elif cat == HEURISTIC_SCALE:
                c["heuristic"] += 1
            elif cat == GUARDED:
                c["guarded"] += 1
            elif cat == UNITLESS:
                c["unitless"].append(sp["text"])
    return per_recipe


def print_step_coverage(per_recipe):
    """Print the method-text scaling section of the build report."""
    print("\nMethod-text scaling (Phase 1d) — markup > guard > heuristic:")
    for recipe in sorted(per_recipe):
        c = per_recipe[recipe]
        u = c["unitless"]
        ulabel = f"{len(u)} ({', '.join(u)})" if u else "0"
        print(
            f"  {recipe}: marked-scale {c['marked_scale']}, marked-lock {c['marked_lock']}, "
            f"heuristic-scale {c['heuristic']}, guarded {c['guarded']}, unitless-for-review {ulabel}"
        )


def build():
    problems = validate()
    if problems:
        print("Found references to ingredients that aren't in INGREDIENTS:")
        print("\n".join(problems))
        print("\nFix the keys (or add the ingredients) and run again.")
        sys.exit(1)

    # One-time transition: a database made by the OLD build_db has no migration
    # tracking and (by definition) no user data yet, so it's safe to discard once
    # and let migrations rebuild it cleanly.
    if DB.exists():
        probe = sqlite3.connect(DB)
        legacy = not has_table(probe, "schema_migrations")
        probe.close()
        if legacy:
            print("Old-format database found (pre-migrations) — recreating it once.")
            DB.unlink()

    # 1) make sure the schema exists / is current (this never deletes data)
    migrate(verbose=True)

    # 2) refresh seed content only. We briefly suspend foreign keys for the bulk
    #    upsert (a maintenance operation), then turn them back on and re-verify.
    #    The pragma must be set OUTSIDE a transaction, so the ordering matters.
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = OFF")
    seed_content(conn)
    seed_weights(conn)
    seed_library_names(conn)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    orphans = conn.execute("PRAGMA foreign_key_check").fetchall()

    n_seed = conn.execute("SELECT COUNT(*) FROM recipes WHERE source='seed'").fetchone()[0]
    n_app = conn.execute("SELECT COUNT(*) FROM recipes WHERE source='app'").fetchone()[0]
    n_ings = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    n_cooks = conn.execute("SELECT COUNT(*) FROM cook_log").fetchone()[0]
    n_ratings = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
    n_weights = conn.execute("SELECT COUNT(*) FROM ingredient_weights").fetchone()[0]

    coverage = compute_coverage(conn)
    step_coverage = compute_step_coverage(conn)
    conn.close()

    print(
        f"Seed content refreshed: {n_seed} seed recipes, {n_ings} ingredients, "
        f"{n_weights} ingredient weights."
    )
    print(
        f"Left untouched (app-owned): {n_app} app recipe(s), {n_cooks} cook-log "
        f"entries, {n_ratings} rating(s)."
    )

    if orphans:
        print(
            "\nNote: some saved data points at recipes that no longer exist:\n  "
            + "\n  ".join(str(o) for o in orphans)
        )

    print_coverage(coverage)
    print_step_coverage(step_coverage)


if __name__ == "__main__":
    build()
