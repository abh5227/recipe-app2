"""Shared test helper.

Builds a brand-new database (migrations + seed.py) in a temp directory and returns a
Flask test client pointed at it. Kept separate from conftest.py and free of any pytest
import, so the project can also exercise these helpers without pytest installed.
"""
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for _p in (str(REPO), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fixtures import TEST_RECIPES   # test-owned recipe set (fixtures.py) — seeded instead of seed.py RECIPES


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


# auth-3b: the routes are login-gated, so the harness logs a reserved test user into its client by
# default — otherwise every route test would 401. The email is reserved (no real test uses it, so it
# can't collide on users.email UNIQUE). is_admin=0: the mutating/read routes only need a logged-in user;
# the admin-only /api/invites tests mint their own admin (create_admin). Auth-state tests get a
# logged-OUT client via app.app.test_client() directly (a fresh cookie jar) or make_kitchen(..., login=False).
HARNESS_USER_EMAIL = "harness@test.local"


def ensure_test_user(email=HARNESS_USER_EMAIL, is_admin=0):
    """Create the reserved harness user (idempotent) in whatever DB app.orm_session() currently points
    at — SQLite temp DB or Postgres — and return its id. Uses the app's own ORM/hash so it's
    dialect-agnostic and honors the harness DB redirect (app.DB is rebound just above by make_kitchen)."""
    import app
    from sqlalchemy import select
    from models import User
    from auth import hash_password
    with app.orm_session() as s:
        uid = s.execute(select(User.id).where(User.email == email)).scalar_one_or_none()
        if uid is None:
            u = User(email=email, password_hash=hash_password("harness-pw"),
                     is_admin=is_admin, created_at=app.now_utc())
            s.add(u)
            s.commit()
            uid = u.id
        return uid


def login_test_client(client, user_id):
    """Authenticate a Flask test client as `user_id` using Flask-Login's session key directly (no login
    route / password round-trip needed). Signing the cookie needs SECRET_KEY — present in BOTH test
    paths: SQLite tests use the dev fallback (DATABASE_URL unset), PG tests get it from the env
    (build.yml's PG step / a local export, required anyway by the fail-closed guard)."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def make_kitchen(tmp_path, login=True):
    """Point the app / build_db / migrate modules at a new temp DB, build it, and return
    a Kitchen. Each call uses its own database file, so tests stay isolated.

    login=True (default, auth-3b) creates + logs in the reserved harness user, so the client is
    authenticated and the ~300 route tests pass un-edited against the login-gated routes. Pass
    login=False for a logged-out client (e.g. to assert unauthenticated 401 behavior)."""
    db = Path(tmp_path) / "test.db"
    import migrate
    import build_db
    import app

    migrate.DB = db
    migrate.MIGRATIONS_DIR = REPO / "migrations"
    build_db.DB = db
    app.DB = db

    # Seed the test DB from the test-owned fixtures, NOT production seed.py's RECIPES: override the
    # module global that build_db.build() (validate + seed_content) reads — the same rebinding pattern
    # as build_db.DB above. This is what lets production seed.py RECIPES be emptied later without
    # breaking the suite. INGREDIENTS/PEOPLE still come from seed.py (they aren't being emptied).
    build_db.RECIPES = TEST_RECIPES

    build_db.build()                       # apply migrations + load seed content (from TEST_RECIPES)
    client = app.app.test_client()
    if login:
        login_test_client(client, ensure_test_user())   # authenticate against the just-built DB
    return Kitchen(db, client)


def write_paprika_archive(path, recipes, malformed=()):
    """Write a `.paprikarecipes` fixture archive for the reader/runner tests.

    `recipes` is a list of raw Paprika-shape dicts, written as gzip-compressed JSON
    `NNN.paprikarecipe` entries in stable numeric-name order (so slug minting is
    deterministic). `malformed` is a list of entry NAMES (each must end in
    `.paprikarecipe` so iter_entries yields it) written as plain non-gzip bytes, which
    iter_entries must report as an error rather than crash on. Returns `path`."""
    import gzip
    import json
    import zipfile

    path = Path(path)
    with zipfile.ZipFile(path, "w") as zf:
        for i, rec in enumerate(recipes):
            zf.writestr("%03d.paprikarecipe" % i,
                        gzip.compress(json.dumps(rec).encode("utf-8")))
        for name in malformed:
            zf.writestr(name, b"not-gzip-not-json")   # decompress -> raises -> reported as err
    return path
