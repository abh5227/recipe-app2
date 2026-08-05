"""The hero-album backfill (scripts/backfill_hero_album_rows.py) — hero↔album unification Stage 2's
data-transforming step. Pins the script's DB behavior: a HERO-ONLY recipe (recipes.image set, no
cook_photos row at that path) gets ONE cook-less (cook_log_id NULL) album row for its hero at the album's
END (max position + 1); an already-consistent/promoted hero (a row already matches recipes.image) is
SKIPPED; a recipe with no hero, or with owner NULL, is skipped; and it's IDEMPOTENT (the NOT-EXISTS guard
means a second run touches nothing — it runs outside migrate's tracker)."""
import importlib.util
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_backfill(db_path):
    spec = importlib.util.spec_from_file_location(
        "backfill_hero_album_rows", REPO / "scripts" / "backfill_hero_album_rows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB = Path(db_path)                     # point the script at our throwaway DB
    return mod


def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE recipes (id TEXT PRIMARY KEY, name TEXT, owner INTEGER, image TEXT)")
    c.execute("""CREATE TABLE cook_photos (
        id INTEGER PRIMARY KEY, cook_log_id INTEGER, recipe_id TEXT, user_id INTEGER,
        path TEXT, caption TEXT, added_at TEXT, position INTEGER)""")
    c.executemany(
        "INSERT INTO recipes (id, name, owner, image) VALUES (?,?,?,?)",
        [
            ("heroonly", "Hero Only", 1, "images/heroonly.jpg"),        # -> backfilled (pos 0)
            ("promoted", "Promoted", 1, "images/cooks/p.jpg"),         # already consistent -> skipped
            ("withphotos", "With Photos", 1, "images/withphotos.jpg"),  # hero-only + 2 existing photos -> append pos 2
            ("nohero", "No Hero", 1, None),                            # no hero -> skipped
            ("noowner", "No Owner", None, "images/noowner.jpg"),        # owner NULL -> skipped
        ],
    )
    c.executemany(
        "INSERT INTO cook_photos (id, cook_log_id, recipe_id, user_id, path, added_at, position) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (1, None, "promoted", 1, "images/cooks/p.jpg", "2024-01-01 00:00:00", 0),   # == promoted.image
            (2, 10, "withphotos", 1, "images/cooks/x.jpg", "2024-02-01 00:00:00", 0),
            (3, 11, "withphotos", 1, "images/cooks/y.jpg", "2024-02-02 00:00:00", 1),
        ],
    )
    c.commit()
    c.close()


def _rows(db, recipe_id):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    got = c.execute(
        "SELECT cook_log_id, recipe_id, user_id, path, caption, position FROM cook_photos "
        "WHERE recipe_id = ? ORDER BY position, id", (recipe_id,),
    ).fetchall()
    c.close()
    return got


def _count(db):
    c = sqlite3.connect(db)
    n = c.execute("SELECT count(*) FROM cook_photos").fetchone()[0]
    c.close()
    return n


def test_backfills_hero_only_as_cookless_album_row(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=False)
    rows = _rows(db, "heroonly")
    assert len(rows) == 1
    r = rows[0]
    assert r["cook_log_id"] is None                        # cook-less
    assert r["user_id"] == 1                               # = recipes.owner
    assert r["path"] == "images/heroonly.jpg"              # points at the EXISTING hero path (no file rename)
    assert r["caption"] is None and r["position"] == 0     # first photo


def test_skips_already_consistent_hero(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=False)
    assert len(_rows(db, "promoted")) == 1                 # unchanged — no duplicate hero row


def test_appends_after_existing_photos(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=False)
    rows = _rows(db, "withphotos")
    assert [r["path"] for r in rows] == [
        "images/cooks/x.jpg", "images/cooks/y.jpg", "images/withphotos.jpg"]   # hero appended LAST
    assert rows[-1]["position"] == 2                       # max(0,1)+1
    assert rows[-1]["cook_log_id"] is None


def test_skips_no_hero_and_owner_null(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    _load_backfill(db).backfill(dry_run=False)
    assert _rows(db, "nohero") == []                       # no hero -> no row
    assert _rows(db, "noowner") == []                      # owner NULL -> skipped (user_id is NOT NULL)


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    before = _count(db)
    _load_backfill(db).backfill(dry_run=True)
    assert _count(db) == before                            # untouched


def test_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db)
    mod = _load_backfill(db)
    first = mod.backfill(dry_run=False)
    assert len(first) == 2                                 # heroonly + withphotos (promoted/nohero/noowner skipped)
    after_first = _count(db)
    second = mod.backfill(dry_run=False)
    assert len(second) == 0                                # NOT-EXISTS guard -> nothing left to add
    assert _count(db) == after_first                       # unchanged
