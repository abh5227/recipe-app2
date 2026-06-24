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
