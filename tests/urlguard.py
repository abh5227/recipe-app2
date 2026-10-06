"""The wall in front of $DATABASE_URL, so the suite cannot run against a database it did not make.

⚠️ THE PATH IS A LIE WHEN $DATABASE_URL IS SET, AND THE TEST HARNESS NEVER KNEW. `make_kitchen`
redirects `app.DB` / `build_db.DB` / `migrate.DB` to a throwaway file, and `app.orm_session()` prefers
$DATABASE_URL over the file it was handed. So one exported variable sends every fixture, every write
and every `--apply` straight past the redirect. Measured with the two lines the passes use:
`refuse_live` passed a copy under /tmp, the engine opened the test Postgres, and the pass read 6
recipes where the copy holds 300. The corpus passes learned this and `refuse_live` exits unless the
run says `--i-mean-live`. The suite did not, and `pytest` on a machine with $DATABASE_URL pointing at
production would have run 2,586 tests, fixtures and writes included, against production.

⚠️ SETTING IT IS NOT ENOUGH TO ALLOW IT. The Postgres CI leg sets it on purpose, which is the whole
reason it cannot simply be banned, so the run has to SAY it is a test database:
$RECIPE_APP_TEST_DATABASE=1 beside it. A variable inherited from a shell, a direnv file or a parent
process carries no such declaration, and that is exactly the case this exists to catch.

⚠️ AND A DECLARATION IS NOT ENOUGH EITHER. "I meant it" does not make a production URL safe, so a
declared URL is still checked: never the live file under any spelling, never a bare `file:` URI, and
a Postgres database whose NAME does not say test is refused. The three refusals are separate, so a
URL cannot satisfy one and skip another.

Pure functions, so the rules are testable without an environment and without opening anything. See
tests/test_database_url_guard.py.
"""
import os
import pathlib
import re

ENV_URL = "DATABASE_URL"
ENV_DECLARE = "RECIPE_APP_TEST_DATABASE"

# A test Postgres database says so in its NAME, as a WHOLE WORD. "recipe_test", "test_recipes",
# "test" and "ci-test" pass. Checked on the name alone, because a host can be tunneled and a user
# can be anyone, and the name is the thing a person types when they make a throwaway.
#
# ⚠️ NO BARE PREFIX OR SUFFIX ALTERNATIVE. This read `|^test|test$` as well, which matched "latest",
# "greatest", "contest", "protest", "attest", "testing" and "testimonials", so
# postgresql://postgres@db.prod.internal/latest was ALLOWED. The boundary form below already matches
# every name the suite blesses, so the alternatives cost nothing to delete and admitted a whole
# class of production names.
_TEST_NAME = re.compile(r"(^|[_\-])test([_\-]|$)", re.IGNORECASE)

class Refused(RuntimeError):
    """Raised at suite import. Loud on purpose: a silent redirect is the defect."""


class Unparseable(Exception):
    """The URL is not one SQLAlchemy can read, so nothing here can reason about it."""


# Query keywords that REDIRECT the connection somewhere other than the URL's own path. The psycopg
# dialect does `opts.update(url.query)` after mapping database -> dbname, so any libpq keyword here
# wins over everything in front of the "?".
_REDIRECTING_QUERY = ("dbname", "database", "host", "hostaddr", "port", "user", "password",
                      "service", "passfile")


def _effective_database(parsed):
    """What the DIALECT will actually connect to, query string included.

    ⚠️ make_url().database IS NOT WHAT GETS OPENED, AND BELIEVING IT WAS IS THIS FILE'S SECOND
    VERSION OF THE SAME MISTAKE. The first version split the URL by hand. The second asked
    make_url and called that "the one parser that opens the connection", which is still false:
    `_PGDialect_common_psycopg.create_connect_args` runs `opts.update(url.query)` after mapping
    database to dbname, so a query string overrides the path.
    `postgresql+psycopg://postgres:pw@db.prod.internal:5432/test?dbname=recipes_production` reads
    as the database "test", passes the whole-word test rule, and opens recipes_production. With the
    declaration set that is a pytest run whose fixture harness TRUNCATEs every table in production.
    The dialect's own create_connect_args is the answer, because it IS the thing that opens it."""
    dialect = parsed.get_dialect()()                 # the class only, nothing connects
    _args, opts = dialect.create_connect_args(parsed)
    return opts.get("dbname") or opts.get("database") or parsed.database


