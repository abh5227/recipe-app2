"""The suite's check on the DATABASE ITSELF, rather than on its address.

⚠️ EVERY OTHER GUARD HERE ANSWERS A QUESTION ABOUT A NAME. `dbguard` compares a path, and its
device and inode, against live. `urlguard` reads $DATABASE_URL and asks the dialect what it would
open. Both answer WHERE a database is, and neither can see the case with no name worth checking: a
harness pointed at a real database that is not live and sits in no variable. A copy of live under
another name, a restored backup, a colleague's Postgres, the test database a previous round left
full. Every one of those has an address the other guards read as harmless.

This module asks a different question. The harness MARKS the database it creates with a token
minted once per run, and every path that writes, truncates or drops asks the connected database for
that token before it does anything. A database this run did not create cannot produce the token, so
it is refused whatever it is called. The address checks stay in front of this one as the first line.

⚠️ MEASURED ON A BYTE COPY OF LIVE, NOT REASONED ABOUT. The old `make_kitchen`, pointed at a
directory holding a 344 MB copy of live named `test.db`, ran `build_db.build()` against it and
WROTE. The five fixture recipe ids are also five of the owner's real recipes, so `seed_content`
upserted over them: `aloo-gobhi` lost its description, notes, image, source url and two of its
times, `bulgogi-bowls` went from 7 method steps to 4, and all five had their `source` tier
rewritten. Beside that it inserted the 36 ingredients, 65 seasons, 102 region links and 44 regions
that migration 046 deleted on purpose. The same copy under the check below is refused with its
sha256 unchanged.

⚠️ WHAT IT DOES NOT COVER, STATED RATHER THAN IMPLIED. The marker governs the harness's own
create, rebuild and truncate paths, which are the ones that run migrations, seed, TRUNCATE and
DROP. It is not wired into `sqlite3.connect` itself, because the suite legitimately builds other
databases (a replayed migration chain, a mined-corpus fixture, a sources file) and a blanket rule
would refuse those. Writes the app makes through a test client reach the database the harness
claimed and stamped, which is the thing this check is about.
"""
import datetime
import os
import pathlib
import sqlite3
import tempfile
import uuid

MARKER_TABLE = "_harness_marker"

# Named here only so a refusal can print it without importing urlguard.
ENV_URL_NAME = "DATABASE_URL"

# ⚠️ ONE TOKEN PER PROCESS, MINTED AT IMPORT. Under pytest-xdist each worker is its own process and
# gets its own token, which is the right granularity: a worker may write only what it created.
TOKEN = uuid.uuid4().hex


class Refused(RuntimeError):
    """The harness will not write to a database it cannot prove it made this run."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_CREATE = (f'CREATE TABLE IF NOT EXISTS "{MARKER_TABLE}" '
           "(token TEXT NOT NULL, stamped_at TEXT NOT NULL, pid INTEGER NOT NULL)")


# ---- SQLite ------------------------------------------------------------------------------------

def _open_ro(path):
    """⚠️ THE CHECK ITSELF CANNOT WRITE. mode=ro means SQLite refuses a write rather than trusting
    this module to attempt none, which is the same rule scripts/gates/state.py follows."""
    return sqlite3.connect(f"file:{pathlib.Path(path)}?mode=ro", uri=True)


def _in_a_temp_dir(root):
    """Is this temp root really a temporary directory?

    ⚠️ WITHOUT THIS, THE "INSIDE ITS OWN TEMP DIRECTORY" CLAUSE IS TAUTOLOGICAL WHERE IT MATTERS.
    make_kitchen derives both arguments from the same value, `db = tmp_path/"test.db"` and
    `temp_root = tmp_path`, so `_inside(db, temp_root)` is True there by construction, and the only
    thing refusing a harness pointed at a real directory was the token check on a file that happened
    to be named `test.db`. Whether the root is a temporary directory is a question the caller's own
    argument cannot answer for itself, and pytest's tmp_path always is, because pytest builds it
    from tempfile.gettempdir()."""
    try:
        return pathlib.Path(root).resolve().is_relative_to(
            pathlib.Path(tempfile.gettempdir()).resolve())
    except (OSError, ValueError, TypeError):
        return False


def _inside(path, root):
    """Is `path` inside `root`, both resolved? Neither has to exist."""
    try:
        return pathlib.Path(path).resolve().is_relative_to(pathlib.Path(root).resolve())
    except (OSError, ValueError, TypeError):
        return False                                 # unanswerable reads as outside


def _main_file(con):
    """The file the connection has ACTUALLY opened, from the connection itself.

    ⚠️ A PATH IS WHAT YOU ASKED FOR AND THIS IS WHAT YOU GOT. `PRAGMA database_list` reports the
    file behind the `main` schema, so a symlink, a relative path or a redirect resolves here rather
    than in the caller's head."""
    for _seq, name, file in con.execute("PRAGMA database_list"):
        if name == "main":
            return file
    return ""


