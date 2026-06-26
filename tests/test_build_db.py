"""Build + migration behavior: schema is created from scratch, seed content loads, and a
rebuild is idempotent and keeps referential integrity."""

# Bump this when a migration is added.
EXPECTED_MIGRATIONS = 10


def test_all_migrations_applied(kitchen):
    with kitchen.conn() as c:
        files = [r[0] for r in c.execute("SELECT filename FROM schema_migrations")]
    assert len(files) == EXPECTED_MIGRATIONS
    assert files == sorted(files)                 # applied in filename order
    assert files[0].startswith("001")
    assert files[-1].startswith("010")


def test_seed_counts(kitchen):
    assert kitchen.count("recipes", "source='seed'") == 5
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
