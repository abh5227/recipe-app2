"""The per-cook ratings backfill (scripts/backfill_percook_ratings.py) — migration 048's data half.

Pins the 5-clause attach rule, the refusals, and the two invariants the script exists to guarantee:
every rating lands on exactly one cook, and the NEW headline (AVG of rated cooks) equals the OLD
stored value so nothing Andy looks at changes. The `ratings` table is read and left frozen."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load(db_path):
    spec = importlib.util.spec_from_file_location(
        "backfill_percook_ratings", REPO / "scripts" / "backfill_percook_ratings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB = Path(db_path)                     # point the script at our throwaway DB
    return mod


def _make_db(path, cooks, ratings):
    """A minimal pre-048 DB: recipes + cook_log + ratings + the migration tracker."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE recipes (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE cook_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            cooked_on TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'app',
            user_id INTEGER);
        CREATE TABLE ratings (
            recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            rated_on TEXT NOT NULL,
            PRIMARY KEY (recipe_id, user_id));
        CREATE TABLE schema_migrations (
            filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));
    """)
    for rid in {k[0] for k in cooks} | {r[0] for r in ratings}:
        c.execute("INSERT INTO recipes (id, name) VALUES (?, ?)", (rid, rid))
    c.executemany("INSERT INTO cook_log (recipe_id, cooked_on, source, user_id) VALUES (?,?,?,?)", cooks)
    c.executemany("INSERT INTO ratings (recipe_id, user_id, rating, rated_on) VALUES (?,?,?,?)", ratings)
    c.commit()
    c.close()


def test_each_clause_picks_the_cook_it_should(tmp_path):
    """All four attach clauses, one recipe each, in one run."""
    db = tmp_path / "t.db"
    _make_db(
        db,
        cooks=[
            ("solo",     "2024-01-01", "app", 1),                    # clause 1: the only cook
            ("inferred", "2024-02-01", "rating-inferred", 1),        # clause 2 wins over the later app cook
            ("inferred", "2026-05-05", "app", 1),
            ("sameday",  "2024-03-03", "app", 1),                    # clause 3: matches rated_on's date
            ("sameday",  "2026-06-06", "app", 1),
            ("earliest", "2024-04-04", "app", 1),                    # clause 4: nothing else distinguishes
            ("earliest", "2026-07-07", "app", 1),
        ],
        ratings=[
            ("solo",     1, 5, "2026-01-01 10:00:00"),
            ("inferred", 1, 4, "2026-07-01 21:29:11"),
            ("sameday",  1, 3, "2024-03-03 18:00:00"),
            ("earliest", 1, 2, "2025-12-31 12:00:00"),
        ],
    )
    result = _load(db).run(db_path=str(db), verbose=False)
    assert result["clauses"] == {
        "one cook": 1, "rating-inferred cook": 1, "cook dated == rated_on": 1, "earliest cook": 1}

    c = sqlite3.connect(db)
    landed = dict(c.execute(
        "SELECT recipe_id, cooked_on FROM cook_log WHERE rating IS NOT NULL").fetchall())
    assert landed == {"solo": "2024-01-01", "inferred": "2024-02-01",
                      "sameday": "2024-03-03", "earliest": "2024-04-04"}
    # the verdict's timestamp travels, and it is NOT the cook's date
    assert c.execute("SELECT rated_at FROM cook_log WHERE recipe_id='inferred' AND rating IS NOT NULL"
                     ).fetchone()[0] == "2026-07-01 21:29:11"


def test_headline_average_equals_the_old_rating(tmp_path):
    """The invariant Andy cares about: the number on screen does not move."""
    db = tmp_path / "t.db"
    _make_db(db,
             cooks=[("a", "2024-01-01", "app", 1), ("a", "2024-02-02", "app", 1),
                    ("b", "2024-03-03", "app", 1)],
             ratings=[("a", 1, 4, "2024-01-01 09:00:00"), ("b", 1, 5, "2024-03-03 09:00:00")])
    _load(db).run(db_path=str(db), verbose=False)
    c = sqlite3.connect(db)
    avg = dict(c.execute("SELECT recipe_id, AVG(rating) FROM cook_log "
                         "WHERE rating IS NOT NULL GROUP BY recipe_id").fetchall())
    assert avg == {"a": 4.0, "b": 5.0}
    # the second cook of 'a' stays unrated, and an unrated cook is EXCLUDED rather than counted as 0
    assert c.execute("SELECT COUNT(*) FROM cook_log WHERE rating IS NULL").fetchone()[0] == 1


def test_a_rating_never_lands_on_another_users_cook(tmp_path):
    """Cooks are matched by the same user. User 2's cooking is not user 1's verdict to give."""
    db = tmp_path / "t.db"
    _make_db(db,
             cooks=[("shared", "2024-01-01", "app", 2), ("shared", "2024-06-06", "app", 1)],
             ratings=[("shared", 1, 5, "2024-06-06 09:00:00")])
    _load(db).run(db_path=str(db), verbose=False)
    c = sqlite3.connect(db)
    assert c.execute("SELECT user_id FROM cook_log WHERE rating IS NOT NULL").fetchall() == [(1,)]


def test_a_rating_with_no_cook_stops_the_run(tmp_path):
    """Clause 5. ⚠️ Never invent a cook to hold a verdict — that is a question for Andy."""
    db = tmp_path / "t.db"
    _make_db(db, cooks=[("cooked", "2024-01-01", "app", 1)],
             ratings=[("cooked", 1, 5, "2024-01-01 09:00:00"),
                      ("orphan", 1, 4, "2024-02-02 09:00:00")])
    with pytest.raises(SystemExit, match="no cook"):
        _load(db).run(db_path=str(db), verbose=False)
    c = sqlite3.connect(db)                      # and it wrote NOTHING, not even the row it could place
    assert c.execute("SELECT COUNT(*) FROM cook_log WHERE rating IS NOT NULL").fetchone()[0] == 0


def test_refuses_to_run_twice(tmp_path):
    db = tmp_path / "t.db"
    _make_db(db, cooks=[("a", "2024-01-01", "app", 1)], ratings=[("a", 1, 5, "2024-01-01 09:00:00")])
    mod = _load(db)
    mod.run(db_path=str(db), verbose=False)
    with pytest.raises(SystemExit, match="already carry a rating"):
        mod.run(db_path=str(db), verbose=False)


def test_dry_run_moves_nothing_but_leaves_the_schema_stamped(tmp_path):
    """--dry-run rolls back the DATA move. The DDL commits (executescript does), and it is stamped in
    the same breath so the DB never has columns schema_migrations denies."""
    db = tmp_path / "t.db"
    _make_db(db, cooks=[("a", "2024-01-01", "app", 1)], ratings=[("a", 1, 5, "2024-01-01 09:00:00")])
    _load(db).run(db_path=str(db), dry_run=True, verbose=False)
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM cook_log WHERE rating IS NOT NULL").fetchone()[0] == 0
    assert [r[1] for r in c.execute("PRAGMA table_info(cook_log)")] == [
        "id", "recipe_id", "cooked_on", "source", "user_id", "rating", "rated_at", "caption"]
    assert c.execute("SELECT COUNT(*) FROM schema_migrations WHERE filename=?",
                     ("048_ratings_cluster.sql",)).fetchone()[0] == 1


def test_ratings_table_is_left_frozen(tmp_path):
    """⚠️ Not emptied, not dropped. It is the rollback for this script."""
    db = tmp_path / "t.db"
    _make_db(db, cooks=[("a", "2024-01-01", "app", 1)], ratings=[("a", 1, 5, "2024-01-01 09:00:00")])
    before = sqlite3.connect(db).execute("SELECT * FROM ratings").fetchall()
    _load(db).run(db_path=str(db), verbose=False)
    assert sqlite3.connect(db).execute("SELECT * FROM ratings").fetchall() == before
