"""ingredients.concept and ingredients.owner, the Option D identity split (migration 031).

The Panel's root. `ingredients.id` was doing two jobs, saying which row this is and which concept it
is, and the model needs a personal and a shared row for one concept to coexist. This file pins the
four behaviors that split has to produce, because the constraint that produces them is subtle: one
unique index is not enough, and the reason is a NULL-comparison rule that is easy to get wrong twice.

Nothing reads either column yet. Stage 1 is shape only.
"""
import sqlite3

import pytest


# ---- the shape and the backfill --------------------------------------------------------------------

def test_columns_added_with_the_right_shape(kitchen):
    with kitchen.conn() as c:
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(ingredients)")}
    assert "concept" in cols and "owner" in cols

    assert cols["concept"]["type"] == "TEXT"
    assert cols["concept"]["notnull"] == 1
    assert cols["concept"]["dflt_value"] == "''"      # the SQLite artifact, see the migration

    assert cols["owner"]["type"] == "INTEGER"
    assert cols["owner"]["notnull"] == 0               # NULL is the shared marker, not a missing value


def test_owner_is_a_foreign_key_to_users_matching_recipes_owner(kitchen):
    """recipes.owner is `INTEGER REFERENCES users(id)` with no ondelete. Mirrored, not invented."""
    with kitchen.conn() as c:
        ing = [r for r in c.execute("PRAGMA foreign_key_list(ingredients)") if r["from"] == "owner"]
        rec = [r for r in c.execute("PRAGMA foreign_key_list(recipes)") if r["from"] == "owner"]
    assert len(ing) == 1 and ing[0]["table"] == "users" and ing[0]["to"] == "id"
    assert ing[0]["on_delete"] == rec[0]["on_delete"]          # same policy as the precedent


def test_every_existing_row_is_backfilled_to_concept_equals_id_and_shared(kitchen):
    """All 36 are shared today and their ids are already name slugs, so concept = id, owner = NULL."""
    with kitchen.conn() as c:
        rows = c.execute("SELECT id, concept, owner FROM ingredients").fetchall()
    assert len(rows) == 36
    assert all(r["concept"] == r["id"] for r in rows)
    assert all(r["owner"] is None for r in rows)


def test_no_row_holds_the_empty_concept(kitchen):
    """⚠️ THE GUARD ON THE '' DEFAULT. The default exists only because SQLite cannot add a NOT NULL
    column to a populated table without one, and the table-rebuild escape is unavailable here because
    three tables FK into ingredients. It is transient: the migration's UPDATE overwrites it, and
    nothing should ever write it again. If this fails, something inserted a row without a concept."""
    assert kitchen.count("ingredients", "concept = ''") == 0
    assert kitchen.count("ingredients", "concept IS NULL") == 0
    assert kitchen.count("ingredients", "TRIM(concept) = ''") == 0


def test_ids_are_unchanged_and_the_stored_links_still_resolve(kitchen):
    """Option D exists to avoid re-keying. The ids must be exactly what they were."""
    with kitchen.conn() as c:
        ids = {r["id"] for r in c.execute("SELECT id FROM ingredients")}
        dangling = c.execute(
            "SELECT COUNT(*) FROM recipe_ingredients ri LEFT JOIN ingredients i ON i.id = ri.ingredient_id "
            "WHERE ri.ingredient_id IS NOT NULL AND i.id IS NULL").fetchone()[0]
    assert {"garlic", "red_onion", "soy_sauce"} <= ids       # readable slugs, not surrogates
    assert dangling == 0
    assert kitchen.fk_orphans() == []


# ---- the four constraint cases: the heart of the stage ----------------------------------------------

@pytest.fixture
def two_users(kitchen):
    """Real user rows. owner is a FOREIGN KEY to users.id, so an invented integer is rejected, which
    is the constraint doing its job and worth knowing rather than working around."""
    from harness import ensure_test_user
    return ensure_test_user(email="owner-a@test.local"), ensure_test_user(email="owner-b@test.local")


def _ins(kitchen, iid, concept, owner):
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, concept, owner) VALUES (?,?,?,?)",
                  (iid, concept, concept, owner))


