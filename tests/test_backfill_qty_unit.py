"""The one-off qty/unit backfill (scripts/backfill_qty_unit.py) — the repo's first data-transforming
step. The transform itself is import_cleanup.split_qty (tested in test_import_cleanup); here we pin the
script's DB behavior: it fills only non-heading rows WHERE quantity IS NULL, leaves qty untouched, and
is IDEMPOTENT (a second run touches nothing — the guard, since it runs outside migrate's tracker)."""
import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_backfill(db_path):
    spec = importlib.util.spec_from_file_location(
        "backfill_qty_unit", REPO / "scripts" / "backfill_qty_unit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB = Path(db_path)                    # point the script at our throwaway DB
    return mod


def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT, is_heading INTEGER NOT NULL DEFAULT 0,
        qty TEXT, quantity TEXT, unit TEXT)""")
    rows = [
        (0, "2 tablespoons"),   # number + unit
        (0, "2"),               # number only
        (0, ""),                # empty
        (0, "4 cloves"),        # count-noun -> unit
        (0, "2 lb / 1 kg"),     # irreducible -> whole
        (1, None),              # a heading (must be skipped)
    ]
    c.executemany("INSERT INTO recipe_ingredients (is_heading, qty) VALUES (?,?)", rows)
    c.commit()
    c.close()


def test_backfill_populates_and_leaves_qty_untouched(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    mod = _load_backfill(db)
    mod.backfill(dry_run=False)

    c = sqlite3.connect(db)
    got = c.execute(
        "SELECT qty, quantity, unit FROM recipe_ingredients WHERE is_heading=0 ORDER BY id"
    ).fetchall()
    assert got == [
        ("2 tablespoons", "2", "tablespoons"),
        ("2", "2", ""),
        ("", "", ""),
        ("4 cloves", "4", "cloves"),
        ("2 lb / 1 kg", "2 lb / 1 kg", ""),
    ]
    # heading row untouched: still NULL quantity/unit (backfill skips is_heading=1)
    head = c.execute("SELECT quantity, unit FROM recipe_ingredients WHERE is_heading=1").fetchone()
    assert head == (None, None)
    c.close()


def test_backfill_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    mod = _load_backfill(db)
    first = mod.backfill(dry_run=False)
    assert sum(first.values()) == 5                     # 5 non-heading rows filled
    # snapshot, then re-run: the WHERE quantity IS NULL guard means the second run touches nothing
    c = sqlite3.connect(db)
    before = c.execute("SELECT id, quantity, unit FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    second = mod.backfill(dry_run=False)
    assert sum(second.values()) == 0                    # nothing left to do
    c = sqlite3.connect(db)
    after = c.execute("SELECT id, quantity, unit FROM recipe_ingredients ORDER BY id").fetchall()
    c.close()
    assert before == after                              # unchanged on the second run