def effective_database(url):
    """The database name a URL would actually open, or None when it cannot be read.

    The public form of the rule above, for a caller that needs the same answer. tests/pg_harness.py
    compares it against the connection's own `current_database()`, and asking it here rather than
    re-deriving it there is what keeps one answer to the question."""
    if not url:
        return None
    try:
        return _effective_database(_parse(url))
    except Exception:                                # unreadable URL: the caller gets no claim
        return None


def _parse(url):
    """The URL as SQLAlchemy reads it.

    ⚠️ ONE PARSER, AND IT IS THE ONE THAT OPENS THE CONNECTION. This file used to split the URL by
    hand, which put a SECOND parser beside the real one, and the two disagreed. `_pg_database`
    split on the first "/" after the scheme, so a password containing a "/" moved the split left:
    `postgresql+psycopg://admin:xy/test@prod.example.com:5432/recipes` yielded a "database name" of
    `test@prod.example.com:5432/recipes`, which the old name test matched on its `^test`
    alternative, and the guard ALLOWED a production connection that SQLAlchemy then opened as
    host=prod.example.com database=recipes. A "/" is ordinary in a random or base64 password.
    `make_url` is already a dependency and already what app.orm_session() feeds, so it is the only
    thing here entitled to say what a URL means."""
    from sqlalchemy.engine import make_url            # already a dependency of the app
    from sqlalchemy.exc import ArgumentError
    try:
        return make_url(url)
    except (ArgumentError, ValueError) as e:
        raise Unparseable(str(e)) from None


def _redact(url):
    """The URL with any password removed, so a refusal can be printed and pasted."""
    try:
        parsed = _parse(url)
    except Unparseable:
        return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)
    return parsed.render_as_string(hide_password=True)