def test_1_two_shared_rows_for_one_concept_are_REJECTED(kitchen):
    """⚠️ THE CASE THAT NEEDS THE PARTIAL INDEX. UNIQUE(owner, concept) alone does NOT catch this,
    because SQLite treats NULLs as distinct in a unique index, so (NULL,'x') and (NULL,'x') do not
    collide. Measured before the migration was written. The partial index on concept WHERE owner IS
    NULL is what makes one-shared-per-concept true."""
    _ins(kitchen, "gochujang", "gochujang", None)
    with pytest.raises(sqlite3.IntegrityError):
        _ins(kitchen, "gochujang_2", "gochujang", None)
    assert kitchen.count("ingredients", "concept = 'gochujang'") == 1


def test_2_a_shared_and_a_personal_row_for_one_concept_COEXIST(kitchen, two_users):
    """The whole point of Option D. Under the old global-slug key this was impossible."""
    a, _b = two_users
    _ins(kitchen, "gochujang", "gochujang", None)          # shared
    _ins(kitchen, f"gochujang__u{a}", "gochujang", a)      # user a's personal
    assert kitchen.count("ingredients", "concept = 'gochujang'") == 2
    with kitchen.conn() as c:
        owners = {r["owner"] for r in c.execute(
            "SELECT owner FROM ingredients WHERE concept = 'gochujang'")}
    assert owners == {None, a}


def test_3_two_personal_rows_for_ONE_user_are_REJECTED(kitchen, two_users):
    """Rule 1: an ingredient is shared or personal, and a user holds one row per concept."""
    a, _b = two_users
    _ins(kitchen, f"gochujang__u{a}", "gochujang", a)
    with pytest.raises(sqlite3.IntegrityError):
        _ins(kitchen, f"gochujang__u{a}b", "gochujang", a)


def test_4_two_personal_rows_for_DIFFERENT_users_COEXIST(kitchen, two_users):
    """Rule 3: each user's personal library is their own."""
    a, b = two_users
    _ins(kitchen, f"gochujang__u{a}", "gochujang", a)
    _ins(kitchen, f"gochujang__u{b}", "gochujang", b)
    assert kitchen.count("ingredients", "concept = 'gochujang'") == 2


def test_one_index_alone_would_not_be_enough(kitchen):
    """Pins WHY there are two indexes, so a later reader does not simplify them into one. Rebuilds the
    single-index version in a scratch database and shows it admits the row case 1 rejects."""
    scratch = sqlite3.connect(":memory:")
    scratch.execute("CREATE TABLE t (id TEXT PRIMARY KEY, concept TEXT NOT NULL, owner INTEGER, "
                    "UNIQUE(owner, concept))")
    scratch.execute("INSERT INTO t VALUES ('a','gochujang',NULL)")
    scratch.execute("INSERT INTO t VALUES ('b','gochujang',NULL)")     # accepted, and should not be
    assert scratch.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2

    with kitchen.conn() as c:                                          # the real schema refuses it
        idx = {r["name"] for r in c.execute("PRAGMA index_list(ingredients)")}
    assert {"idx_ingredients_owner_concept", "idx_ingredients_shared_concept"} <= idx


# ---- inert ------------------------------------------------------------------------------------------

def test_nothing_reads_the_new_columns_yet(kitchen):
    """Stage 1 is shape only. The effective-library read is stage 2 and the create path is stage 3."""
    import ast
    from pathlib import Path
    import app
    src = Path(app.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr in ("concept", "owner")
             and isinstance(n.value, ast.Name) and n.value.id == "Ingredient"]
    assert reads == [], "app.py reads Ingredient.concept/owner, but stage 1 is schema-only"

    body = kitchen.client.get("/api/ingredients/garlic").get_json()
    assert body["concept"] == "garlic" and body["owner"] is None   # additive in the whole-row drawer


def test_owner_must_be_a_real_user(kitchen):
    """The FK is not decorative. An invented owner id is rejected, which is what stops a personal row
    being stranded on a user that does not exist."""
    with pytest.raises(sqlite3.IntegrityError):
        _ins(kitchen, "orphan", "orphan", 99999)
