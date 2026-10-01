"""A table-rebuild migration is all-or-nothing, so an interrupted run leaves nothing half built.

⚠️ THE DEFECT THIS FILE EXISTS FOR. migrate.py applies each file with sqlite3's `executescript`,
which opens NO transaction, so every statement in a migration auto-commits on its own. A table
rebuild is create, copy, DROP, RENAME, recreate indexes, and an interruption anywhere in the middle
is committed. 056_wait_alongside.sql was given a BEGIN for this reason. The five older rebuilds
(005, 019, 026, 041, 045) were not, and they are the ones a fresh clone still runs.

Two failure shapes, both measured in `test_a_truncated_rebuild_leaves_nothing_behind`:

  * truncated after the DROP     the real table is GONE and the scratch table is left holding the
                                 rows. Loud, and recoverable only by hand.
  * truncated before CREATE INDEX   the rebuild LOOKS finished and the indexes are simply missing.
                                 Silent, and permanent once the filename is recorded.

The second is the one worth the test. Nothing errors, nothing reports, and the schema has quietly
drifted from what the migration says it builds.
"""
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / "migrations"
sys.path.insert(0, str(REPO))
import migrate as migrate_mod                                                  # noqa: E402

# the rebuilds, oldest first. 056 is the control: it already carried a BEGIN.
REBUILDS = ["005_cascade_history.sql", "019_ratings_composite_pk.sql",
            "026_cook_photos_cook_log_nullable.sql", "041_relation_part_of.sql",
            "045_sourced_content_resolved_basis.sql", "056_wait_alongside.sql"]


def _all_migrations():
    return sorted(p.name for p in MIGRATIONS.glob("*.sql"))


def _shape(db):
    """The whole schema plus every table's row count. What a rollback has to leave untouched."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    schema = c.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                       "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    counts = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        counts[t] = c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    c.close()
    return schema, counts


def _build_up_to(tmp_path, upto_exclusive, monkeypatch, name="part.db"):
    """A fresh build holding every migration BEFORE `upto_exclusive`."""
    folder = tmp_path / f"m-{upto_exclusive}"
    folder.mkdir(exist_ok=True)
    for n in _all_migrations():
        if n < upto_exclusive:
            shutil.copy(MIGRATIONS / n, folder / n)
    db = tmp_path / name
    monkeypatch.setattr(migrate_mod, "MIGRATIONS_DIR", folder)
    migrate_mod.migrate(verbose=False, db=db)
    return db


def _truncate(sql, after):
    """The file as a crash would leave it: everything up to and including the `after` statement."""
    i = sql.lower().index(after.lower())
    end = sql.index(";", i) + 1
    return sql[:end]


_CRASH = r"""
import os, sqlite3, sys
db, sqlfile = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(db)
conn.execute("PRAGMA foreign_keys = ON")
try:
    conn.executescript(open(sqlfile).read())
except sqlite3.Error:
    pass
