"""ingredients.source and ingredients.library_id, the add-on-save provenance columns (migration 030).

Stage 2 adds the two columns and nothing else, so what is worth pinning is the SHAPE and, above all,
HOW THE HAND-AUTHORED ROWS READ. Stage 6's delete path will refuse a seed row and allow a promoted one,
so a mislabeled seed row is a curated entry somebody can delete by accident. That is the test carrying
the weight here. The columns are inert until stage 5 writes them.
"""
from sqlalchemy import insert, select, update

from models import Ingredient


def test_columns_added_with_the_right_shape(kitchen):
    with kitchen.conn() as c:
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(ingredients)")}
    assert "source" in cols and "library_id" in cols

    # source mirrors recipes.source: TEXT, NOT NULL, DEFAULT 'seed' (migration 004's shape).
    assert cols["source"]["type"] == "TEXT"
    assert cols["source"]["notnull"] == 1
    assert cols["source"]["dflt_value"] == "'seed'"

    # library_id is nullable with no default. A hand-authored row has no library origin, and NULL is
    # the honest value for that rather than a sentinel.
    assert cols["library_id"]["type"] == "TEXT"
    assert cols["library_id"]["notnull"] == 0
    assert cols["library_id"]["dflt_value"] is None


def test_source_matches_the_recipes_vocabulary(kitchen):
    """Same column shape as recipes.source, so a reader of one already knows the other."""
    with kitchen.conn() as c:
        ing = {r["name"]: r for r in c.execute("PRAGMA table_info(ingredients)")}["source"]
        rec = {r["name"]: r for r in c.execute("PRAGMA table_info(recipes)")}["source"]
    assert (ing["type"], ing["notnull"], ing["dflt_value"]) == \
           (rec["type"], rec["notnull"], rec["dflt_value"])


def test_hand_authored_rows_read_as_seed_tier(kitchen):
    """⚠️ THE ONE THAT MATTERS. Every row seeded from seed.py's INGREDIENTS must read as seed-tier with
    no library origin, because stage 6's delete path refuses seed and allows promoted. If these ever
    read as 'app', the whole curated library becomes deletable."""
    with kitchen.conn() as c:
        rows = c.execute("SELECT id, source, library_id FROM ingredients").fetchall()
    assert len(rows) == 36
    assert {r["source"] for r in rows} == {"seed"}          # no row reads as promoted
    assert all(r["library_id"] is None for r in rows)       # and none claims a library origin
    assert kitchen.count("ingredients", "source = 'app'") == 0


def test_seed_tier_survives_a_rebuild(kitchen):
    """seed_content upserts the 36 by id and names neither new column, so a rebuild must not flip a
    row's tier or invent a provenance. Pins that stage 2 stays inert through the build path."""
    kitchen.rebuild()
    assert kitchen.count("ingredients", "source = 'seed'") == 36
    assert kitchen.count("ingredients", "library_id IS NOT NULL") == 0


def test_model_round_trips_a_promoted_row(kitchen):
    """What a stage-5 promoted row will look like. The library_id is an Open Food Facts id rather than
    a Q-id on purpose, since 38.4% of library rows carry that shape."""
    with kitchen.session() as s:
        s.execute(insert(Ingredient.__table__).values(
            id="penne", name="penne", source="app", library_id="en:penne"))
        s.commit()
    with kitchen.session() as s:
        row = s.execute(select(Ingredient.id, Ingredient.source, Ingredient.library_id,
                               Ingredient.descr, Ingredient.pairs)
                        .where(Ingredient.id == "penne")).one()
    assert tuple(row) == ("penne", "app", "en:penne", None, None)
    # and it has not disturbed the hand-authored rows
    assert kitchen.count("ingredients", "source = 'seed'") == 36


def test_a_dangling_library_id_is_allowed(kitchen):
    """library_id is NOT a foreign key. Library ids are not durable (commit 460cae5 destroyed 7 of them
    in one rebuild), so the column must accept an id that no longer resolves. The dangle is audit-only,
    and an FK here would either block a library rebuild or cascade the ingredient away with it."""
    with kitchen.session() as s:
        s.execute(insert(Ingredient.__table__).values(
            id="lasagne", name="lasagne", source="app", library_id="en:lasagne"))
        s.commit()
    assert kitchen.count("ingredients", "library_id = 'en:lasagne'") == 1
    assert kitchen.count("library_names") == 0      # nothing to resolve against, and that is fine
    assert kitchen.fk_orphans() == []               # no FK, so no orphan


def test_drawer_payload_gains_the_columns_additively(kitchen):
    """/api/ingredients/<iid> selects the whole row, so the drawer JSON now carries source and
    library_id. Additive only: every key it served before is still there, and the client ignores keys
    it does not read."""
    body = kitchen.client.get("/api/ingredients/garlic").get_json()
    assert body["source"] == "seed" and body["library_id"] is None
    for key in ("id", "name", "descr", "pairs", "season", "regions", "used_in"):
        assert key in body
