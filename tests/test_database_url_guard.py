"""The wall in front of $DATABASE_URL.

⚠️ WHY THIS FILE EXISTS. make_kitchen redirects app.DB / build_db.DB / migrate.DB to a throwaway
file, and app.orm_session() prefers $DATABASE_URL over the file it was handed. So one exported
variable walks past that redirect AND past tests/dbguard.py, which patches sqlite3.connect and never
sees a Postgres connection at all. `pytest` on a machine with $DATABASE_URL pointing at production
would have run the whole suite, fixtures and writes included, against production.

⚠️ EVERY CASE HERE IS A PURE FUNCTION CALL. Nothing in this file sets an environment variable for
the real suite, opens a database or starts a run. urlguard.check takes the URL and the declaration
as arguments for exactly that reason.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import urlguard

REPO = pathlib.Path(__file__).resolve().parent.parent
LIVE = REPO / "recipes.db"
PG_TEST = "postgresql+psycopg://postgres@localhost:5432/recipe_test"


# ---- the unset case, which is every ordinary run ------------------------------------------------

@pytest.mark.parametrize("url", [None, "", "   "])
def test_an_unset_variable_lets_the_run_proceed(url):
    """The SQLite throwaway path. make_kitchen's redirect is the only thing in play."""
    assert urlguard.check(url, declared=False, live_db=LIVE) is None


# ---- setting it is not enough to allow it --------------------------------------------------------

def test_a_url_that_was_not_declared_a_test_database_is_refused():
    """⚠️ THE CASE THE DEFECT CAME FROM. A variable inherited from a shell, a direnv file or a
    parent process carries no declaration, and a run that never meant to use it is exactly the run
    that must not."""
    reason = urlguard.check(PG_TEST, declared=False, live_db=LIVE)
    assert reason is not None
    assert "has not declared it a test database" in reason
    assert urlguard.ENV_DECLARE in reason, "the refusal says how to declare it"
    assert "unset" in reason, "and how to get out of it the other way"


def test_the_same_url_is_allowed_once_the_run_declares_it():
    """The Postgres CI leg sets the variable on purpose, which is why it cannot simply be banned."""
    assert urlguard.check(PG_TEST, declared=True, live_db=LIVE) is None


# ---- and a declaration is not enough either ------------------------------------------------------

def test_the_live_sqlite_path_is_refused_even_when_declared():
    """⚠️ "I MEANT IT" DOES NOT MAKE THE LIVE FILE SAFE. 300 recipes and every rating and cook."""
    reason = urlguard.check(f"sqlite:///{LIVE}", declared=True, live_db=LIVE)
    assert reason is not None and "LIVE database" in reason


def test_the_live_path_is_refused_through_a_relative_spelling(monkeypatch):
    """A path string says nothing about which file it opens, so the test is the resolved path."""
    monkeypatch.chdir(REPO)
    reason = urlguard.check("sqlite:///./recipes.db", declared=True, live_db=LIVE)
    assert reason is not None and "LIVE database" in reason


def test_the_live_path_is_refused_through_a_hard_link(tmp_path):
    """⚠️ THE CASE RESOLVING A PATH CANNOT CATCH. A hard link IS the file under a second name."""
    import os
    hard = tmp_path / "not-live-at-all.db"
    if not LIVE.exists():
        pytest.skip("no live database here, and the resolved-path cases above cover the rule")
    try:
        os.link(LIVE, hard)
    except OSError:
        pytest.skip("no hard links across these filesystems")
    reason = urlguard.check(f"sqlite:///{hard}", declared=True, live_db=LIVE)
    assert reason is not None and "LIVE database" in reason


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://user:secret@prod.example.com:5432/recipes",
    "postgresql://postgres@localhost/production",
    "postgres://u@h/chefs_choice",
])
def test_a_postgres_database_whose_name_does_not_say_test_is_refused(url):
    """The fixture harness TRUNCATEs every table in the metadata to reset itself, so a wrong name
    here empties whatever it reaches."""
    reason = urlguard.check(url, declared=True, live_db=LIVE)
    assert reason is not None and "does not say it is a test database" in reason


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://postgres@localhost:5432/recipe_test",
    "postgresql+psycopg://postgres@localhost:5432/test_recipes",
    "postgresql://postgres@localhost/test",
    "postgresql://postgres@localhost/ci-test",
])
def test_a_postgres_database_that_says_test_is_allowed(url):
    assert urlguard.check(url, declared=True, live_db=LIVE) is None


