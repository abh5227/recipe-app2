"""library_names, the add-on-save lookup table (migration 029).

Stage 1 adds the table and the model and nothing else, so what is worth pinning is the SHAPE and the
round trip. The shape matters because the missing third column is a decision, not an oversight: a
`slug` column plus its index was measured (1,044 KB against 624 KB on the 10,527-row library) and
dropped along with step-link promotion, so a later session re-adding it should have to change a test
that says why. The table is also deliberately EMPTY after a build, since the loader arrives in a later
stage and reads a gitignored server-side file that CI will not have.
"""
from sqlalchemy import insert, select

from models import LibraryName


def test_table_shape(kitchen):
    """Two columns, library_id as the primary key, canonical NOT NULL. library_id's notnull is 0
    because SQLite's TEXT PRIMARY KEY DDL is implicitly nullable (the PRAGMA notnull=0 case models.py's
    header note describes), so the primary key is asserted through pk rather than notnull."""
    with kitchen.conn() as c:
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(library_names)")}
    assert list(cols) == ["library_id", "canonical"]        # two columns, and no slug
    assert cols["library_id"]["type"] == "TEXT"
    assert cols["library_id"]["pk"] == 1
    assert cols["canonical"]["type"] == "TEXT"
    assert cols["canonical"]["notnull"] == 1
    assert cols["canonical"]["pk"] == 0


def test_no_index_beyond_the_primary_key(kitchen):
    """The slug index went with step-link promotion. SQLite still auto-creates an index for a non-
    INTEGER primary key (origin 'pk'), so what this asserts is that nothing was added by CREATE INDEX
    (origin 'c')."""
    with kitchen.conn() as c:
        created = [r["name"] for r in c.execute("PRAGMA index_list(library_names)")
                   if r["origin"] == "c"]
    assert created == []


def test_empty_after_a_build(kitchen):
    """No loader yet, and the one that arrives later reads a gitignored file CI will not have. Empty is
    the expected state, and it is what keeps the later save gate's create branch dormant."""
    assert kitchen.count("library_names") == 0


def test_model_round_trips(kitchen):
    """Both id shapes the library actually uses: a Wikidata Q-id (61.1% of rows) and an Open Food Facts
    id (38.4%). One Text primary key has to hold either."""
    with kitchen.session() as s:
        s.execute(insert(LibraryName.__table__).values(library_id="Q1063736", canonical="penne"))
        s.execute(insert(LibraryName.__table__).values(library_id="en:egg-pasta", canonical="egg pasta"))
        s.commit()
    with kitchen.session() as s:
        rows = s.execute(
            select(LibraryName.library_id, LibraryName.canonical).order_by(LibraryName.library_id)
        ).all()
    assert [tuple(r) for r in rows] == [("Q1063736", "penne"), ("en:egg-pasta", "egg pasta")]
    assert kitchen.count("library_names") == 2


def test_rebuild_leaves_the_table_alone(kitchen):
    """build_db.py has no loader for this table yet, so a rebuild must neither fill it nor clear what is
    in it. Pins that stage 1 stays inert through the build path it will later hook into."""
    with kitchen.session() as s:
        s.execute(insert(LibraryName.__table__).values(library_id="Q178", canonical="pasta"))
        s.commit()
    kitchen.rebuild()
    assert kitchen.count("library_names") == 1
