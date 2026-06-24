#!/usr/bin/env python3
"""demo_foreign_keys.py — a hands-on look at what the foreign key does.

Run it from inside the recipe-app folder (where recipes.db lives):

    python3 demo_foreign_keys.py

It does three things, printing the results as it goes:
  1. shows that 'garlic' is stored in ONE row in the ingredients table
  2. shows the several recipes that REFERENCE that one row (no copying)
  3. tries to add a recipe line pointing at a typo'd ingredient, first with
     the foreign-key rule OFF (it sneaks in) then ON (it's rejected)

It works on a throwaway COPY of your database, so it never changes your real
data. Nothing it does is saved.
"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

SOURCE_DB = Path(__file__).resolve().parent / "recipes.db"


def main():
    if not os.path.exists(SOURCE_DB):
        print(f"Can't find {SOURCE_DB}.\n"
              f"Run python3 build_db.py first to create it, then try again.")
        return

    # work on a temporary copy so the real database is never touched
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy(SOURCE_DB, tmp)

    # -----------------------------------------------------------------
    print("=" * 72)
    print("1) 'garlic' is defined ONCE, here in the ingredients table:")
    print("=" * 72)
    c = sqlite3.connect(tmp)
    c.row_factory = sqlite3.Row
    g = c.execute("SELECT id, name, pairs FROM ingredients WHERE id='garlic'").fetchone()
    if g is None:
        print("  (no 'garlic' row found — edit the key below to one you do have)")
        c.close(); os.remove(tmp); return
    months = [r["month"] for r in c.execute(
        "SELECT month FROM ingredient_seasons WHERE ingredient_id='garlic' ORDER BY month")]
    regions = [r["name"] for r in c.execute(
        """SELECT rg.name FROM ingredient_regions ir
           JOIN regions rg ON rg.id = ir.region_id
           WHERE ir.ingredient_id='garlic' ORDER BY ir.position""")]
    print(f"  id      = {g['id']}")
    print(f"  name    = {g['name']}")
    print(f"  season  = {months}   (reassembled from the ingredient_seasons table)")
    print(f"  regions = {regions}")
    print("  Its core fields live here; its season and regions live in child tables.")

    # -----------------------------------------------------------------
    print()
    print("=" * 72)
    print("2) Several recipes REFERENCE that one row — without copying it:")
    print("=" * 72)
    rows = c.execute("""
        SELECT r.name AS recipe, ri.ingredient_id, ri.qty, ri.label, ri.note
        FROM recipe_ingredients ri
        JOIN recipes r ON r.id = ri.recipe_id
        WHERE ri.ingredient_id = 'garlic'
    """).fetchall()
    for x in rows:
        reads = f"{x['qty']} {x['label']}{x['note'] or ''}"
        print(f"  {x['recipe'][:38]:<40} stores key '{x['ingredient_id']}'  ->  {reads}")
    print("\n  Each row holds only the key 'garlic' plus its own wording.")
    print("  The season/regions/description are NOT repeated in these rows.")
    c.close()

    # -----------------------------------------------------------------
    print()
    print("=" * 72)
    print("3) The foreign-key rule: try to reference a typo, 'gralic'")
    print("=" * 72)
    bad = ("mussakhan", 99, "1 clove", "gralic", "garlic")
    insert = """INSERT INTO recipe_ingredients
                (recipe_id, position, qty, ingredient_id, label) VALUES (?,?,?,?,?)"""

    # rule OFF (SQLite's default if you never set the pragma)
    a = sqlite3.connect(tmp)
    a.execute("PRAGMA foreign_keys = OFF")
    a.execute(insert, bad)
    landed = a.execute(
        "SELECT recipe_id, ingredient_id FROM recipe_ingredients WHERE ingredient_id='gralic'"
    ).fetchone()
    print(f"  rule OFF -> accepted. Bad row now in table: {landed}")
    print("            It points at 'gralic', which exists in no ingredient.")
    a.rollback(); a.close()

    # rule ON — set on a fresh connection, BEFORE any transaction starts
    # (SQLite ignores this pragma if changed mid-transaction)
    b = sqlite3.connect(tmp)
    b.execute("PRAGMA foreign_keys = ON")
    try:
        b.execute(insert, bad)
        print("  rule ON  -> accepted (unexpected!)")
    except sqlite3.IntegrityError as e:
        print(f"  rule ON  -> REJECTED: {e}")
        print("            The typo is stopped at the door; the bad row never lands.")
    b.rollback(); b.close()

    os.remove(tmp)
    print("\n(Done. Your real recipes.db was not touched.)")


if __name__ == "__main__":
    main()
