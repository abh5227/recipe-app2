"""scripts/archive_import_flags.py — moving the finished import review queue out of the way.

⚠️ ARCHIVE MEANS MOVED, NOT DELETED, and that is what these pin. The 562 positioned flags on live are
the only record of what the importer declined to guess and why, so they go to import_flags_archive
(migration 055) keeping their original ids, and one INSERT ... SELECT puts them back.
"""
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import archive_import_flags as aif   # noqa: E402

ROWS = [
    (1, "dish", 0, "ambiguous_section", "no amount — suggest ingredient"),
    (2, "dish", 3, "grams_declined", "a gram value was present"),
    (3, "dish", None, "no_directions", None),
    (4, "dish", None, "imported_via", "read from a URL"),
    (5, "other", 7, "each_multi", "'each' distributes one amount"),
]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("""CREATE TABLE import_flags (id INTEGER PRIMARY KEY, recipe_id TEXT NOT NULL,
                 position INTEGER, flag TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL)""")
    c.execute((REPO / "migrations" / "055_import_flags_archive.sql").read_text()
              .split(";")[0] + ";")
    c.executemany("INSERT INTO import_flags (id, recipe_id, position, flag, reason, created_at) "
                  "VALUES (?,?,?,?,?, '2026-07-01 21:29:10')", ROWS)
    c.commit()
    c.close()
    return p


def _counts(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    return (c.execute("SELECT COUNT(*) FROM import_flags").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM import_flags_archive").fetchone()[0])


def test_only_the_positioned_rows_move(db, tmp_path):
    n, by_flag = aif.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    assert n == 3 and set(by_flag) == {"ambiguous_section", "grams_declined", "each_multi"}
    assert _counts(db) == (2, 3)


def test_the_live_imported_via_row_stays(db, tmp_path):
    """⚠️ app.update_recipe READS IT, to decide whether a recipe's baseline is captured on its first
    save. It is live, not history, and it carries no position so it is outside the move anyway."""
    aif.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    left = {r[0] for r in c.execute("SELECT flag FROM import_flags")}
    assert left == {"imported_via", "no_directions"}


def test_an_archived_row_is_byte_identical_and_keeps_its_id(db, tmp_path):
    before = {r[0]: tuple(r) for r in sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
        "SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags "
        "WHERE position IS NOT NULL")}
    aif.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    after = {r[0]: tuple(r) for r in sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
        "SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags_archive")}
    assert after == before


def test_the_move_round_trips(db, tmp_path):
    """The recovery the docstring promises, run as a test rather than left as a claim."""
    orig = [tuple(r) for r in sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
        "SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags ORDER BY id")]
    aif.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    c = sqlite3.connect(db)
    c.execute("""INSERT INTO import_flags (id, recipe_id, position, flag, reason, created_at)
                 SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags_archive""")
    c.commit()
    back = [tuple(r) for r in c.execute(
        "SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags ORDER BY id")]
    assert back == orig


def test_a_rehearsal_writes_nothing_but_still_writes_the_audit(db, tmp_path):
    aif.run(str(db), apply=False, csv_out=tmp_path / "a.csv")
    assert _counts(db) == (5, 0)
    assert (tmp_path / "a.csv").read_text().count("\n") == 4        # header + the 3 movable rows


def test_it_refuses_to_run_without_the_archive_table(tmp_path):
    p = tmp_path / "bare.db"
    c = sqlite3.connect(p)
    c.execute("""CREATE TABLE import_flags (id INTEGER PRIMARY KEY, recipe_id TEXT NOT NULL,
                 position INTEGER, flag TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL)""")
    c.commit()
    c.close()
    with pytest.raises(SystemExit, match="migration 055"):
        aif.run(str(p), apply=True, csv_out=tmp_path / "a.csv")


def test_a_second_run_moves_nothing_more(db, tmp_path):
    aif.run(str(db), apply=True, csv_out=tmp_path / "a.csv")
    n, _ = aif.run(str(db), apply=True, csv_out=tmp_path / "b.csv")
    assert n == 0
    assert _counts(db) == (2, 3)
