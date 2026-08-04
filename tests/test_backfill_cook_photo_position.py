"""The cook-photo position backfill (scripts/backfill_cook_photo_position.py) — Stage 4 build 3d-i's
data-transforming seed. Pins the script's DB behavior: per recipe it assigns position 0,1,2,… in the
album's CURRENT display order (cook-linked newest-first, undated last), it CONTINUES from a recipe's
existing max (never disturbing a row that already has a position), and it is IDEMPOTENT (the WHERE
position IS NULL guard means a second run touches nothing — it runs outside migrate's tracker)."""
import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_backfill(db_path):
    spec = importlib.util.spec_from_file_location(
        "backfill_cook_photo_position", REPO / "scripts" / "backfill_cook_photo_position.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB = Path(db_path)                     # point the script at our throwaway DB
    return mod


def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE cook_log (id INTEGER PRIMARY KEY, cooked_on TEXT)")
    c.execute("""CREATE TABLE cook_photos (
        id INTEGER PRIMARY KEY, cook_log_id INTEGER, recipe_id TEXT, user_id INTEGER,
        path TEXT, caption TEXT, added_at TEXT, position INTEGER)""")
    c.executemany("INSERT INTO cook_log (id, cooked_on) VALUES (?,?)",
                  [(10, "2024-03-01"), (11, "2024-05-01")])
    # r1: two cook-linked (03-01, 05-01) + one standalone/undated -> display order [#2(05-01), #1(03-01), #3]
    # r2: one standalone -> [#4]
    c.executemany(
        "INSERT INTO cook_photos (id, cook_log_id, recipe_id, user_id, path, added_at, position) "
        "VALUES (?,?,?,?,?,?,NULL)",
        [
            (1, 10, "r1", 1, "images/cooks/a.jpg", "2024-03-01T00:00Z"),
            (2, 11, "r1", 1, "images/cooks/b.jpg", "2024-05-01T00:00Z"),
            (3, None, "r1", 1, "images/cooks/c.jpg", "2024-06-01T00:00Z"),   # undated -> last
            (4, None, "r2", 1, "images/cooks/d.jpg", "2024-02-01T00:00Z"),
        ],
    )
    c.commit()
    c.close()


def _positions(db):
    c = sqlite3.connect(db)
    got = dict(c.execute("SELECT id, position FROM cook_photos").fetchall())
    c.close()
    return got


def test_seeds_position_in_display_order_per_recipe(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=False)
    # r1 display order [#2, #1, #3] -> 0,1,2 ; r2 [#4] -> 0
    assert _positions(db) == {1: 1, 2: 0, 3: 2, 4: 0}


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=True)
    assert _positions(db) == {1: None, 2: None, 3: None, 4: None}   # untouched


def test_continues_from_existing_max_without_disturbing_set_rows(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    c = sqlite3.connect(db)
    c.execute("UPDATE cook_photos SET position = 5 WHERE id = 2")   # #2 already positioned (e.g. appended)
    c.commit(); c.close()
    _load_backfill(db).backfill(dry_run=False)
    got = _positions(db)
    assert got[2] == 5                              # untouched (already had a position)
    # r1's remaining NULLs (#1, #3) sequence from max(5)+1 in display order [#1, #3] -> 6, 7
    assert got[1] == 6 and got[3] == 7
    assert got[4] == 0                              # r2 independent


def test_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    mod = _load_backfill(db)
    first = mod.backfill(dry_run=False)
    assert sum(len(m) for _rid, m in first) == 4    # 4 rows seeded
    before = _positions(db)
    second = mod.backfill(dry_run=False)
    assert sum(len(m) for _rid, m in second) == 0   # nothing left (no NULL positions)
    assert _positions(db) == before                 # unchanged
