"""Dialect-neutral test seed + truncate-reseed primitive for the Postgres test DB (Stage 2c-1).

build_db.seed_content is SQLite-coupled (cur.lastrowid, PRAGMA foreign_keys OFF/ON,
PRAGMA foreign_key_check), so it can't seed Postgres. This module loads the SAME logical seed
the SQLite harness builds — INGREDIENTS + PEOPLE (seed.py), TEST_RECIPES (fixtures.py), the
King-Arthur weights CSV — via SQLAlchemy Core inserts on models.py's tables: no lastrowid
(regions capture their generated id via result.inserted_primary_key), no PRAGMA. It runs on any
dialect; Stage 2c uses it against the Postgres test DB (schema from `alembic upgrade head`).

Transformations are REUSED from the production seed path (build_db.WEIGHT_CONVERT_EXCLUDE +
WEIGHTS_CSV, weights.normalize/parse_reference_volume, import_cleanup.split_qty) so the seeded
state matches build_db.build() logically. NOT collected by pytest (not test_*.py).
"""
import csv
import datetime
import sys
from pathlib import Path

from sqlalchemy import insert, text

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import models
from models import (
    Ingredient, IngredientSeason, Region, IngredientRegion, Person,
    Recipe, RecipeIngredient, RecipeStep, ingredient_weights,
)
from seed import INGREDIENTS, PEOPLE
from fixtures import TEST_RECIPES
from build_db import WEIGHT_CONVERT_EXCLUDE, WEIGHTS_CSV
from weights import normalize, parse_reference_volume
from import_cleanup import split_qty


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _insert_lines_and_steps(conn, r):
    """Mirror build_db._insert_lines_and_steps, dialect-neutral (Core). Same 3 ingredient branches
    (heading / library item / plain text) and same raw_text construction + qty->quantity/unit split."""
    ri = RecipeIngredient.__table__
    for pos, row in enumerate(r["ingredients"]):
        if "heading" in row:
            conn.execute(insert(ri).values(recipe_id=r["id"], position=pos, is_heading=1, raw_text=row["heading"]))
        elif "item" in row:
            quantity, unit = split_qty(row.get("qty"))
            conn.execute(insert(ri).values(
                recipe_id=r["id"], position=pos, qty=row.get("qty"), quantity=quantity, unit=unit,
                ingredient_id=row["item"], label=row.get("label"), note=row.get("note"),
                raw_text=f"{row.get('qty','')} {row.get('label','')}{row.get('note','')}".strip(),
            ))
        else:
            quantity, unit = split_qty(row.get("qty"))
            conn.execute(insert(ri).values(
                recipe_id=r["id"], position=pos, qty=row.get("qty"), quantity=quantity, unit=unit,
                raw_text=row.get("text", ""),
            ))
    rs = RecipeStep.__table__
    for pos, step in enumerate(r["steps"]):
        # the Core-table column key is its DB name "text" (the "body" name is only the ORM attribute)
        if isinstance(step, dict):
            conn.execute(insert(rs).values({"recipe_id": r["id"], "position": pos, "is_heading": 1, "text": step["heading"]}))
        else:
            conn.execute(insert(rs).values({"recipe_id": r["id"], "position": pos, "is_heading": 0, "text": step}))


def _seed_weights(conn):
    """Mirror build_db.seed_weights: load the CSV, compute grams_per_ml = grams / reference-mL,
    convert_to_grams=0 for the exclude set. Skips rows with unparseable volume. Same source + math."""
    if not WEIGHTS_CSV.exists():
        return 0
    n = 0
    with open(WEIGHTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#"))
        for row in reader:
            name = (row.get("ingredient") or "").strip()
            grams = (row.get("grams") or "").strip()
            ml = parse_reference_volume(row.get("reference_volume") or "")
            if not name or not grams or not ml:
                continue
            key = normalize(name)
            conn.execute(insert(ingredient_weights).values(
                lookup_key=key, display_name=name, grams_per_ml=float(grams) / ml,
                convert_to_grams=0 if key in WEIGHT_CONVERT_EXCLUDE else 1,
            ))
            n += 1
    return n


def seed_all(conn):
    """Load the full test seed into `conn` (a SQLAlchemy connection, any dialect) via Core inserts.
    Same logical state build_db.build() produces on SQLite: 36 ingredients + their seasons/regions,
    2 people, 5 TEST_RECIPES (source='seed') with lines+steps, and the weights chart."""
    now = _now()
    # ingredient library
    for key, ing in INGREDIENTS.items():
        conn.execute(insert(Ingredient.__table__).values(
            id=key, name=ing["name"], descr=ing.get("descr"), pairs=ing.get("pairs"), created_at=now))
    # seasons (derived from the library)
    for key, ing in INGREDIENTS.items():
        for month in ing.get("season", []):
            conn.execute(insert(IngredientSeason.__table__).values(ingredient_id=key, month=month))
    # regions: insert each once, capturing its generated id via inserted_primary_key (NO lastrowid)
    region_id = {}
    for ing in INGREDIENTS.values():
        for name in ing.get("regions", []):
            if name not in region_id:
                res = conn.execute(insert(Region.__table__).values(name=name))
                region_id[name] = res.inserted_primary_key[0]
    for key, ing in INGREDIENTS.items():
        for pos, name in enumerate(ing.get("regions", [])):
            conn.execute(insert(IngredientRegion.__table__).values(
                ingredient_id=key, region_id=region_id[name], position=pos))
    # people (configuration, like the ingredient library)
    for pos, person in enumerate(PEOPLE):
        conn.execute(insert(Person.__table__).values(
            id=person["id"], name=person["name"], color=person["color"], position=pos))
    # recipes + their lines/steps (seeded as source='seed', matching the SQLite harness)
    for r in TEST_RECIPES:
        conn.execute(insert(Recipe.__table__).values(
            id=r["id"], name=r["name"], author=r.get("author"), source_url=r.get("source_url"),
            category=r.get("category"), servings=r.get("servings"), prep_time=r.get("prep_time"),
            cook_time=r.get("cook_time"), total_time=r.get("total_time"), descr=r.get("descr"),
            notes=r.get("notes"), image=r.get("image"), uid=r.get("uid"), created_at=now, source="seed"))
        _insert_lines_and_steps(conn, r)
    _seed_weights(conn)


def reset_and_seed(engine):
    """Truncate-and-reseed isolation primitive for the Postgres test DB: TRUNCATE every seed/data
    table (RESTART IDENTITY resets the SERIAL sequences for deterministic IDs; CASCADE ignores FK
    order), then reseed — all in one transaction. Leaves alembic_version (the Alembic stamp) alone.
    Assumes the schema already exists (alembic upgrade head)."""
    names = [t.name for t in models.Base.metadata.sorted_tables if t.name != "schema_migrations"]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))
        seed_all(conn)
