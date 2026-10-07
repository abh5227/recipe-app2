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


# Every migration that opens a transaction, rebuild or not. A rebuild is the loudest case and not
# the only one, and the go-live step for the titles round asked the question directly: force 062 to
# fail partway through on a copy and the database must be left exactly as it was.
TRANSACTIONAL = [n for n in _all_migrations()
                 if re.search(r"^\s*BEGIN\s*;", (MIGRATIONS / n).read_text(), re.I | re.M)]


def _truncate_before_commit(sql):
    """The file as a crash before its final COMMIT would leave it."""
    i = [m.start() for m in re.finditer(r"^\s*COMMIT\s*;", sql, re.I | re.M)][-1]
    return sql[:i]


@pytest.mark.parametrize("name", TRANSACTIONAL)
def test_a_migration_interrupted_inside_its_transaction_leaves_nothing_behind(
        tmp_path, monkeypatch, name):
    """⚠️ STATED OVER EVERY TRANSACTIONAL MIGRATION, NOT OVER THE REBUILDS. The six rebuilds are the
    case that hurts most and the question is the same for an ALTER: 062 adds recipe_notes.title with
    a CHECK, and the go-live for that round had to show that a failure partway through leaves the
    database byte-identical and the app still serving it. Two shapes were measured on a copy of live
    at migration 061, a statement erroring after the ALTER and the process being killed before the
    COMMIT, and both came back with the same sha256. This is that check, generalized and in CI.

    ⚠️ AND THE FILENAME MUST NOT BE RECORDED. migrate.py tracks by filename only, so a file recorded
    after a half-run can never be retried and the drift is permanent."""
    sql = (MIGRATIONS / name).read_text()
    db = _build_up_to(tmp_path, name, monkeypatch, name=f"t-{name}.db")
    before = _shape(db)
    _replay(db, _truncate_before_commit(sql))
    after = _shape(db)

    assert after[0] == before[0], (
        f"{name} interrupted before its COMMIT changed the schema.\n"
        f"  gone:  {[r[1] for r in before[0] if r not in after[0]]}\n"
        f"  added: {[r[1] for r in after[0] if r not in before[0]]}")
    assert after[1] == before[1], f"{name} interrupted before its COMMIT changed row counts"

    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    recorded = {r[0] for r in c.execute("SELECT filename FROM schema_migrations")}
    c.close()
    assert name not in recorded, f"{name} was recorded as applied after being interrupted"

    # and the retry works, which is the other half of all-or-nothing
    monkeypatch.setattr(migrate_mod, "MIGRATIONS_DIR", MIGRATIONS)
    migrate_mod.migrate(verbose=False, db=db)
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    recorded = {r[0] for r in c.execute("SELECT filename FROM schema_migrations")}
    c.close()
    assert name in recorded, f"{name} did not apply after the interrupted run"


# ⚠️ THE EXEMPTION LIST IS EMPTY, AND IT STAYS A SET RATHER THAN BECOMING NOTHING. Seven older
# additive migrations (009, 013, 015, 018, 027, 031, 048) ran for months with no transaction. Each
# adds two or more statements under one `executescript`, which auto-commits every one of them, so an
# interrupted run left columns added with the filename unrecorded and the retry died forever on
# "duplicate column name". 031 was the worst: two ADD COLUMNs then two UPDATEs, so the backfill could
# be missing with the columns in place and nothing saying so.
#
# All seven were wrapped on 2026-10-07. Live and every other database past them is untouched by that
# edit, because migrate.py tracks by filename and never by checksum, and a fresh install's schema and
# seeded data were proved byte-identical before and after
# (tests/test_migration_equivalence.py). The forced-failure proof for each one is
# test_a_migration_interrupted_inside_its_transaction_leaves_nothing_behind above, which reads the
# folder and so picked all seven up the moment they carried a BEGIN.
#
# ⚠️ ANYTHING ADDED HERE NEEDS A REASON NEXT TO IT AND A DECISION BEHIND IT. An empty list means the
# rule below holds over every migration in the folder with nothing excused.
UNWRAPPED_ADDITIVE = set()


def test_an_additive_column_migration_carries_its_own_transaction():
    """⚠️ AN `ALTER TABLE ... ADD COLUMN` LOOKS ATOMIC ON ITS OWN AND THE FILE IS NOT. A migration
    that adds a column and then backfills it, or adds two, is several auto-committing statements
    under executescript, and the half-applied result is a schema the deploy's code has no name for,
    with a retry that can never succeed. Stated over the folder so the next additive migration is
    covered before anyone remembers it. 062, the titles round's own, carries its BEGIN/COMMIT."""
    missing = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        s = p.read_text()
        if not re.search(r"\bADD\s+COLUMN\b", s, re.I):
            continue
        # one bare ALTER and nothing else is atomic by itself, which is what SQLite guarantees
        statements = [x for x in (t.strip() for t in s.split(";"))
                      if x and not x.startswith("--")]
        body = [x for x in statements
                if not re.match(r"^(BEGIN|COMMIT|PRAGMA)\b", x, re.I)
                and not x.lstrip().startswith("--")]
        if len(body) <= 1:
            continue
        if not (re.search(r"^\s*BEGIN\s*;", s, re.I | re.M)
                and re.search(r"^\s*COMMIT\s*;", s, re.I | re.M)):
            missing.append(p.name)
    assert set(missing) <= UNWRAPPED_ADDITIVE, (
        "a migration with more than one statement auto-commits each of them under executescript, "
        "so an interrupted run leaves a schema nothing was written against and a retry that dies "
        f"on a duplicate column: {sorted(set(missing) - UNWRAPPED_ADDITIVE)}")
    gone = UNWRAPPED_ADDITIVE - set(missing)
    assert not gone, (
        f"these were fixed and the exemption list was not updated: {sorted(gone)}")


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
