"""The harness writes only to a database it made this run, and the proof is in the database.

⚠️ WHY THESE ARE NOT MORE ADDRESS TESTS. tests/test_live_guards.py and
tests/test_database_url_guard.py already cover the two name-based walls. The failure neither can
see is a harness pointed at a real database that is not live and is in no variable, which is what
dbmarker answers. So every test here works by taking a database the harness did NOT create and
checking that nothing is written to it, with its fingerprint read before and after.
"""
import ast
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbmarker                                                                # noqa: E402
import harness                                                                 # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _preexisting(path, rows=True):
    """A database the harness did not create, carrying live's own schema.

    ⚠️ BUILT FROM migrations/ RATHER THAN COPIED FROM LIVE, AND THE REASON IS SIZE, NOT
    CONVENIENCE. live is 344 MB and CI has no live at all, so a byte copy would make this test
    either slow or skipped, and a skipped test is the thing this whole round exists to avoid. What
    is under test is the property "a database this run did not create", which this file has.

    The real case was measured once, by hand, on a byte copy of live: the old harness wrote to it,
    upserting over five of the owner's real recipes, and the new one refuses it with the copy's
    sha256 unchanged. tests/dbmarker.py's docstring records what moved.
    """
    import migrate
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate.migrate(verbose=False, db=path)
    if rows:
        con = sqlite3.connect(path)
        con.execute("INSERT INTO recipes (id, name, created_at, source) VALUES (?, ?, ?, ?)",
                    ("somebodys-recipe", "Somebody's Recipe", "2026-01-01 00:00:00", "app"))
        con.commit()
        con.close()
    return path


# ---- the ordinary case: the harness marks what it builds -----------------------------------------

def test_the_harness_marks_the_database_it_builds(kitchen):
    con = sqlite3.connect(kitchen.db)
    token = con.execute(f'SELECT token FROM "{dbmarker.MARKER_TABLE}"').fetchone()[0]
    con.close()
    assert token == dbmarker.TOKEN, "the fixture database is not marked with this run's token"


def test_the_token_is_one_value_for_the_whole_run(kitchen, tmp_path):
    (tmp_path / "second").mkdir()
    second = harness.make_kitchen(tmp_path / "second")
    assert _token(kitchen.db) == _token(second.db) == dbmarker.TOKEN


def _token(db):
    con = dbmarker._open_ro(db)
    try:
        return dbmarker._token_of_sqlite(con)
    finally:
        con.close()


def test_a_marked_database_verifies(kitchen, tmp_path):
    dbmarker.verify_sqlite(kitchen.db, tmp_path)        # does not raise


def test_the_marker_survives_a_rebuild(kitchen):
    kitchen.rebuild()
    assert _token(kitchen.db) == dbmarker.TOKEN


# ---- the case the address checks cannot see ------------------------------------------------------

def test_a_preexisting_database_is_refused_with_nothing_written(tmp_path):
    """The brief's case: the harness is pointed at a database somebody else made.

    The fingerprint is read before and after, because "it raised" and "it wrote nothing" are
    different claims and only the second one matters.
    """
    db = _preexisting(tmp_path / "kit" / "test.db")
    before = _sha(db)
    with pytest.raises(dbmarker.Refused) as e:
        harness.make_kitchen(tmp_path / "kit")
    assert "did not create" in str(e.value)
    assert _sha(db) == before, "the harness wrote to a database it was supposed to refuse"


def test_an_empty_preexisting_database_is_refused_too(tmp_path):
    """⚠️ EMPTY IS NOT THE SAME AS OURS. A database with the schema and no rows still carries no
    marker, so it is still somebody else's, and a rule that let an empty one through would admit a
    freshly restored backup."""
    db = _preexisting(tmp_path / "kit" / "test.db", rows=False)
    before = _sha(db)
    with pytest.raises(dbmarker.Refused):
        harness.make_kitchen(tmp_path / "kit")
    assert _sha(db) == before