def _token_of_sqlite(con):
    try:
        row = con.execute(f'SELECT token FROM "{MARKER_TABLE}" LIMIT 1').fetchone()
    except sqlite3.Error:
        return None                                  # no marker table at all
    return row[0] if row else None


def _opened_by(con):
    """The file behind a LIVE SQLAlchemy connection's `main` schema, asked of the connection."""
    for row in con.exec_driver_sql("PRAGMA database_list"):
        if row[1] == "main":
            return row[2]
    return ""


def verify_session(session, temp_root):
    """Refuse unless the database THIS SESSION ACTUALLY OPENED is one this run made.

    ⚠️ THE PATH AND THE CONNECTION ARE DIFFERENT QUESTIONS, AND $DATABASE_URL IS WHERE THEY PART.
    `app.orm_session()` composes its URL as `$DATABASE_URL or sqlite:///{app.DB}`, reading the
    environment on EVERY call, while `tests/urlguard.py` reads that variable once at conftest
    import. A test that sets it mid-run therefore reaches a database no guard has seen, and
    `verify_sqlite(app.DB, ...)` went on answering about the file the path named. Measured: with a
    kitchen built and marked, one `monkeypatch.setenv("DATABASE_URL", "sqlite:///<decoy>")` left
    the check inspecting the marked `test.db` while the session opened the unmarked decoy and the
    INSERT landed there, with nothing raised. That is the same defect `_main_file` exists to stop,
    one level further up: a path is what you asked for, and this is what you got.

    The URL is checked first and the connection second, which is the order the rest of this module
    uses. An out-of-tree SQLite path is refused before anything is opened; what the connection
    reports is then the authoritative answer, because a symlink or a redirect resolves there and
    not in the caller's head.

    ⚠️ POSTGRES HAS NO FILE, SO `temp_root` GOVERNS SQLITE ONLY. On that dialect the token is the
    whole check here, which is what `claim_or_verify_pg` already establishes at reset.
    """
    def refuse(message):
        session.close()
        raise Refused(message)

    bind = session.get_bind()                        # the engine, WITHOUT opening a connection
    sqlite = bind.dialect.name == "sqlite"
    named = bind.url.database
    if sqlite and named and not _inside(named, temp_root):
        refuse(f"\n\nthe harness refuses to write:\n  this session is bound to {named}, which is "
               f"OUTSIDE its own temp directory {temp_root}.\n  app.orm_session() prefers "
               f"${ENV_URL_NAME} over app.DB, so the path the harness was handed is not "
               f"necessarily\n  the database a write opens.\n")

    con = session.connection()
    if sqlite:
        opened = _opened_by(con)
        if not opened:
            refuse(f"\n\nthe harness refuses to write:\n  this session reports no file behind its "
                   f"main schema, so there is nothing to identify\n")
        if not _inside(opened, temp_root):
            refuse(f"\n\nthe harness refuses to write:\n  this session opened {opened}, which is "
                   f"OUTSIDE its own temp directory {temp_root}.\n  The harness writes only inside "
                   f"the directory pytest made for this test.\n")
    try:
        token = con.exec_driver_sql(f'SELECT token FROM "{MARKER_TABLE}" LIMIT 1').scalar()
    except Exception:                                # no marker table at all, on either dialect
        token = None
    if token is None:
        refuse(f"\n\nthe harness refuses to write:\n  the database this session opened carries no "
               f"harness marker, so it is one this run did not create.\n  A copy of live, a "
               f"restored backup and a colleague's database all look like this.\n")
    if token != TOKEN:
        refuse(f"\n\nthe harness refuses to write:\n  the database this session opened is marked "
               f"{token[:8]}… and this run is {TOKEN[:8]}….\n  It was made by a different run, so "
               f"it is not this run's to write.\n")