os._exit(0)          # no close, no rollback, no atexit. A real crash, not a tidy one.
"""


def _replay(db, sql):
    """migrate.py's own flow in a child process that is then killed outright.

    ⚠️ IT HAS TO BE A REAL CRASH, NOT `del conn`. Dropping the connection in-process leaves the
    lock held long enough that the next open fails with "database is locked", which measures the
    test harness rather than the migration. `os._exit` skips every cleanup path, the OS releases
    the lock when the process dies, and SQLite recovers from the hot journal on the next open.
    That is the path a Ctrl-C, a laptop sleep or a power cut actually takes."""
    f = pathlib.Path(db).parent / "crash.sql"
    f.write_text(sql)
    subprocess.run([sys.executable, "-c", _CRASH, str(db), str(f)], capture_output=True)


@pytest.mark.parametrize("name", REBUILDS)
@pytest.mark.parametrize("cut", ["drop", "rename"])
def test_a_truncated_rebuild_leaves_nothing_behind(tmp_path, monkeypatch, name, cut):
    """Replay each rebuild truncated mid-flight on a fresh build. The schema and every row count
    must come back exactly as they were, and the filename must NOT be recorded."""
    sql = (MIGRATIONS / name).read_text()
    anchor = {"drop": "DROP TABLE", "rename": "RENAME TO"}[cut]
    if anchor.lower() not in sql.lower():
        pytest.skip(f"{name} has no {anchor}")

    db = _build_up_to(tmp_path, name, monkeypatch)
    before = _shape(db)
    _replay(db, _truncate(sql, anchor))
    after = _shape(db)

    assert after[0] == before[0], (
        f"{name} truncated at {anchor} changed the schema.\n"
        f"  gone:  {[r[1] for r in before[0] if r not in after[0]]}\n"
        f"  added: {[r[1] for r in after[0] if r not in before[0]]}")
    assert after[1] == before[1], f"{name} truncated at {anchor} changed row counts"

    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    recorded = {r[0] for r in c.execute("SELECT filename FROM schema_migrations")}
    c.close()
    assert name not in recorded, f"{name} was recorded as applied after being interrupted"


@pytest.mark.parametrize("name", REBUILDS)
def test_migrate_recovers_and_applies_the_file_cleanly_afterwards(tmp_path, monkeypatch, name):
    """The other half of all-or-nothing. After the interrupted run, an ordinary migrate.py applies
    the file and the result equals an uninterrupted fresh build."""
    sql = (MIGRATIONS / name).read_text()
    db = _build_up_to(tmp_path, name, monkeypatch, name="crashed.db")
    _replay(db, _truncate(sql, "DROP TABLE"))

    monkeypatch.setattr(migrate_mod, "MIGRATIONS_DIR", MIGRATIONS)
    migrate_mod.migrate(verbose=False, db=db)

    clean = tmp_path / "clean.db"
    migrate_mod.migrate(verbose=False, db=clean)

    assert _shape(db)[0] == _shape(clean)[0], f"{name}: recovery did not reach the clean schema"
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    recorded = {r[0] for r in c.execute("SELECT filename FROM schema_migrations")}
    c.close()
    assert name in recorded, f"{name} was not recorded after the recovery run"


def test_every_table_rebuild_migration_is_one_transaction():
    """Stated over the FOLDER, so the next rebuild written is covered before anyone remembers it."""
    missing = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        s = p.read_text()
        rebuild = re.search(r"\bRENAME\s+TO\b", s, re.I) and re.search(r"\bCREATE\s+TABLE\b", s, re.I)
        if not rebuild:
            continue
        if not (re.search(r"^\s*BEGIN\s*;", s, re.I | re.M)
                and re.search(r"^\s*COMMIT\s*;", s, re.I | re.M)):
            missing.append(p.name)
    assert not missing, (
        "a table rebuild with no BEGIN/COMMIT auto-commits every statement, so an interrupted run "
        f"leaves the schema half built: {missing}")


def test_a_pragma_in_a_rebuild_sits_outside_its_transaction():
    """⚠️ A PRAGMA foreign_keys is a NO-OP inside a transaction, measured. 045 sets it off for the
    rebuild and back on after, so moving it inside the BEGIN would silently run that rebuild with
    foreign keys ON and change what the file does. This is why the wrap is per file and not a
    blanket wrap in migrate.py."""
    for p in sorted(MIGRATIONS.glob("*.sql")):
        s = p.read_text()
        if not re.search(r"PRAGMA\s+foreign_keys", s, re.I):
            continue
        body = re.search(r"^\s*BEGIN\s*;(.*?)^\s*COMMIT\s*;", s, re.I | re.M | re.S)
        if not body:
            continue
        inside = re.findall(r"^\s*PRAGMA\s+foreign_keys[^\n]*", body.group(1), re.I | re.M)
        assert not inside, (
            f"{p.name} sets PRAGMA foreign_keys inside its transaction, where it does nothing: "
            f"{inside}")