def test_a_database_from_an_earlier_run_is_refused(kitchen, tmp_path):
    """A marker is not a password, it is a RUN. Yesterday's fixture database has a marker and it is
    the wrong one, so writing to it is refused rather than quietly allowed."""
    con = sqlite3.connect(kitchen.db)
    con.execute(f'UPDATE "{dbmarker.MARKER_TABLE}" SET token = ?', ("a" * 32,))
    con.commit()
    con.close()
    before = _sha(kitchen.db)
    with pytest.raises(dbmarker.Refused) as e:
        dbmarker.verify_sqlite(kitchen.db, tmp_path)
    assert "a different run" in str(e.value)
    assert _sha(kitchen.db) == before


def test_a_database_with_the_marker_table_removed_is_refused(kitchen, tmp_path):
    con = sqlite3.connect(kitchen.db)
    con.execute(f'DROP TABLE "{dbmarker.MARKER_TABLE}"')
    con.commit()
    con.close()
    with pytest.raises(dbmarker.Refused) as e:
        dbmarker.verify_sqlite(kitchen.db, tmp_path)
    assert "carries no harness marker" in str(e.value)


def test_a_database_outside_the_temp_directory_is_refused(tmp_path):
    """The claim reads the PATH before anything opens it, so a target outside the directory pytest
    made for this test never gets as far as being created."""
    with pytest.raises(dbmarker.Refused) as e:
        dbmarker.claim_sqlite(tmp_path.parent / "elsewhere.db", temp_root=tmp_path)
    assert "outside its own temp directory" in str(e.value)


def test_a_symlink_out_of_the_temp_directory_is_refused(tmp_path):
    """⚠️ A PATH INSIDE THE DIRECTORY IS NOT A FILE INSIDE THE DIRECTORY. This is why the check
    reads PRAGMA database_list rather than trusting the path it was handed: the connection reports
    the file it opened, and a symlink resolves out of the temp root."""
    real = _preexisting(tmp_path / "outside" / "real.db")
    link = tmp_path / "kit" / "test.db"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real)
    before = _sha(real)
    with pytest.raises(dbmarker.Refused):
        dbmarker.verify_sqlite(link, temp_root=tmp_path / "kit")
    assert _sha(real) == before


def test_the_missing_database_case_refuses_rather_than_passing(tmp_path):
    """A check with nothing to read fails. An absent file is not a verified one."""
    with pytest.raises(dbmarker.Refused) as e:
        dbmarker.verify_sqlite(tmp_path / "nothing.db", temp_root=tmp_path)
    assert "there is no database at" in str(e.value)


# ---- the write doors ask every time --------------------------------------------------------------

def test_conn_refuses_once_the_marker_stops_matching(kitchen):
    """⚠️ THE CHECK IS ON THE DOOR, NOT ONLY AT BUILD TIME. Build-time-only would be defeated by
    anything that redirects the database after the fixture is made."""
    con = sqlite3.connect(kitchen.db)
    con.execute(f'DELETE FROM "{dbmarker.MARKER_TABLE}"')
    con.commit()
    con.close()
    with pytest.raises(dbmarker.Refused):
        kitchen.conn()


def test_session_refuses_once_the_marker_stops_matching(kitchen):
    con = sqlite3.connect(kitchen.db)
    con.execute(f'DELETE FROM "{dbmarker.MARKER_TABLE}"')
    con.commit()
    con.close()
    with pytest.raises(dbmarker.Refused):
        kitchen.session()


def test_rebuild_refuses_once_the_marker_stops_matching(kitchen):
    con = sqlite3.connect(kitchen.db)
    con.execute(f'DELETE FROM "{dbmarker.MARKER_TABLE}"')
    con.commit()
    con.close()
    with pytest.raises(dbmarker.Refused):
        kitchen.rebuild()


