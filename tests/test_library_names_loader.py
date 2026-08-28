"""build_db.seed_library_names, the add-on-save lookup loader (stage 3).

The load itself is ordinary. What is worth pinning is the ABSENT-FILE path, because that is the state
every fresh clone and every CI run is in, and it is what keeps the stage-5 save gate dormant.

The file is server-side and gitignored, so make_kitchen rebinds build_db.LIBRARY_NAMES_CSV into
tmp_path (the same module-global pattern it uses for build_db.DB and build_db.RECIPES). That is what
makes these tests machine-independent: the default is a path that does not exist even on a machine
carrying the real lookup, and a test that wants rows writes tmp_path/"library_names.csv" itself.
"""
import sqlite3

import pytest

import build_db


FIVE_ROWS = """# library_names.csv — id -> canonical, generated from the library rowset
library_id,canonical
Q1063736,penne
Q178,pasta
en:egg-pasta,egg pasta
en:lasagne,lasagne
salt,salt
"""


def _write(tmp_path, text):
    """Write the lookup where make_kitchen already pointed the loader."""
    p = tmp_path / "library_names.csv"
    p.write_text(text, encoding="utf-8")
    assert p == build_db.LIBRARY_NAMES_CSV      # the harness rebinding is what makes this reach
    return p


# ---- the absent-file path: the default, and the one that matters ------------------------------

def test_build_succeeds_with_no_file_and_leaves_the_table_empty(kitchen):
    """⚠️ THE IMPORTANT ONE. library_names.csv is gitignored and absent on a fresh clone and in CI, so
    a build must run clean and leave the lookup empty. An empty lookup is what keeps the stage-5
    create branch from ever matching, so the feature self-disables instead of half-enabling."""
    assert not build_db.LIBRARY_NAMES_CSV.exists()      # genuinely absent, not mocked mid-call
    assert kitchen.count("library_names") == 0
    kitchen.rebuild()                                    # runs build() -> seed_library_names
    assert kitchen.count("library_names") == 0
    assert kitchen.count("ingredients") == 36            # and the rest of the build is unaffected


def test_absent_file_leaves_already_loaded_rows_alone(kitchen):
    """The early return happens before the DELETE, matching seed_weights. Losing the file does not
    silently empty a lookup that was already loaded."""
    with kitchen.conn() as c:
        c.execute("INSERT INTO library_names VALUES ('Q178','pasta')")
    with kitchen.conn() as c:
        build_db.seed_library_names(c)                   # file still absent
    assert kitchen.count("library_names") == 1


# ---- the with-file path -----------------------------------------------------------------------

def test_loads_every_row_including_both_id_shapes(kitchen, tmp_path):
    """Both shapes the library actually uses have to survive the round trip: a Wikidata Q-id (61.1% of
    rows) and an Open Food Facts id (38.4%)."""
    _write(tmp_path, FIVE_ROWS)
    with kitchen.conn() as c:
        build_db.seed_library_names(c)
    with kitchen.conn() as c:
        rows = {r["library_id"]: r["canonical"]
                for r in c.execute("SELECT library_id, canonical FROM library_names")}
    assert rows == {"Q1063736": "penne", "Q178": "pasta", "en:egg-pasta": "egg pasta",
                    "en:lasagne": "lasagne", "salt": "salt"}


def test_the_build_path_loads_it_too(kitchen, tmp_path):
    """Exercises the wiring in build(), not just the function. seed_library_names sits beside
    seed_weights inside the same suspended-FK block."""
    _write(tmp_path, FIVE_ROWS)
    kitchen.rebuild()
    assert kitchen.count("library_names") == 5


def test_rerun_replaces_rather_than_duplicates(kitchen, tmp_path):
    """DELETE-then-INSERT, the same wholesale rebuild seed_weights does, so a second run is a no-op
    and a shrunken file really shrinks the table."""
    _write(tmp_path, FIVE_ROWS)
    with kitchen.conn() as c:
        build_db.seed_library_names(c)
        build_db.seed_library_names(c)
    assert kitchen.count("library_names") == 5

    _write(tmp_path, "library_id,canonical\nQ178,pasta\n")
    with kitchen.conn() as c:
        build_db.seed_library_names(c)
    assert kitchen.count("library_names") == 1


def test_incomplete_rows_are_skipped_and_comments_ignored(kitchen, tmp_path):
    """Missing either column means no data, so the row is skipped rather than stored half-empty, the
    same call seed_weights makes on an unparseable volume."""
    _write(tmp_path, "# a note about provenance\n"
                     "library_id,canonical\n"
                     "Q178,pasta\n"
                     ",orphaned name\n"          # no id
                     "Q999,\n"                   # no canonical
                     "en:salt,salt\n")
    with kitchen.conn() as c:
        build_db.seed_library_names(c)
    assert kitchen.count("library_names") == 2


def test_a_duplicate_id_raises_and_leaves_the_table_untouched(kitchen, tmp_path):
    """⚠️ A duplicate is NOT skipped, unlike an incomplete row. An incomplete row carries no data, a
    duplicate carries conflicting data, and quietly keeping the first would make the lookup depend on
    file order. The DELETE is uncommitted when it raises, so the database is unharmed."""
    _write(tmp_path, "library_id,canonical\nQ178,pasta\nQ178,noodles\n")
    conn = sqlite3.connect(kitchen.db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            build_db.seed_library_names(conn)
        conn.rollback()
    finally:
        conn.close()
    assert kitchen.count("library_names") == 0
