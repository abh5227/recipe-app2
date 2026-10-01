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
dbguard.install(Path(__file__).resolve().parent.parent / "recipes.db")


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


@pytest.fixture(autouse=True)
def _no_live_database(request):
    """Every test runs with the live database shut off unless it asks for it by name, and then only
    read-only. This is the wall behind make_kitchen's DB redirect."""
    dbguard.set_read_only_allowed(
        request.node.get_closest_marker("live_catalog") is not None)
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
