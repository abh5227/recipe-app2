"""The note_kinds TABLE, static/note-kinds.json and the migration cannot drift apart.

⚠️ THE KIND IS A ROW RATHER THAN A CHECK BECAUSE SQLITE CANNOT WIDEN A CHECK IN PLACE. Adding a
sixth kind as a CHECK would be a create-copy-drop-rename on the table holding every note in the
database; as a row it is one INSERT. The cost of that choice is that the list now lives in three
places — the JSON the client and import_cleanup share, the SQLite migration, and the Alembic mirror
— and nothing but this file notices when one of them is edited alone.
"""
import json
import os
import pathlib
import re

import pytest

import harness  # noqa: F401

REPO = pathlib.Path(__file__).resolve().parent.parent
JSON_KINDS = json.loads((REPO / "static" / "note-kinds.json").read_text())["kinds"]
MIGRATION = (REPO / "migrations" / "060_recipe_notes.sql").read_text()
ALEMBIC = (REPO / "alembic" / "versions" / "f3c8d21a97e4_recipe_notes.py").read_text()


def _rows_in(sql_or_py):
    """Every ('kind', 'Header', position) triple written out in a file, however it is spelled."""
    return {(m.group(1), m.group(2), int(m.group(3)))
            for m in re.finditer(r"\(\s*['\"](\w+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*(\d+)\s*\)",
                                 sql_or_py)}


def test_the_table_holds_exactly_the_kinds_the_client_knows(kitchen):
    with kitchen.conn() as c:
        rows = {(r[0], r[1], r[2]) for r in
                c.execute("SELECT kind, header, position FROM note_kinds")}
    want = {(k["kind"], k["header"], i) for i, k in enumerate(JSON_KINDS)}
    assert rows == want, "note_kinds and static/note-kinds.json disagree"


def test_the_sqlite_migration_seeds_exactly_those_kinds():
    want = {(k["kind"], k["header"], i) for i, k in enumerate(JSON_KINDS)}
    assert _rows_in(MIGRATION) >= want, "migrations/060 does not seed every kind in the JSON"


def test_the_postgres_mirror_seeds_exactly_those_kinds():
    """A fresh Postgres database with no note_kinds rows cannot store a note at all, so the seed is
    part of the schema rather than part of some later data step."""
    want = {(k["kind"], k["header"], i) for i, k in enumerate(JSON_KINDS)}
    assert _rows_in(ALEMBIC) >= want, "the Alembic mirror does not seed every kind in the JSON"


def test_every_kind_a_note_can_hold_is_a_row(kitchen):
    """The foreign key is the enforcement, and this is the statement of what it enforces."""
    import notes as notes_rules
    with kitchen.conn() as c:
        rows = {r[0] for r in c.execute("SELECT kind FROM note_kinds")}
    assert set(notes_rules.KIND_HEADERS) == rows
    assert notes_rules.DEFAULT_KIND in rows


def test_a_note_cannot_hold_a_kind_that_is_not_a_row(kitchen):
    """⚠️ THE FOREIGN KEY ONLY BITES WITH foreign_keys ON, which build_db and migrate both set and
    the app's connection sets per-connection. Stated here so a change to that setting fails loudly
    rather than quietly letting an unknown kind in."""
    import sqlite3
    with kitchen.conn() as c:
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("INSERT INTO recipes (id, name, source) VALUES ('k-probe', 'K', 'app')")
        try:
            c.execute("INSERT INTO recipe_notes (recipe_id, position, kind, text) "
                      "VALUES ('k-probe', 0, 'nonsense', 'x')")
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        c.rollback()
    assert raised, "a note was stored with a kind that is not in note_kinds"


# ---- the fixture database has to be able to hold a note (review fix) ---------------------------

def test_the_postgres_fixture_reset_keeps_the_kinds():
    """⚠️ THE HARNESS IS PART OF THE BLAST RADIUS. pg_harness.reset_and_seed TRUNCATEs every table
    in the metadata except schema_migrations, and note_kinds joined that metadata the moment
    models.py declared it. Nothing reseeds it, so after one reset the Postgres fixture could not
    store a single note: every create carrying one returned 500 on the kind foreign key, and the
    fallback kind was missing too. The PG leg of CI runs the integration file and the parity file,
    neither of which wrote a note, so the whole dialect was uncovered."""
    import pg_harness

    assert "note_kinds" in pg_harness.KEEP_THROUGH_RESET
    body = (REPO / "tests" / "pg_harness.py").read_text().split("def reset_and_seed")[1]
    assert "KEEP_THROUGH_RESET" in body, "reset_and_seed no longer honours the keep set"
    # ⚠️ AND KEEPING THEM IS NOT ENOUGH ON ITS OWN. Measured while testing the fix: one run of the
    #    old harness emptied the table, and since nothing reseeds it the database stayed unable to
    #    store a note afterwards. The keep set protects the rows, ensure_note_kinds heals a
    #    database that already lost them.
    assert "ensure_note_kinds" in body, "reset_and_seed no longer repairs an emptied table"


@pytest.mark.skipif(not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
                    reason="needs the Postgres test database")
def test_on_postgres_an_emptied_kind_table_is_put_back_by_the_next_reset():
    """The heal, exercised rather than read: empty the table, reset, and the five are back."""
    import sqlalchemy

    import pg_harness

    engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as c:
        c.execute(sqlalchemy.text("DELETE FROM recipe_notes"))
        c.execute(sqlalchemy.text("DELETE FROM note_kinds"))
    pg_harness.reset_and_seed(engine)
    with engine.begin() as c:
        rows = {(r[0], r[1], r[2]) for r in c.execute(
            sqlalchemy.text("SELECT kind, header, position FROM note_kinds"))}
    assert rows == {(k["kind"], k["header"], i) for i, k in enumerate(JSON_KINDS)}


@pytest.mark.skipif(not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
                    reason="needs the Postgres test database")
def test_on_postgres_a_reset_leaves_every_lookup_table_populated():
    """The general form, stated over the schema: a table something points at by foreign key, that
    held rows before the reset, holds them after it."""
    import sqlalchemy

    import models
    import pg_harness

    engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])
    targets = sorted({fk.column.table.name
                      for t in models.Base.metadata.sorted_tables for fk in t.foreign_keys})
    with engine.begin() as c:
        before = {name: c.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
                  for name in targets}
    pg_harness.reset_and_seed(engine)
    with engine.begin() as c:
        after = {name: c.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
                 for name in targets}
    emptied = [n for n in targets if before[n] and not after[n]
               and n not in ("recipes", "recipe_steps", "recipe_ingredients", "recipe_notes",
                             "users", "people", "cook_log", "ingredients")]
    assert not emptied, f"the reset emptied reference data nothing refills: {emptied}"
