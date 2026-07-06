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

from seed import INGREDIENTS, RECIPES, PEOPLE
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
    for key, ing in INGREDIENTS.items():
        conn.execute(
            """INSERT INTO ingredients (id, name, descr, pairs, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name, descr = excluded.descr, pairs = excluded.pairs""",
            (key, ing["name"], ing.get("descr"), ing.get("pairs"),
             ingredient_created.get(key) or now),
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

    # ---- people (configuration, like the ingredient library): upsert from seed.py ----
    for pos, person in enumerate(PEOPLE):
        conn.execute(
            """INSERT INTO people (id, name, color, position) VALUES (?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name, color = excluded.color, position = excluded.position""",
            (person["id"], person["name"], person["color"], pos),
        )
    # drop anyone removed from seed.py, along with their saved changes (FK is off here,
    # so the cascade doesn't fire — delete the child rows explicitly).
    seed_people = {p["id"] for p in PEOPLE}
    for pid in [row[0] for row in conn.execute("SELECT id FROM people")]:
        if pid not in seed_people:
            conn.execute("DELETE FROM recipe_line_changes WHERE person_id = ?", (pid,))
            conn.execute("DELETE FROM recipe_additions    WHERE person_id = ?", (pid,))
            conn.execute("DELETE FROM people               WHERE id = ?", (pid,))

    # ---- seed-owned recipes (app recipes are left completely alone) ----
    seed_slugs = {r["id"] for r in RECIPES}

    # remove seed recipes that were deleted from seed.py. Their children + history
    # go too (deleted explicitly, since cascades don't fire with FK off here).
    existing_seed = [row[0] for row in conn.execute("SELECT id FROM recipes WHERE source = 'seed'")]
    for slug in existing_seed:
        if slug not in seed_slugs:
            for t in ("ratings", "cook_log", "recipe_line_changes", "recipe_additions",
                      "recipe_ingredients", "recipe_steps"):
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
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    orphans = conn.execute("PRAGMA foreign_key_check").fetchall()

    n_seed = conn.execute("SELECT COUNT(*) FROM recipes WHERE source='seed'").fetchone()[0]
    n_app = conn.execute("SELECT COUNT(*) FROM recipes WHERE source='app'").fetchone()[0]
    n_ings = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    n_people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    n_cooks = conn.execute("SELECT COUNT(*) FROM cook_log").fetchone()[0]
    n_ratings = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
    n_changes = conn.execute("SELECT COUNT(*) FROM recipe_line_changes").fetchone()[0]
    n_additions = conn.execute("SELECT COUNT(*) FROM recipe_additions").fetchone()[0]
    n_weights = conn.execute("SELECT COUNT(*) FROM ingredient_weights").fetchone()[0]

    # A line edit/removal is stored by line position, so reordering or trimming a seed
    # recipe's ingredients in seed.py can leave one pointing at the wrong line, or at a
    # line that's gone. List where each one landed (per person) so you can eyeball it,
    # and mark with [!] any that clearly no longer fit. (Additions aren't position-based,
    # so they can't drift this way and aren't listed here.)
    change_rows = conn.execute(
        """SELECT r.name, pe.name, c.position, c.kind, c.new_qty,
                  ri.is_heading, ri.qty, ri.label, ri.raw_text
           FROM recipe_line_changes c
           JOIN recipes r  ON r.id  = c.recipe_id
           JOIN people  pe ON pe.id = c.person_id
           LEFT JOIN recipe_ingredients ri
                  ON ri.recipe_id = c.recipe_id AND ri.position = c.position
           ORDER BY r.name, pe.name, c.position"""
    ).fetchall()

    # An addition can name a section (a heading's text). If that heading is later renamed
    # or removed in seed.py, the addition no longer matches and quietly falls to the bottom
    # of the list. List those so you can re-point them.
    orphan_additions = conn.execute(
        """SELECT r.name, pe.name, a.section, a.raw_text
           FROM recipe_additions a
           JOIN recipes r  ON r.id  = a.recipe_id
           JOIN people  pe ON pe.id = a.person_id
           WHERE a.section IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM recipe_ingredients ri
                 WHERE ri.recipe_id = a.recipe_id AND ri.is_heading = 1 AND ri.raw_text = a.section
             )
           ORDER BY r.name, pe.name, a.id"""
    ).fetchall()
    coverage = compute_coverage(conn)
    step_coverage = compute_step_coverage(conn)
    conn.close()

    print(
        f"Seed content refreshed: {n_seed} seed recipes, {n_ings} ingredients, "
        f"{n_people} people, {n_weights} ingredient weights."
    )
    print(
        f"Left untouched (app-owned): {n_app} app recipe(s), {n_cooks} cook-log "
        f"entries, {n_ratings} rating(s), {n_changes} line change(s), {n_additions} addition(s)."
    )

    if change_rows:
        print("\nSaved per-person line changes are attached to these ingredient lines —")
        print("give them a glance; a line marked [!] may have shifted out of place:")
        current = None
        for recipe_name, person_name, position, kind, new_qty, is_heading, qty, label, raw_text in change_rows:
            if recipe_name != current:
                current = recipe_name
                print(f"  {recipe_name}")
            change = f'set quantity "{new_qty}"' if kind == "edit" else "removed this line"
            if is_heading is None:
                print(f"    [!] {person_name} \u00b7 line {position}: no ingredient there now -> {change}")
            elif is_heading:
                print(f"    [!] {person_name} \u00b7 line {position}: now a section heading -> {change}")
            else:
                text = f"{qty or ''} {label or raw_text or ''}".strip()
                print(f"    {person_name} \u00b7 line {position}: \"{text}\"  ->  {change}")

    if orphan_additions:
        print("\nThese added ingredients name a section that no longer exists (so they now")
        print("sit at the bottom of the list) — re-point them in the app if you like:")
        current = None
        for recipe_name, person_name, section, raw_text in orphan_additions:
            if recipe_name != current:
                current = recipe_name
                print(f"  {recipe_name}")
            print(f"    [!] {person_name} \u00b7 \"{raw_text}\" -> section \"{section}\" is gone")

    if orphans:
        print(
            "\nNote: some saved data points at recipes that no longer exist:\n  "
            + "\n  ".join(str(o) for o in orphans)
        )

    print_coverage(coverage)
    print_step_coverage(step_coverage)


if __name__ == "__main__":
    build()