def check(url, declared, live_db=None):
    """The rule. Returns None when this run may proceed, or the reason it may not.

    `url` is $DATABASE_URL as given (None or "" means unset). `declared` is whether the run set
    $RECIPE_APP_TEST_DATABASE. `live_db` is the live database's path, for the identity test.
    """
    if not url or not url.strip():
        return None                                     # unset: the SQLite throwaway path

    url = url.strip()
    shown = _redact(url)

    if not declared:
        return (f"${ENV_URL} is set to {shown} and this run has not declared it a test database.\n"
                f"  The suite reads through app.orm_session(), which prefers ${ENV_URL} over the "
                f"throwaway file make_kitchen creates, so every fixture and every write in the run "
                f"would go there instead.\n"
                f"  If that really is a throwaway database, say so: {ENV_DECLARE}=1 beside it.\n"
                f"  If it is not, unset ${ENV_URL} before running the suite.")

    # Declared. The declaration does not make a production URL safe, so the rules below still apply.
    if url.startswith("file:") or ("?" in url and "uri=true" in url.lower()):
        return (f"${ENV_URL} is a file: URI ({shown}).\n"
                f"  A URI carries its own flags, so the path in it is not the file that gets opened "
                f"and the live-identity test below cannot see through it. Give a plain path.")

    try:
        parsed = _parse(url)
    except Unparseable as e:
        return (f"${ENV_URL} is set to {shown}, which SQLAlchemy cannot read ({e}).\n"
                f"  If the engine cannot parse it, nothing here can tell whether it is safe.")

    backend = parsed.get_backend_name()
    name = parsed.database

    if backend == "sqlite":
        if not name:
            return None                                 # in-memory: a throwaway by construction
        if str(name).startswith("file:"):
            return (f"${ENV_URL} wraps a file: URI ({shown}).\n"
                    f"  Give a plain path, so the live-identity test can resolve it.")
        if live_db is None:
            # ⚠️ FAILS CLOSED, THE WAY corpus_guard DOES. Without live's location this cannot tell
            #    a copy from the real file, and guessing in the permissive direction is how the
            #    one file that matters gets opened.
            return (f"${ENV_URL} names a SQLite file ({shown}) and this check was given no live "
                    f"database to compare it against, so it cannot tell a copy from the real one.")
        if _same_file(name, live_db):
            return (f"${ENV_URL} names the LIVE database ({shown}).\n"
                    f"  That is the one file the suite must never open for writing, whatever it is "
                    f"spelled as. 300 recipes and every rating and cook live there.")
        return None

    if backend in ("postgresql", "postgres"):
        # ⚠️ REFUSED BEFORE THE NAME IS EVEN READ. A redirecting keyword means the URL in front of
        #    the "?" describes nothing, so there is no name worth testing. Stated as a list rather
        #    than inferred, so a reader can audit it against libpq.
        redirecting = sorted(k for k in (parsed.query or {}) if k.lower() in _REDIRECTING_QUERY)
        if redirecting:
            return (f"${ENV_URL} carries {', '.join(redirecting)} in its query string ({shown}).\n"
                    f"  The Postgres dialect merges the query OVER the URL's own path, so what gets "
                    f"opened is not what the URL appears to say. Put the database in the path and "
                    f"nothing in the query.")
        try:
            name = _effective_database(parsed)
        except Exception as e:                       # an uninstallable driver, a dialect that errors
            return (f"${ENV_URL} is a Postgres URL this environment cannot resolve ({shown}): "
                    f"{type(e).__name__}: {e}\n"
                    f"  If the dialect cannot say which database it would open, nothing here can "
                    f"tell whether it is safe.")
        if not name:
            return (f"${ENV_URL} names no database ({shown}).\n"
                    f"  A Postgres URL with no database part connects to the server's default, "
                    f"which is not a throwaway anybody made.")
        if not _TEST_NAME.search(name):
            return (f"${ENV_URL} points at the Postgres database {name!r} ({shown}), whose name "
                    f"does not say it is a test database.\n"
                    f"  The suite TRUNCATEs every table in the metadata to reset its fixture, so a "
                    f"wrong name here empties whatever it reaches.\n"
                    f"  Name a throwaway database, for example recipe_test.")
        return None

    return (f"${ENV_URL} is set to {shown}, which the suite does not recognize as SQLite or "
            f"Postgres (it reads as {backend!r}).\n  The suite only knows how to make a throwaway "
            f"of those two, so it cannot tell whether this one is safe.")


def _same_file(path, live):
    """Live by resolved path AND by device/inode, which is how corpus_guard.is_live does it: a path
    string says nothing about which file it opens, and a hard link IS the file under another name.

    ⚠️ A PATH THE FILESYSTEM REFUSES TO LOOK AT IS TREATED AS LIVE. An embedded NUL raised
    ValueError out of lstat, which is a traceback where every other refusal here is a paragraph.
    Unanswerable means refused, not allowed."""
    try:
        p, l = pathlib.Path(path), pathlib.Path(live)
    except (ValueError, TypeError):
        return True
    try:
        if p.resolve() == l.resolve():
            return True
    except (OSError, ValueError):
        return True                                  # unanswerable: refuse
    try:
        a, b = p.stat(), l.stat()
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    except (OSError, ValueError):
        return False


# What counts as NOT a declaration, so RECIPE_APP_TEST_DATABASE=0 does not read as yes.
_FALSEY = {"", "0", "false", "no", "off", "none"}


def declared_in(env):
    """⚠️ bool() ON THE RAW STRING MADE "0" A YES. Any non-empty value declared a test database,
    so =0, =false and =no all turned the guard off while reading as though they turned it on."""
    return str(env.get(ENV_DECLARE, "")).strip().lower() not in _FALSEY


def install(live_db=None, env=None):
    """Check this run's environment and raise Refused when it may not proceed."""
    env = os.environ if env is None else env
    reason = check(env.get(ENV_URL), declared_in(env), live_db=live_db)
    if reason is not None:
        raise Refused("\n\nthe test suite refuses to start:\n  " + reason + "\n")
