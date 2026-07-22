"""Build + migration behavior: schema is created from scratch, seed content loads, and a
rebuild is idempotent and keeps referential integrity."""
from fixtures import TEST_RECIPES   # the test-owned recipe set the harness seeds (see fixtures.py)

# Bump this when a migration is added.
EXPECTED_MIGRATIONS = 15


def test_all_migrations_applied(kitchen):
    with kitchen.conn() as c:
        files = [r[0] for r in c.execute("SELECT filename FROM schema_migrations")]
    assert len(files) == EXPECTED_MIGRATIONS
    assert files == sorted(files)                 # applied in filename order
    assert files[0].startswith("001")
    assert files[-1].startswith("015")


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
    assert kitchen.count("people") == 2


def test_no_user_data_on_fresh_build(kitchen):
    assert kitchen.count("ratings") == 0
    assert kitchen.count("cook_log") == 0
    assert kitchen.count("recipe_line_changes") == 0
    assert kitchen.count("recipe_additions") == 0


def test_foreign_key_integrity(kitchen):
    assert kitchen.fk_orphans() == []


def test_build_is_idempotent(kitchen):
    before = (kitchen.count("recipes"), kitchen.count("ingredients"), kitchen.count("people"))
    kitchen.rebuild()
    after = (kitchen.count("recipes"), kitchen.count("ingredients"), kitchen.count("people"))
    assert before == after
    assert kitchen.fk_orphans() == []
