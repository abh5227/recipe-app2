"""Suite-wide assertion that no test opens the LIVE database.

WHY THIS EXISTS, WITH THE CASE THAT CAUSED IT. The harness redirects `app.DB`, `build_db.DB` and
`migrate.DB` to a temp database, and that redirect was believed to be the whole boundary. It is not.
A test that names a path itself reaches straight past it, and one did: the first version of the
corpus-pass guard test set `sys.argv` to the live database path and called `main()`, so
`corpus_guard.refuse_live` was the only thing between an ordinary `pytest` run and a real migration
of the 300-recipe live database. For `apply_plan_ahead_proposals`, which wrote by default, there was
not even an `--apply` to withhold. A reviewer broke that guard the way a regression would and watched
the test write and commit.

A redirect protects the door it is nailed to. This protects the wall. The same shape as
tests/netguard.py, for the same reason.

WHAT IS BLOCKED: any `sqlite3.connect` whose target IS the live file, by FILE IDENTITY rather than by
the spelling of its path. `./recipes.db`, `scripts/../recipes.db`, a symlink and a HARD LINK all open
the same file, and a string comparison would let the last one through. SQLAlchemy's SQLite dialect
calls the same function, so `app.orm_session()` and `models.engine` are covered by one patch.

WHAT IS NOT BLOCKED, DELIBERATELY: a test marked `live_catalog`, and then only for a READ-ONLY
`mode=ro` URI. tests/test_mining_boundaries.py checks the real 10,500-entry library catalog against
the brand rules, and a fixture database has the tables with no rows, so a check written only against
one is vacuous. Those tests open live read-only and skip when it is absent. The marker makes that a
visible, reviewable choice instead of an accident, and a marked test that tries to open live for
WRITING is refused like any other.
"""
import os
import sqlite3
import sqlite3.dbapi2

_REAL = sqlite3.connect
_LIVE = None            # (st_dev, st_ino) of the live file, or None when there is no live file
_LIVE_PATH = None
_ALLOW_RO = False


class LiveDatabaseOpened(AssertionError):
    """Raised when a test opens the live recipes.db."""


def _identity(path):
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (st.st_dev, st.st_ino)


def _target_of(database):
    """The filesystem path a sqlite3.connect argument names, or None for :memory: and the like."""
    if isinstance(database, (bytes, os.PathLike)):
        database = os.fspath(database)
        if isinstance(database, bytes):
            database = database.decode("utf-8", "replace")
    if not isinstance(database, str) or not database or database == ":memory:":
        return None, False
    if database.startswith("file:"):
        body, _, query = database[5:].partition("?")
        if body.startswith("//"):            # file://host/path — the authority is empty in practice
            body = body[2:].partition("/")[2]
            body = "/" + body
        read_only = any(p in ("mode=ro", "mode=rom") for p in query.split("&"))
        return body or None, read_only
    return database, False


def _check(database):
    if _LIVE is None and _LIVE_PATH is None:
        return
    target, read_only = _target_of(database)
    if target is None:
        return
    same = False
    try:
        same = os.path.realpath(target) == _LIVE_PATH
    except (OSError, ValueError):
        pass
    if not same and _LIVE is not None:
        same = _identity(target) == _LIVE
    if not same:
        return
    if read_only and _ALLOW_RO:
        return
    raise LiveDatabaseOpened(
        f"a test tried to open the LIVE database ({_LIVE_PATH}) as {database!r}.\n"
        f"  Nothing in the suite may open it. Use the `kitchen` fixture, or tmp_path.\n"
        f"  A test that genuinely needs the real library catalog marks itself\n"
        f"  @pytest.mark.live_catalog and opens it with a file:...?mode=ro URI."
        + ("" if read_only else "\n  This open was NOT read-only, which no marker permits."))


def _guarded(database=":memory:", *args, **kwargs):
    _check(database)
    return _REAL(database, *args, **kwargs)


def install(live_path):
    """Patch sqlite3.connect. Called at conftest IMPORT so collection-time code is covered too."""
    global _LIVE, _LIVE_PATH
    _LIVE_PATH = os.path.realpath(live_path)
    _LIVE = _identity(_LIVE_PATH)
    sqlite3.connect = _guarded
    sqlite3.dbapi2.connect = _guarded        # SQLAlchemy's dialect holds the dbapi2 module


def set_read_only_allowed(allowed):
    global _ALLOW_RO
    _ALLOW_RO = bool(allowed)
