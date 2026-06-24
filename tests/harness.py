"""Shared test helper.

Builds a brand-new database (migrations + seed.py) in a temp directory and returns a
Flask test client pointed at it. Kept separate from conftest.py and free of any pytest
import, so the project can also exercise these helpers without pytest installed.
"""
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class Kitchen:
    """A freshly built test database plus a client to talk to it."""

    def __init__(self, db_path, client):
        self.db = db_path
        self.client = client

    def conn(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def count(self, table, where=""):
        sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        with self.conn() as c:
            return c.execute(sql).fetchone()[0]

    def first_line_pos(self, recipe_id):
        """Position of the first real (non-heading) ingredient line of a recipe."""
        with self.conn() as c:
            return c.execute(
                "SELECT position FROM recipe_ingredients "
                "WHERE recipe_id = ? AND is_heading = 0 ORDER BY position LIMIT 1",
                (recipe_id,),
            ).fetchone()[0]

    def fk_orphans(self):
        with self.conn() as c:
            return c.execute("PRAGMA foreign_key_check").fetchall()

    def rebuild(self):
        import build_db
        build_db.build()


def make_kitchen(tmp_path):
    """Point the app / build_db / migrate modules at a new temp DB, build it, and return
    a Kitchen. Each call uses its own database file, so tests stay isolated."""
    db = Path(tmp_path) / "test.db"
    import migrate
    import build_db
    import app

    migrate.DB = db
    migrate.MIGRATIONS_DIR = REPO / "migrations"
    build_db.DB = db
    app.DB = db

    build_db.build()                       # apply migrations + load seed content
    return Kitchen(db, app.app.test_client())