def stamp_sqlite(path):
    """Mark a database this run created. Idempotent, and it replaces an older run's token."""
    con = sqlite3.connect(str(path))
    try:
        con.execute(_CREATE)
        con.execute(f'DELETE FROM "{MARKER_TABLE}"')
        con.execute(f'INSERT INTO "{MARKER_TABLE}" (token, stamped_at, pid) VALUES (?, ?, ?)',
                    (TOKEN, _now(), os.getpid()))
        con.commit()
    finally:
        con.close()


def verify_sqlite(path, temp_root):
    """Refuse unless this database is one this run made, inside the harness's own temp directory."""
    p = pathlib.Path(path)
    if not p.exists():
        raise Refused(f"\n\nthe harness refuses to write:\n  there is no database at {p}, so "
                      f"nothing can be checked before writing to it\n")
    con = _open_ro(p)
    try:
        opened = _main_file(con)
        token = _token_of_sqlite(con)
    finally:
        con.close()

    if not opened:
        raise Refused(f"\n\nthe harness refuses to write:\n  the connection to {p} reports no file "
                      f"behind its main schema, so there is nothing to identify\n")
    if not _inside(opened, temp_root):
        raise Refused(
            f"\n\nthe harness refuses to write:\n  it opened {opened}, which is OUTSIDE its own "
            f"temp directory {temp_root}.\n  The harness writes only inside the directory pytest "
            f"made for this test.\n")
    if token is None:
        raise Refused(
            f"\n\nthe harness refuses to write:\n  {p} carries no harness marker, so it is a "
            f"database this run did not create.\n  A copy of live, a restored backup and a "
            f"colleague's database all look like this, whatever the path says.\n")
    if token != TOKEN:
        raise Refused(
            f"\n\nthe harness refuses to write:\n  {p} is marked {token[:8]}… and this run is "
            f"{TOKEN[:8]}….\n  It was made by a different run, so it is not this run's to write.\n")


def claim_sqlite(path, temp_root):
    """The harness is about to CREATE this database.

    Two cases are allowed and one is not. A path that does not exist is the ordinary case, and the
    harness is free to make it. A path that exists and carries THIS run's token is one the harness
    already made, so rebuilding it is allowed. Anything else is somebody else's database and is
    refused with nothing written, which is what keeps a copy of live intact.
    """
    p = pathlib.Path(path)
    if not _in_a_temp_dir(temp_root):
        raise Refused(
            f"\n\nthe harness refuses to build:\n  {temp_root} is not inside this machine's "
            f"temporary directory ({tempfile.gettempdir()}).\n  A fixture database is made in a "
            f"directory pytest created for one test, never somewhere a real one could be sitting.\n")
    if not _inside(p, temp_root):
        raise Refused(
            f"\n\nthe harness refuses to build:\n  {p} is outside its own temp directory "
            f"{temp_root}.\n  A fixture database is made inside the directory pytest handed this "
            f"test, and nowhere else.\n")
    if p.exists():
        verify_sqlite(p, temp_root)