def test_a_postgres_url_with_no_database_part_is_refused():
    """It would connect to the server's default, which is not a throwaway anybody made."""
    reason = urlguard.check("postgresql+psycopg://postgres@localhost:5432", declared=True,
                            live_db=LIVE)
    assert reason is not None and "names no database" in reason


@pytest.mark.parametrize("url", [
    "file:recipes.db?mode=ro",
    "file:/Users/someone/recipe-app/recipes.db",
    "sqlite:///file:recipes.db?mode=ro&uri=true",
])
def test_a_file_uri_is_refused(url):
    """⚠️ A URI CARRIES ITS OWN FLAGS, so the path inside it is not the file that gets opened and the
    live-identity test cannot see through it. This is the gap corpus_guard.is_live still has, and the
    answer here is to refuse the form rather than to start parsing it."""
    reason = urlguard.check(url, declared=True, live_db=LIVE)
    assert reason is not None and "URI" in reason


def test_a_scheme_the_suite_does_not_know_is_refused():
    """The suite only knows how to make a throwaway SQLite file or Postgres database."""
    reason = urlguard.check("mysql://root@localhost/whatever", declared=True, live_db=LIVE)
    assert reason is not None and "does not recognize" in reason


def test_a_throwaway_sqlite_file_is_allowed(tmp_path):
    """Every rehearsal depends on this. A copy is a different file, whatever it is called."""
    copy = tmp_path / "recipes.db"
    copy.write_bytes(b"not really a database")
    assert urlguard.check(f"sqlite:///{copy}", declared=True, live_db=LIVE) is None


# ---- the refusal is loud, and it does not print the password ------------------------------------

def test_install_raises_rather_than_redirecting_quietly():
    """⚠️ LOUD IS THE POINT. A silent redirect IS the defect, so this cannot be a warning."""
    with pytest.raises(urlguard.Refused) as e:
        urlguard.install(live_db=LIVE, env={"DATABASE_URL": PG_TEST})
    assert "refuses to start" in str(e.value)


def test_install_lets_a_declared_test_database_through():
    urlguard.install(live_db=LIVE, env={"DATABASE_URL": PG_TEST,
                                        "RECIPE_APP_TEST_DATABASE": "1"})


def test_install_lets_an_empty_environment_through():
    urlguard.install(live_db=LIVE, env={})


def test_a_refusal_never_prints_the_password():
    """A refusal is meant to be pasted into a message, and a connection string carries a secret."""
    url = "postgresql+psycopg://admin:sup3rs3cret@prod.example.com:5432/recipes"
    for declared in (False, True):
        reason = urlguard.check(url, declared=declared, live_db=LIVE)
        assert reason is not None
        assert "sup3rs3cret" not in reason, "the password reached the refusal text"
        assert "admin:***@" in reason, "and the shape is still readable"


# ---- the guard is actually installed, and the CI leg still declares itself -----------------------

def test_the_guard_is_installed_from_conftest_at_import():
    """A guard nobody calls is a comment. Installed at import, not in a fixture, so it covers
    collection-time code too."""
    src = (REPO / "tests" / "conftest.py").read_text()
    assert "import urlguard" in src
    assert "urlguard.install(" in src
    assert "corpus_guard.live_db()" in src, "it asks the shared guard where live is"


def _workflow_steps():
    """Each `- name:` step of build.yml as (name, its own lines), by indentation.

    ⚠️ AN env: REGEX SWALLOWED THE WHOLE FILE. The first version matched
    `env:\\n(?:[ \\t]+\\S.*\\n)+`, and `run: |` plus its indented body continues that match, so on
    the real workflow it found ONE 75-line "env block" running from the postgres service to the
    final SONAR_TOKEN. The assertion then only checked that the declaration appeared SOMEWHERE
    below the URL. Mutation-tested: moving the declaration to the Node step kept the test green
    while the Postgres step would refuse at startup. Steps are split on their own indentation
    instead, so a declaration in a different step cannot satisfy this one."""
    lines = (REPO / ".github" / "workflows" / "build.yml").read_text().splitlines()
    steps, cur = [], None
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- name:"):
            indent = len(line) - len(stripped)
            cur = [stripped[len("- name:"):].strip(), indent, []]
            steps.append(cur)
            continue
        if cur is not None:
            if line.strip() and (len(line) - len(line.lstrip())) <= cur[1]:
                cur = None                      # dedented out of the step
            else:
                cur[2].append(line)
    return [(name, "\n".join(body)) for name, _, body in steps]


