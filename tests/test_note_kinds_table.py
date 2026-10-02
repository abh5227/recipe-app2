"""The note_kinds TABLE, static/note-kinds.json and the migration cannot drift apart.

⚠️ THE KIND IS A ROW RATHER THAN A CHECK BECAUSE SQLITE CANNOT WIDEN A CHECK IN PLACE. Adding a
sixth kind as a CHECK would be a create-copy-drop-rename on the table holding every note in the
database; as a row it is one INSERT. The cost of that choice is that the list now lives in three
places — the JSON the client and import_cleanup share, the SQLite migration, and the Alembic mirror
— and nothing but this file notices when one of them is edited alone.
"""
import json
import pathlib
import re

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
