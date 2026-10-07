"""pytest fixtures for the test suite.

The `kitchen` fixture gives each test a freshly built throwaway database and a client,
so tests never touch the real recipes.db and don't interfere with each other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # make harness importable

import pytest
import dbguard
import netguard
from harness import make_kitchen

# Installed at IMPORT, not in a fixture, so the guard covers collection-time code too. See
# tests/netguard.py for what it blocks, what it deliberately does not, and the defect that caused it.
netguard.install()
# ⚠️ AND THE SAME WALL IN FRONT OF THE LIVE DATABASE. The harness redirects app.DB / build_db.DB /
# migrate.DB, and a test that names a path itself reaches straight past that redirect — one did. See
# tests/dbguard.py. Installed at import for the same reason netguard is.
# ⚠️ AND IT ASKS THE SHARED GUARD WHERE LIVE IS, NOT ITS OWN PARENT DIRECTORY. `parent.parent` is
# THIS checkout, so a suite run from a worktree guarded that worktree's absent recipes.db and left
# the real one open. corpus_guard.live_db() is the one absolute answer from any checkout, and a
# location it cannot determine raises, which is louder than guarding the wrong file.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import corpus_guard                                                            # noqa: E402

dbguard.install(corpus_guard.live_db())
# ⚠️ AND THE WALL dbguard CANNOT BE. dbguard patches sqlite3.connect, and $DATABASE_URL does not go
# through sqlite3 at all: app.orm_session() hands it to SQLAlchemy, which opens Postgres. So one
# exported variable walks past make_kitchen's redirect AND past the patch above. urlguard checks the
# variable itself, at import, and refuses the run rather than redirecting it quietly. The Postgres CI
# leg sets $DATABASE_URL on purpose and declares it with $RECIPE_APP_TEST_DATABASE=1.
import urlguard                                                                # noqa: E402

urlguard.install(corpus_guard.live_db())


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "network: this test genuinely needs the open internet. Nothing in the suite uses it. "
        "Adding it is a visible, reviewable choice — see tests/netguard.py.",
    )
    config.addinivalue_line(
        "markers",
        "live_catalog: this test reads the REAL library catalog in recipes.db, read-only, and skips "
        "when there is none. A fixture database has the tables and no rows, so a check written only "
        "against one is vacuous. Adding it is a visible, reviewable choice — see tests/dbguard.py.",
    )
    config.addinivalue_line(
        "markers",
        "live_schema: this test reads the live database's SCHEMA, read-only, and skips when there "
        "is none. Separate from live_catalog on purpose: that marker is about the catalog's ROWS, "
        "this one is about whether live's schema still matches what migrations build. Same single "
        "allowance, a mode=ro URI and nothing else — see tests/dbguard.py.",
    )


@pytest.fixture(autouse=True)
def _no_live_database(request):
    """Every test runs with the live database shut off unless it asks for it by name, and then only
    read-only. This is the wall behind make_kitchen's DB redirect."""
    dbguard.set_read_only_allowed(
        request.node.get_closest_marker("live_catalog") is not None
        or request.node.get_closest_marker("live_schema") is not None)
    yield
    dbguard.set_read_only_allowed(False)


@pytest.fixture(autouse=True)
def _no_outbound_network(request):
    """Every test runs with the network shut off unless it asks for it by name.

    This is the wall behind the per-test transport stubs. A stub protects the door it is nailed to,
    and url_image.fetch_image proved that a second door can be added without anyone noticing: 10
    commit tests were retrieving real photos from real recipe sites while their own docstring said
    NO NETWORK, and the suite stayed green.
    """
    netguard.set_allowed(request.node.get_closest_marker("network") is not None)
    yield
    netguard.set_allowed(False)


@pytest.fixture(autouse=True)
def _no_repo_reports(tmp_path, monkeypatch):
    """Every test writes its reports into its own temp folder, never into the repo's.

    ⚠️ THE SUITE WAS REWRITING THE WORKING TREE ON EVERY RUN. Measured 2026-10-07: one plain
    `pytest` replaced six files in `reports/` with fixture output under the real names, and
    `total-vs-waits.csv` ended up listing two recipes called `nocook` and `unclear` where live's
    survey had put a real recipe id. A person reading that file to see what the survey found was
    reading test fixtures.

    ⚠️ AND ONE TEST ALREADY SET `$RECIPE_APP_REPORTS` BY HAND, WHICH NOTHING READ. That is the
    worse half: a redirect that is not wired reads as proof the test cannot reach the working tree,
    while it rewrites a file in it. `corpus_guard.report_target` reads both variables now, so the
    wall is one fixture rather than an argument every caller has to remember, the same way
    `_no_live_database` sits behind `make_kitchen`'s redirect rather than beside it.

    `RECIPE_APP_REPAIRS` is here too. `--record` already refuses to overwrite a non-empty record,
    so nothing committed was ever at risk, but a test may still CREATE a file there and that is the
    folder holding the record of what was done to the data.
    """
    monkeypatch.setenv("RECIPE_APP_REPORTS", str(tmp_path / "reports"))
    monkeypatch.setenv("RECIPE_APP_REPAIRS", str(tmp_path / "data-repairs"))


@pytest.fixture
def kitchen(tmp_path):
    return make_kitchen(tmp_path)


@pytest.fixture(autouse=True)
def no_image_network(monkeypatch):
    """⚠️ THE HERO FETCH REACHES THE NETWORK AND THE SUITE MUST NOT.

    url_fetch.fetch is stubbed per test against U0's committed fixtures. url_image.fetch_image is a
    SEPARATE transport path, which is the entire point of U3, so stubbing one does not stub the
    other. Without this, /api/import/commit retrieved a real photo from a real recipe site on every
    test that used it: 10 of them did, measured with a socket guard, while the file's own "NO
    NETWORK" docstring said otherwise.

    The default is a refusal, which is the graceful path the import already has to handle, so a test
    that does not care about pictures gets a hero-less recipe and asserts exactly what it always
    asserted. A test that DOES care injects its own fetcher or re-patches this.
    """
    import url_fetch
    import url_image
    monkeypatch.setattr(url_image, "fetch_image", lambda url, **kw: url_fetch.Refused(
        "NETWORK_ERROR", "the network is disabled in tests", url))


@pytest.fixture
def kitchen_logged_out(tmp_path):
    # auth-3b opt-out: a Kitchen whose client is NOT authenticated, for asserting the login gate blocks.
    return make_kitchen(tmp_path, login=False)
