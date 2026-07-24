"""pytest fixtures for the test suite.

The `kitchen` fixture gives each test a freshly built throwaway database and a client,
so tests never touch the real recipes.db and don't interfere with each other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # make harness importable

import pytest
from harness import make_kitchen


@pytest.fixture
def kitchen(tmp_path):
    return make_kitchen(tmp_path)


@pytest.fixture
def kitchen_logged_out(tmp_path):
    # auth-3b opt-out: a Kitchen whose client is NOT authenticated, for asserting the login gate blocks.
    return make_kitchen(tmp_path, login=False)
