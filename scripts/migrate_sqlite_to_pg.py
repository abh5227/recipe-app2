#!/usr/bin/env python3
"""migrate_sqlite_to_pg.py — one-time copy of all app data from SQLite (recipes.db) to Postgres.

Stage 2b-4 of the SQLite -> Postgres migration. The Postgres schema is created by Alembic (2a);
this script only COPIES DATA. It is standalone tooling — it does NOT touch app.py, and it reads
SQLite from the explicit recipes.db path (NOT orm_session(), which is now DATABASE_URL-driven and
would point at Postgres).

Run:
    docker start recipe-postgres                        # the container must be up
    DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/recipe \
        python3 scripts/migrate_sqlite_to_pg.py

Safety:
  * TARGET must be a postgresql URL (refuses SQLite / unset DATABASE_URL).
  * Refuses to run if Postgres already has data (avoids a double-copy) — reset the container +
    `alembic upgrade head` to retry.
  * Copies inside ONE transaction (all-or-nothing); on any error, nothing is committed.
  * Skips schema_migrations (SQLite migration tracking; Postgres uses alembic_version).
"""
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select, text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from models import (  # noqa: E402  (path set up above)
    Ingredient, Person, Region, Recipe, ingredient_weights,
    RecipeIngredient, RecipeStep, CookLog, Rating, ImportFlag,
    IngredientSeason, IngredientRegion, RecipeAddition, RecipeLineChange,
)

SQLITE_PATH = REPO / "recipes.db"

# (sqlite table name, target Core Table) in FK-dependency order: Tier 0 roots, then Tier 1 children.
# schema_migrations is intentionally absent (not copied). ingredient_weights is a no-PK Core table.
TABLES = [
    # --- Tier 0: roots (no FK deps) ---
    ("ingredients", Ingredient.__table__),
    ("people", Person.__table__),
    ("regions", Region.__table__),
    ("recipes", Recipe.__table__),
    ("ingredient_weights", ingredient_weights),
    # --- Tier 1: children (all parents are Tier 0) ---
    ("recipe_ingredients", RecipeIngredient.__table__),
    ("recipe_steps", RecipeStep.__table__),
    ("cook_log", CookLog.__table__),
    ("ratings", Rating.__table__),
    ("import_flags", ImportFlag.__table__),
    ("ingredient_seasons", IngredientSeason.__table__),
    ("ingredient_regions", IngredientRegion.__table__),
    ("recipe_additions", RecipeAddition.__table__),
    ("recipe_line_changes", RecipeLineChange.__table__),
]

# INTEGER-PK tables whose SERIAL sequence must be advanced past the copied MAX(id).
SERIAL_TABLES = ["regions", "cook_log", "recipe_ingredients", "recipe_steps",
                 "recipe_additions", "import_flags"]

# Tables to sanity-check for the refuse-if-not-empty guard.
EMPTY_CHECK = ["recipes", "ingredients", "recipe_ingredients"]


def read_rows(src, sqlite_name, table):
    """Read every row of `sqlite_name` from SQLite into dicts keyed by the TARGET column KEY.

    Maps by column KEY <- SQLite column NAME so the recipe_steps DB column "text" (whose model
    attribute/key is "body") lands under the right key for the Core insert. Values are copied
    verbatim: text-dates as str, REAL as float, NULL as None, is_heading as int.
    """
    keymap = [(col.key, col.name) for col in table.columns]   # (target key, db column name)
    rows = []
    for r in src.execute(f"SELECT * FROM {sqlite_name}"):      # sqlite_name is from the fixed list above
        rows.append({key: r[name] for key, name in keymap})
    return rows


def main():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        sys.exit("ABORT: set DATABASE_URL to the postgresql+psycopg://... container URL "
                 f"(got {url!r}). This script copies INTO Postgres.")
    if not SQLITE_PATH.exists():
        sys.exit(f"ABORT: source SQLite DB not found at {SQLITE_PATH}")

    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row
    target = create_engine(url, future=True)

    # --- refuse-if-not-empty ---
    with target.connect() as conn:
        for t in EMPTY_CHECK:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            if n:
                sys.exit(
                    f"ABORT: Postgres already has data ({t}={n}). Reset and retry:\n"
                    "  docker rm -f recipe-postgres && docker run --name recipe-postgres "
                    "-e POSTGRES_PASSWORD=<pw> -e POSTGRES_DB=recipe -p 5432:5432 -d postgres:16\n"
                    "  DATABASE_URL=... alembic upgrade head\n"
                    "  DATABASE_URL=... python3 scripts/migrate_sqlite_to_pg.py"
                )

    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {url.split('@')[-1]}  (schema from Alembic baseline)\n")

    copied = {}
    # --- all-or-nothing copy + sequence reset ---
    with target.begin() as conn:
        for sqlite_name, table in TABLES:
            rows = read_rows(src, sqlite_name, table)
            if rows:
                conn.execute(insert(table), rows)
            copied[sqlite_name] = len(rows)
            print(f"  copied {sqlite_name:22} {len(rows):>5}")

        print("\n  resetting SERIAL sequences:")
        for t in SERIAL_TABLES:
            # setval past MAX(id); empty table -> is_called=false so next id is 1. Names via
            # pg_get_serial_sequence (not hardcoded). t is from the fixed SERIAL_TABLES list.
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE(MAX(id), 1), "
                f"MAX(id) IS NOT NULL) FROM {t}"
            ))
            print(f"    {t}_id_seq -> reset")

    src.close()
    print(f"\nDONE. Copied {sum(copied.values())} rows across {len(copied)} tables "
          "(schema_migrations skipped). Postgres now holds the app data.")


if __name__ == "__main__":
    main()