def test_the_postgres_ci_leg_declares_its_database_so_it_keeps_running():
    """⚠️ THE HALF THAT WOULD HAVE BROKEN CI SILENTLY. An earlier attempt at this guard refused the
    variable outright, which turns the Postgres leg into a second SQLite run while still reporting
    green. The leg sets $DATABASE_URL, so it has to declare it, IN THE SAME STEP."""
    steps = _workflow_steps()
    assert steps, "no steps parsed out of build.yml"
    setters = [(n, b) for n, b in steps if "DATABASE_URL: postgresql" in b]
    assert setters, "no step in build.yml sets a Postgres DATABASE_URL"
    for name, body in setters:
        assert f"{urlguard.ENV_DECLARE}:" in body, (
            f"the step {name!r} sets a Postgres DATABASE_URL without declaring it a test database "
            f"in the SAME step, so the suite will refuse to start and the leg will not run")


def test_no_other_step_carries_the_declaration_on_its_own():
    """A declaration without a URL is harmless but means somebody moved it. Named so the pair
    cannot drift into two different steps and still look right."""
    for name, body in _workflow_steps():
        if f"{urlguard.ENV_DECLARE}:" in body:
            assert "DATABASE_URL: postgresql" in body, \
                f"the step {name!r} declares a test database and sets no DATABASE_URL"


def test_the_ci_postgres_database_name_passes_the_rule():
    """The workflow's own URL has to be one the guard allows, or CI refuses at startup."""
    import re
    wf = (REPO / ".github" / "workflows" / "build.yml").read_text()
    m = re.search(r"DATABASE_URL:\s*(postgresql\S+)", wf)
    assert m, "no Postgres DATABASE_URL in the workflow"
    assert urlguard.check(m.group(1), declared=True, live_db=LIVE) is None, \
        f"CI's own URL {m.group(1)} is refused by the guard"


# ---- the hand-rolled parser, and what it let through ---------------------------------------------

@pytest.mark.parametrize("url", [
    "postgresql+psycopg://admin:xy/test@prod.example.com:5432/recipes",
    "postgresql+psycopg://ab/testing@prod.example.com:5432/recipes",
    "postgresql://user:a/b/test@db.internal:5432/production",
])
def test_a_password_containing_a_slash_cannot_disguise_a_production_database(url):
    """⚠️ TWO PARSERS DISAGREEING. The guard split the URL by hand on the first "/" after the
    scheme, so a password containing a "/" moved the split left and the "database name" became the
    password tail plus the host plus the real name. The old name test matched that on its ^test
    alternative and ALLOWED the connection, which SQLAlchemy then opened against production. A "/"
    is ordinary in a random or base64 password."""
    from sqlalchemy.engine import make_url
    real = make_url(url).database
    reason = urlguard.check(url, declared=True, live_db=LIVE)
    assert reason is not None, f"it was allowed, and SQLAlchemy would open {real!r}"
    assert real in reason, \
        f"the refusal must name what SQLAlchemy actually opens ({real!r}), not what a second parser guessed"


def test_the_guard_reads_the_url_with_the_same_parser_that_opens_it():
    """One rule, one function. A second URL parser beside the real one is how this went wrong."""
    src = (REPO / "tests" / "urlguard.py").read_text()
    assert "make_url" in src, "the guard parses the URL itself again"
    assert "def _pg_database" not in src and "def _sqlite_path" not in src, \
        "a hand-rolled URL splitter is back"


@pytest.mark.parametrize("name", ["latest", "greatest", "contest", "protest", "attest",
                                  "testing", "testimonials", "recipes_latest", "LATEST"])
def test_a_production_name_that_merely_contains_test_is_refused(name):
    """⚠️ THE NAME RULE HAD A BARE PREFIX AND SUFFIX ALTERNATIVE. ^test|test$ matched every name
    here, so postgresql://postgres@db.prod.internal/latest was allowed. The whole-word form matches
    every name the suite blesses, so the alternatives cost nothing to delete."""
    reason = urlguard.check(f"postgresql+psycopg://postgres@db.prod.internal:5432/{name}",
                            declared=True, live_db=LIVE)
    assert reason is not None, f"the database {name!r} was accepted as a test database"


def test_an_in_memory_sqlite_url_is_allowed():
    """A throwaway by construction, and the only database that cannot be the live file."""
    assert urlguard.check("sqlite://", declared=True, live_db=LIVE) is None


def test_a_url_sqlalchemy_cannot_read_is_refused_rather_than_guessed_at():
    reason = urlguard.check("::::not a url at all", declared=True, live_db=LIVE)
    assert reason is not None and "cannot read" in reason
