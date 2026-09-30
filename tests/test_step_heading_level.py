"""recipe_steps.heading_level — the column migration 059 adds, and the default that makes every
existing row correct without a backfill.

⚠️ TWO LEVELS BECAUSE THE HEADINGS COME FROM TWO PLACES. 116 were recognized by the importer as
section titles and stand on their own. 104 are lead-in labels lifted out of the front of one step,
46 joined by a colon and 58 by a dash. A lifted label names ONE step. A section title opens a group.
At one weight, a recipe with twelve one-step labels reads as twelve sections.
"""
import pytest


@pytest.fixture
def rid(kitchen):
    return kitchen.client.post("/api/recipes", json={
        "name": "Levels", "ingredients": [], "steps": ["placeholder"]}).get_json()["id"]


def test_the_column_exists_and_defaults_to_a_section(kitchen, rid):
    """⚠️ NOT NULL DEFAULT 1 IS WHY 059 SHIPS WITHOUT A BACKFILL. The rows that existed when the
    column arrived are the importer's 116 section titles plus 2,286 ordinary steps, and 1 is the
    right answer for every one of them."""
    with kitchen.conn() as c:
        cols = {r[1]: r for r in c.execute("PRAGMA table_info(recipe_steps)")}
        assert "heading_level" in cols, "migration 059 did not add heading_level"
        _, _, ctype, notnull, default, _ = cols["heading_level"]
        assert ctype == "INTEGER"
        assert notnull == 1, "a step with no level is not a state the readers handle"
        assert default == "1", "the default is a section heading"
        levels = {r[0] for r in c.execute("SELECT DISTINCT heading_level FROM recipe_steps")}
        assert levels <= {1}, "no row starts life as a subheading"


def test_a_subheading_stores_its_level(kitchen, rid):
    with kitchen.conn() as c:
        c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, text, heading_level) "
                  "VALUES (?,?,1,?,2)", (rid, 1, "Deseed"))
        c.commit()
        got = c.execute("SELECT heading_level FROM recipe_steps WHERE text='Deseed'").fetchone()[0]
    assert got == 2


def test_no_check_refuses_a_level_the_writer_would_narrow(kitchen, rid):
    """⚠️ THERE IS NO CHECK, AND THAT IS 057'S DECISION REPEATED. SQLite cannot add one without
    recreating the table, and app._step_parts narrows an incoming level to 1 or 2 before it is
    written. This test states the floor honestly rather than pretending the table enforces it."""
    with kitchen.conn() as c:
        c.execute("INSERT INTO recipe_steps (recipe_id, position, is_heading, text, heading_level) "
                  "VALUES (?,?,1,?,7)", (rid, 1, "Out of range"))
        c.commit()
        assert c.execute("SELECT heading_level FROM recipe_steps WHERE text='Out of range'"
                         ).fetchone()[0] == 7
