"""Build + migration behavior: schema is created from scratch, seed content loads, and a
rebuild is idempotent and keeps referential integrity."""
from fixtures import TEST_RECIPES   # the test-owned recipe set the harness seeds (see fixtures.py)

# Bump this when a migration is added.
EXPECTED_MIGRATIONS = 46


def test_all_migrations_applied(kitchen):
    with kitchen.conn() as c:
        files = [r[0] for r in c.execute("SELECT filename FROM schema_migrations")]
    assert len(files) == EXPECTED_MIGRATIONS
    assert files == sorted(files)                 # applied in filename order
    assert files[0].startswith("001")
    assert files[-1].startswith("046")


def test_seed_rows_get_qty_unit_split(kitchen):
    """The seed load path splits qty -> quantity+unit on build (same rule as the app-row backfill),
    so the rebuilt rows don't lose the split. qty stays as-is; quantity+unit recombine to it."""
    import re
    norm = (lambda s: re.sub(r"\s+", " ", s or "").strip())
    with kitchen.conn() as c:
        rows = c.execute(
            "SELECT qty, quantity, unit FROM recipe_ingredients WHERE is_heading = 0"
        ).fetchall()
    assert rows
    # every non-heading seed row got a non-NULL quantity, and quantity+unit recombines to qty
    assert all(qn is not None for _q, qn, _u in rows)
    assert all(norm(f"{qn} {u or ''}") == norm(q) for q, qn, u in rows)
    shapes = {(q, qn, u) for q, qn, u in rows}
    assert any(u == "tbsp" and qn == "2" for q, qn, u in shapes)               # number + unit
    assert any(u == "cloves" for q, qn, u in shapes)                           # count-noun -> unit
    assert any(q == "2 lb / 1 kg" and qn == "2 lb / 1 kg" and (u or "") == ""  # irreducible kept whole
               for q, qn, u in shapes)


def test_seed_counts(kitchen):
    # Recipes are seeded from the test fixtures (fixtures.TEST_RECIPES), not production seed.py's
    # RECIPES — so assert the fixture count; this stays correct after production RECIPES is emptied.
    assert kitchen.count("recipes", "source='seed'") == len(TEST_RECIPES)
    assert kitchen.count("recipes", "source='app'") == 0
    assert kitchen.count("ingredients") == 36


def test_no_user_data_on_fresh_build(kitchen):
    assert kitchen.count("ratings") == 0
    assert kitchen.count("cook_log") == 0


def test_foreign_key_integrity(kitchen):
    assert kitchen.fk_orphans() == []


def test_build_is_idempotent(kitchen):
    before = (kitchen.count("recipes"), kitchen.count("ingredients"))
    kitchen.rebuild()
    after = (kitchen.count("recipes"), kitchen.count("ingredients"))
    assert before == after
    assert kitchen.fk_orphans() == []


def test_alembic_has_exactly_one_head():
    """⚠️ TWO HEADS MAKE `alembic upgrade head` FAIL, AND ONLY POSTGRES CI FINDS OUT.

    The SQLite path applies migrations/NNN_*.sql in filename order and never reads the Alembic
    graph, so a broken revision chain is invisible to every other test in this file and to the whole
    local suite. The Postgres integration step runs `alembic upgrade head` and stops on
    "Multiple head revisions are present".

    Measured when this was written: two new revisions were each given a down_revision copied from a
    nearby file rather than from the current head, which left three heads and turned the SonarQube
    job red at the Postgres step while every local suite stayed green.

    Pure file parsing, no database and no Alembic import, so it runs everywhere the rest of the
    suite runs."""
    import os, re

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    versions = os.path.join(here, "alembic", "versions")
    down_of = {}
    for name in os.listdir(versions):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(versions, name), encoding="utf-8").read()
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)", text, re.M)
        down = re.search(r"^down_revision(?:\s*:[^=]+)?=\s*(.+)$", text, re.M)
        assert rev, f"{name} has no revision id"
        down_of[rev.group(1)] = (down.group(1).strip().strip("'\"") if down else None)

    parents = {d for d in down_of.values() if d}
    heads = sorted(r for r in down_of if r not in parents)
    assert len(heads) == 1, f"alembic has {len(heads)} heads, expected 1: {heads}"

    roots = sorted(r for r, d in down_of.items() if d in (None, "None"))
    assert len(roots) == 1, f"alembic has {len(roots)} roots, expected 1: {roots}"

    # every down_revision names a revision that exists
    missing = sorted({d for d in down_of.values() if d and d not in down_of and d != "None"})
    assert not missing, f"down_revision points at revisions that do not exist: {missing}"
