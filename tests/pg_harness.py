"""Dialect-neutral test seed + truncate-reseed primitive for the Postgres test DB (Stage 2c-1).

build_db.seed_content is SQLite-coupled (cur.lastrowid, PRAGMA foreign_keys OFF/ON,
PRAGMA foreign_key_check), so it can't seed Postgres. This module loads the SAME logical seed
the SQLite harness builds — INGREDIENTS (seed.py), TEST_RECIPES (fixtures.py), the
King-Arthur weights CSV — via SQLAlchemy Core inserts on models.py's tables: no lastrowid
(regions capture their generated id via result.inserted_primary_key), no PRAGMA. It runs on any
dialect; Stage 2c uses it against the Postgres test DB (schema from `alembic upgrade head`).

Transformations are REUSED from the production seed path (build_db.WEIGHT_CONVERT_EXCLUDE +
WEIGHTS_CSV, weights.normalize/parse_reference_volume, import_cleanup.split_qty) so the seeded
state matches build_db.build() logically. NOT collected by pytest (not test_*.py).
"""
import csv
import datetime
import os
import sys
from pathlib import Path

from sqlalchemy import insert, text

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import models
from models import (
    Ingredient, IngredientSeason, Region, IngredientRegion,
    Recipe, RecipeIngredient, RecipeStep, ingredient_weights,
)
# ⚠️ INGREDIENTS COMES FROM THE FIXTURES, NOT FROM seed.py (seed project, stage A). This module
# does `from X import Y`, which binds a name in THIS module, so make_kitchen's rebind of
# build_db.INGREDIENTS cannot reach it. Importing the fixture directly is what keeps the PG
# seed and the SQLite seed on the same data once seed.py is emptied. Aliased so the seed_all
# body below reads unchanged.
from fixtures import TEST_INGREDIENTS as INGREDIENTS
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
    5 TEST_RECIPES (source='seed') with lines+steps, and the weights chart."""
    now = _now()
    # ingredient library
    # ⚠️ concept MUST BE SUPPLIED, exactly as build_db.seed_content supplies it (migration 031). The
    # column defaults to '' and idx_ingredients_shared_concept is UNIQUE(concept) WHERE owner IS NULL,
    # so leaving it to the default seeds the first ingredient and then fails on the second with
    # "duplicate key value violates unique constraint". A seed key IS its concept. owner stays NULL,
    # which marks a LIBRARY row. This harness is the THIRD writer to `ingredients` and the only one that runs
    # on Postgres alone, which is why it survived a green SQLite suite.
    for key, ing in INGREDIENTS.items():
        conn.execute(insert(Ingredient.__table__).values(
            id=key, name=ing["name"], descr=ing.get("descr"), pairs=ing.get("pairs"),
            created_at=now, concept=key))
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
    # recipes + their lines/steps (seeded as source='seed', matching the SQLite harness)
    for r in TEST_RECIPES:
        conn.execute(insert(Recipe.__table__).values(
            id=r["id"], name=r["name"], author=r.get("author"), source_url=r.get("source_url"),
            category=r.get("category"), servings=r.get("servings"), prep_time=r.get("prep_time"),
            cook_time=r.get("cook_time"), total_time=r.get("total_time"), descr=r.get("descr"),
            # ⚠️ NO notes= HERE. Migration 063 dropped recipes.notes, so Recipe.__table__ no longer
            #    carries the column and insert().values(notes=…) fails at COMPILE time with
            #    "Unconsumed column names: notes", before any SQL is sent. That took out every test
            #    using the pg fixture, and this file is skipped on a run without $DATABASE_URL, so
            #    the whole Postgres leg of CI would have gone red on a suite that is green locally.
            #    The SQLite harness seeds no notes either (build_db never wrote the column), so the
            #    two fixtures still agree. TEST_RECIPES keeps its two notes strings as fixture data.
            image=r.get("image"), uid=r.get("uid"), created_at=now, source="seed"))
        _insert_lines_and_steps(conn, r)
    _seed_weights(conn)


# ⚠️ REFERENCE DATA THE SCHEMA ITSELF CREATES, AND TRUNCATING IT BREAKS WHAT POINTS AT IT.
#    Migration 060 and its Alembic mirror insert the five note kinds, nothing reseeds them, and
#    recipe_notes.kind is a FOREIGN KEY to that table. Reproduced before this line existed: after
#    one reset the table held 0 rows and POST /api/recipes with any note returned 500 on
#    recipe_notes_kind_fkey, with NO payload able to succeed, because write_notes reads the allowed
#    kinds from the table and falls back to 'notes', which was also missing. The whole Postgres leg
#    of CI could not store a note and nothing said so.
KEEP_THROUGH_RESET = {"schema_migrations", "note_kinds"}


def reset_and_seed(engine):
    """Truncate-and-reseed isolation primitive for the Postgres test DB: TRUNCATE every seed/data
    table (RESTART IDENTITY resets the SERIAL sequences for deterministic IDs; CASCADE ignores FK
    order), then reseed — all in one transaction. Leaves alembic_version (the Alembic stamp) alone.
    Assumes the schema already exists (alembic upgrade head)."""
    # ⚠️ note_kinds IS REFERENCE DATA THE SCHEMA ITSELF CREATES, AND TRUNCATING IT BREAKS EVERY
    #    NOTE. Migration 060 and its Alembic mirror insert the five kinds, nothing reseeds them, and
    #    recipe_notes.kind is a FOREIGN KEY to this table. Reproduced: after one reset the table held
    #    0 rows and POST /api/recipes with any note returned 500 on recipes_notes_kind_fkey, with no
    #    payload able to succeed, because write_notes reads the allowed kinds from this table and
    #    falls back to 'notes', which was also missing. Left alone for the same reason
    #    schema_migrations is: the migration owns it, not the seed.
    names = [t.name for t in models.Base.metadata.sorted_tables
             if t.name not in KEEP_THROUGH_RESET]
    with engine.begin() as conn:
        # ⚠️ THE DATABASE ITSELF IS ASKED BEFORE THE TRUNCATE, NOT ITS ADDRESS. urlguard reads
        # $DATABASE_URL at startup and this reads the connection: current_database() against what
        # the URL resolves to, then the harness marker. A database this run did not create carries
        # no marker, and one that carries no marker may be claimed only while it is empty. See
        # tests/dbmarker.py for why an address check cannot answer this on its own.
        import dbmarker
        import urlguard
        dbmarker.claim_or_verify_pg(
            conn,
            expected_db=urlguard.effective_database(os.environ.get(urlguard.ENV_URL)),
            content_tables=names)
        conn.execute(text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))
        seed_all(conn)
        ensure_note_kinds(conn)


def ensure_note_kinds(conn):
    """Put the five kinds back if anything has emptied the table, from the one file that defines
    them.

    ⚠️ KEEPING THE TABLE OUT OF THE TRUNCATE IS NOT ENOUGH ON ITS OWN, and that was measured the
    moment the fix was tested: a single run of the OLD harness emptied note_kinds, and because
    nothing reseeds it the database stayed unable to store a note afterwards. Keeping it is what
    protects the rows; this is what heals a database that already lost them. Idempotent, and it
    reads static/note-kinds.json, which tests/test_note_kinds_table.py already pins against both
    the SQLite migration and the Alembic mirror."""
    import json

    kinds = json.loads((Path(__file__).resolve().parent.parent
                        / "static" / "note-kinds.json").read_text())["kinds"]
    for i, k in enumerate(kinds):
        conn.execute(text("INSERT INTO note_kinds (kind, header, position) "
                          "VALUES (:k, :h, :p) ON CONFLICT (kind) DO NOTHING"),
                     {"k": k["kind"], "h": k["header"], "p": i})