def test_the_kitchen_cannot_be_built_without_a_temp_root():
    """⚠️ A DEFAULT WOULD MAKE THE CHECK SKIPPABLE BY FORGETTING AN ARGUMENT. The one failure mode
    a guard must not have is being optional."""
    with pytest.raises(TypeError):
        harness.Kitchen("x.db", None)


def _marker_calls(func):
    """{(call name, first argument as source): ...} for every dbmarker.* call inside harness.<func>."""
    tree = ast.parse((REPO / "tests" / "harness.py").read_text())
    bodies = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert func in bodies, f"harness.py no longer defines {func}"
    out = {}
    for n in ast.walk(bodies[func]):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "dbmarker"):
            out[n.func.attr] = ast.unparse(n.args[0]) if n.args else None
    return out


@pytest.mark.parametrize("func,call,arg", [
    ("make_kitchen", "claim_sqlite", "db"),
    ("make_kitchen", "stamp_sqlite", "db"),
    ("conn", "verify_sqlite", "self.db"),
    # ⚠️ THE ARGUMENT IS THE ASSERTION, NOT THE CALL. An earlier version of this test checked only
    # that the NAME dbmarker.verify_sqlite appeared in the function, and both of these passed while
    # asking about the wrong database: the write opens the module global, which does not have to
    # equal self.db, and review demonstrated a write landing in an unmarked database with the check
    # satisfied. A pin that cannot see the argument cannot see this class of defect at all.
    ("session", "verify_sqlite", "app.DB"),
    ("rebuild", "verify_sqlite", "build_db.DB"),
    ("rebuild", "stamp_sqlite", "build_db.DB"),
])
def test_every_write_door_asks_about_the_database_it_will_open(func, call, arg):
    """⚠️ STATED STRUCTURALLY, SO THE NEXT EDIT OF harness.py CANNOT QUIETLY DROP IT. The review's
    question about this round was whether a fixture could write before the check runs, and the
    answer has to survive that edit."""
    calls = _marker_calls(func)
    assert call in calls, f"{func} no longer calls dbmarker.{call}"
    assert calls[call] == arg, \
        f"{func} calls dbmarker.{call}({calls[call]}) and the write opens {arg}"


def test_the_postgres_truncate_asks_before_it_truncates():
    """The same structural pin on the other dialect's only write door, which a local run cannot
    exercise against a real server. The order matters: the claim has to precede the TRUNCATE."""
    body = (REPO / "tests" / "pg_harness.py").read_text().split("def reset_and_seed")[1]
    # the STATEMENT, not the docstring that describes it
    claim, truncate = body.find("claim_or_verify_pg"), body.find('text("TRUNCATE ')
    assert claim != -1, "reset_and_seed no longer asks the database for the marker"
    assert truncate != -1, "reset_and_seed no longer truncates, so this pin describes nothing"
    assert claim < truncate, "the marker check runs AFTER the truncate, which is no check at all"


# ---- the Postgres rules, as far as they can be read without a server ----------------------------

def test_the_url_and_the_connection_are_compared_by_one_rule():
    """`urlguard.effective_database` is what pg_harness compares current_database() against, and it
    is the same function the startup guard reads the name with. Two answers to "which database
    would open" is the defect that round's review found twice."""
    import urlguard
    url = "postgresql+psycopg://postgres:pw@localhost:5432/recipe_test"
    assert urlguard.effective_database(url) == "recipe_test"
    # the query string wins, which is exactly why the comparison exists
    assert urlguard.effective_database(url + "?dbname=something_else") == "something_else"
    assert urlguard.effective_database(None) is None
    assert urlguard.effective_database("not a url at all") is None