# ---- Postgres ----------------------------------------------------------------------------------

def _scalar(conn, sql, **params):
    from sqlalchemy import text
    return conn.execute(text(sql), params).scalar()


def _stamp_pg(conn):
    from sqlalchemy import text
    conn.execute(text(_CREATE))
    conn.execute(text(f'DELETE FROM "{MARKER_TABLE}"'))
    conn.execute(text(f'INSERT INTO "{MARKER_TABLE}" (token, stamped_at, pid) '
                      "VALUES (:t, :s, :p)"), {"t": TOKEN, "s": _now(), "p": os.getpid()})


def _rows_anywhere(conn, content_tables):
    """Every table that exists and is not empty, as (name, count). The proof a database is unused.

    ⚠️ THE NAME IS CAST, NOT JUST BOUND. `to_regclass(:t)` leaves Postgres inferring the type of an
    untyped placeholder, which is the kind of thing that works on one driver and fails on another,
    and this file cannot be exercised against a real server from the machine it was written on."""
    found = []
    for name in content_tables:
        if _scalar(conn, "SELECT to_regclass(CAST(:t AS text))", t=name) is None:
            continue
        n = _scalar(conn, f'SELECT count(*) FROM "{name}"')
        if n:
            found.append((name, n))
    return found


def claim_or_verify_pg(conn, expected_db, content_tables):
    """Refuse unless this Postgres database is the harness's to truncate, and mark it when it is.

    ⚠️ THE HARNESS DOES NOT CREATE THE POSTGRES DATABASE, SO THE FIRST CLAIM HAS TO BE EARNED.
    CI's service creates it and `alembic upgrade head` builds the schema, so the first
    reset_and_seed of a run meets a database with no marker. It may claim one only when every
    content table is EMPTY, which a database anybody cares about is not. After that the token is
    the whole check.

    A marker holding a DIFFERENT token is a harness database from an earlier run, which is what a
    developer reusing one test database sees on their second run. The marker table's presence is
    the evidence, since nothing but this module ever creates it, so the token is replaced and the
    run proceeds.

    Returns "claimed", "reclaimed" or "verified", so a caller can say which happened.
    """
    actual = _scalar(conn, "SELECT current_database()")
    if expected_db is None:
        # ⚠️ FAILS CLOSED, THE WAY corpus_guard AND urlguard._same_file DO. A URL this environment
        #    cannot resolve used to mean "skip the comparison", which left the marker as the whole
        #    answer at exactly the moment the one thing that could say where the connection went was
        #    unreadable. Unanswerable is refused, never allowed.
        raise Refused(
            f"\n\nthe harness refuses to truncate:\n  it is connected to {actual!r} and nothing "
            f"here can say which database ${ENV_URL_NAME} names, so the two cannot be compared.\n")
    if actual != expected_db:
        raise Refused(
            f"\n\nthe harness refuses to truncate:\n  it is connected to the database {actual!r} "
            f"and $DATABASE_URL resolves to {expected_db!r}.\n  What opened is not what the URL "
            f"appears to say, so nothing here can tell what would be truncated.\n")

    if _scalar(conn, "SELECT to_regclass(CAST(:t AS text))", t=MARKER_TABLE) is None:
        held = _rows_anywhere(conn, content_tables)
        if held:
            shown = ", ".join(f"{name} {n}" for name, n in held[:6])
            raise Refused(
                f"\n\nthe harness refuses to truncate:\n  the database {actual!r} carries no "
                f"harness marker and is NOT empty ({shown}).\n  A database this run did not create "
                f"and that holds rows is somebody's data. The suite creates its own.\n")
        _stamp_pg(conn)
        return "claimed"

    token = _scalar(conn, f'SELECT token FROM "{MARKER_TABLE}" LIMIT 1')
    if token == TOKEN:
        return "verified"
    _stamp_pg(conn)                                  # a harness database from an earlier run
    return "reclaimed"
