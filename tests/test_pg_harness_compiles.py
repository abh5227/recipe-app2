"""The Postgres fixture builder is exercised on a run with no Postgres.

⚠️ THE WHOLE PG LEG IS SKIPPED LOCALLY, SO ITS HARNESS HAD NO COVERAGE AT ALL. tests/
test_pg_integration.py and tests/test_schema_parity.py are 65 skipped without $DATABASE_URL, and
tests/pg_harness.py is only imported from them. Migration 063 dropped recipes.notes, Recipe.__table__
stopped carrying the column, and `insert(Recipe.__table__).values(notes=…)` then failed at COMPILE
time with "Unconsumed column names: notes" -- before any SQL is sent, so a real server would not have
saved it either. Every test using the pg fixture errored, on a commit whose SQLite suite was 3,037
green. Found by an independent review, not by the suite.

CLAUDE.md states this rule twice over: blast radius includes the fixture harness, and "green locally
because the tests aren't exercising what CI exercises" is the standing trap. A compile is dialect
independent, so SQLite can answer the question Postgres would have asked.

⚠️ AND IT RUNS seed_all RATHER THAN READING IT. A statement that compiles is the claim, and only
executing it proves the compile happened.
"""
import pathlib
import sys

import pytest
import sqlalchemy as sa

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import pg_harness                                                               # noqa: E402
from models import Base                                                         # noqa: E402


@pytest.fixture
def mirror():
    """The model metadata on an in-memory SQLite database. Not the PG schema, deliberately: what is
    under test is whether the harness's INSERTs agree with models.py, which is where it broke."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        yield conn


def test_seed_all_still_agrees_with_the_model(mirror):
    pg_harness.seed_all(mirror)
    counts = {t: mirror.execute(sa.text(f'SELECT count(*) FROM "{t}"')).scalar()
              for t in ("recipes", "recipe_ingredients", "recipe_steps", "ingredient_weights")}
    # ⚠️ ANTI-VACUITY. A seed_all that silently inserted nothing would compile perfectly.
    assert counts["recipes"] == 5, counts
    assert counts["recipe_ingredients"] > 20 and counts["recipe_steps"] > 10, counts
    assert counts["ingredient_weights"] > 100, counts


def test_a_column_the_model_does_not_have_is_refused_at_compile_time(mirror):
    """⚠️ THE PROOF THAT THE TEST ABOVE CAN FAIL. Without this, "seed_all ran" says nothing about
    whether an unknown column would have been caught, and that is the exact defect."""
    from models import Recipe
    with pytest.raises(sa.exc.CompileError) as e:
        mirror.execute(sa.insert(Recipe.__table__).values(id="x", name="X", notes="gone"))
    assert "notes" in str(e.value)


def test_ensure_note_kinds_puts_the_reference_rows_back(mirror):
    """The other thing this harness owns that nothing local exercised. A truncate empties
    note_kinds, recipe_notes.kind is a foreign key to it, and nothing else reseeds it."""
    mirror.execute(sa.text("DELETE FROM note_kinds"))
    pg_harness.ensure_note_kinds(mirror)
    assert mirror.execute(sa.text("SELECT count(*) FROM note_kinds")).scalar() == 5