def test_an_empty_postgres_database_is_claimable_and_a_full_one_is_not():
    """The claim rule itself, with the counting done against a SQLite connection standing in for the
    server.

    ⚠️ THIS IS THE RULE, NOT THE INTEGRATION. The real thing runs in CI's Postgres leg
    (tests/test_pg_integration.py), because to_regclass and current_database() are Postgres's own.
    What is checked here is the decision: rows present means refuse, no rows means claim.
    """
    assert dbmarker._rows_anywhere.__doc__, "the emptiness proof lost its reason"
    src = (REPO / "tests" / "dbmarker.py").read_text()
    body = src.split("def claim_or_verify_pg")[1]
    assert "current_database()" in body, "the connection is no longer asked which database it is"
    assert "_rows_anywhere" in body, "a database with no marker is no longer required to be empty"
    assert body.find("_rows_anywhere") < body.find("_stamp_pg"), \
        "the stamp happens before the emptiness proof, so a full database would be claimed"


def test_rebuild_asks_about_the_database_build_db_will_open(kitchen, tmp_path):
    """⚠️ REPRODUCED FROM THE REVIEW. Rebinding build_db.DB and calling rebuild() re-ran the whole
    migration chain and the seed over a database this run did not create, and then stamped the one
    it had NOT rebuilt. The victim's bytes are read before and after."""
    import build_db
    victim = _preexisting(tmp_path / "victim" / "real.db")
    before = _sha(victim)
    build_db.DB = victim
    try:
        with pytest.raises(dbmarker.Refused):
            kitchen.rebuild()
    finally:
        build_db.DB = kitchen.db
    assert _sha(victim) == before, "rebuild wrote to a database it was supposed to refuse"
    assert _token(victim) is None, "rebuild marked a database it did not create"


def test_session_asks_about_the_database_the_factory_will_open(kitchen, tmp_path):
    """The same shape on the other global. orm_session() reads app.DB at call time."""
    import app
    victim = _preexisting(tmp_path / "victim2" / "real.db")
    before = _sha(victim)
    app.DB = victim
    try:
        with pytest.raises(dbmarker.Refused):
            kitchen.session()
    finally:
        app.DB = kitchen.db
    assert _sha(victim) == before


def test_a_temp_root_that_is_not_a_temp_directory_is_refused():
    """⚠️ THE CLAUSE THAT WAS TAUTOLOGICAL AT ITS ONLY REAL CALL SITE. make_kitchen derives the path
    and the root from the same argument, so "inside its own temp directory" was true by
    construction, and a harness aimed at a real directory full of databases got as far as building
    in it. Whether the root is a temporary directory is the part the caller cannot answer for
    itself. Nothing is written either way, so this is safe to point at the repo."""
    with pytest.raises(dbmarker.Refused) as e:
        dbmarker.claim_sqlite(REPO / "nothing-is-created.db", temp_root=REPO)
    assert "is not inside this machine's temporary directory" in str(e.value)
    assert not (REPO / "nothing-is-created.db").exists()


def test_pytest_s_own_temp_directory_passes_that_clause(tmp_path):
    """The other direction, because a guard that refused pytest's own directory would be useless."""
    assert dbmarker._in_a_temp_dir(tmp_path)
    dbmarker.claim_sqlite(tmp_path / "fine.db", temp_root=tmp_path)      # does not raise


def test_an_unreadable_database_url_refuses_rather_than_skipping_the_comparison():
    """⚠️ FAIL CLOSED, LIKE THE REST OF THE GUARDS. `if expected_db and ...` meant a URL this
    environment cannot resolve removed the current_database() comparison, leaving the marker as the
    whole answer at the moment the one thing that could say where the connection went was
    unreadable. Pinned structurally, because current_database() is Postgres's own and the live
    version runs in CI's Postgres leg."""
    body = (REPO / "tests" / "dbmarker.py").read_text().split("def claim_or_verify_pg")[1]
    guard = body.find("expected_db is None")
    marker = body.find("MARKER_TABLE")
    assert guard != -1, "an unresolvable URL no longer refuses"
    assert guard < marker, "the refusal happens after the marker is read, so it is not the first word"
    assert "if expected_db and" not in body, "the permissive form is back"
