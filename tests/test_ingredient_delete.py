"""DELETE /api/ingredients/<iid>, the undo for the save gate's create path (add-on-save stage 6).

The app has never deleted an ingredient. This route is the only way, and what it must never do
matters far more than what it does: the 36 hand-authored rows hold prose nothing regenerates, and 30
of them are also referenced by [[key]] text already typed into recipe steps. So the weight here is on
the two refusals, not on the happy path.
"""
import app


def _lib(kitchen, *pairs):
    with kitchen.conn() as c:
        c.executemany("INSERT INTO library_names (library_id, canonical) VALUES (?,?)", pairs)


def _promote(kitchen, library_id, canonical, recipe_name="Holder"):
    """Create a source='app' row the way stage 5 really does, through the save gate, then unlink it
    by rewriting the recipe without the line. Leaves an unreferenced promoted row."""
    _lib(kitchen, (library_id, canonical))
    rid = kitchen.client.post("/api/recipes", json={
        "name": recipe_name, "ingredients": [{"item_library_id": library_id}], "steps": [],
    }).get_json()["id"]
    return rid


def _row(kitchen, iid):
    with kitchen.conn() as c:
        return c.execute("SELECT id, source, library_id FROM ingredients WHERE id=?", (iid,)).fetchone()


# ---- the seed protection: the most important thing in this file ---------------------------------

def test_a_seed_row_cannot_be_deleted(kitchen):
    """⚠️ THE 36 ARE UNDELETABLE. They hold hand-written prose and 30 of them are named in step
    [[key]] text, so losing one is not recoverable from anything in the repo."""
    r = kitchen.client.delete("/api/ingredients/garlic")
    assert r.status_code == 403
    assert r.get_json()["error"] == \
        "hand-authored ingredients can't be deleted here, edit seed.py instead"
    assert _row(kitchen, "garlic") is not None
    assert kitchen.count("ingredients") == 36


def test_every_one_of_the_36_refuses(kitchen):
    """Not a sample. Every seed row is tried, because a tier check that works on garlic and not on
    some other row is worse than none."""
    with kitchen.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM ingredients WHERE source='seed'")]
    assert len(ids) == 36
    for iid in ids:
        assert kitchen.client.delete(f"/api/ingredients/{iid}").status_code == 403
    assert kitchen.count("ingredients") == 36
    assert kitchen.count("ingredients", "source='seed'") == 36


def test_tier_is_checked_before_references_so_a_seed_row_gets_the_truer_message(kitchen):
    """All 36 are BOTH seed and linked. Refusing on the intrinsic property first is what
    delete_recipe does with tier before ownership, and it yields the message that explains why."""
    with kitchen.conn() as c:
        linked = c.execute("SELECT ingredient_id FROM recipe_ingredients "
                           "WHERE ingredient_id IS NOT NULL LIMIT 1").fetchone()["ingredient_id"]
    r = kitchen.client.delete(f"/api/ingredients/{linked}")
    assert r.status_code == 403                                  # not 409
    assert "seed.py" in r.get_json()["error"]


def test_the_allowlist_protects_a_tier_nobody_has_invented_yet(kitchen):
    """DELETABLE_INGREDIENT_SOURCES is an allowlist, not "anything that is not seed", so a future
    tier is protected by default rather than deletable by default."""
    assert app.DELETABLE_INGREDIENT_SOURCES == ("app",)
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, source) VALUES ('probe','Probe','someday')")
    assert kitchen.client.delete("/api/ingredients/probe").status_code == 403
    assert _row(kitchen, "probe") is not None


# ---- the linked-row refusal ----------------------------------------------------------------------

def test_a_linked_promoted_row_is_refused_and_the_link_survives(kitchen):
    """⚠️ Deleting this would dangle a recipe's link. The pre-check names how many recipes to unlink,
    which is the whole reason it exists rather than catching the constraint error."""
    rid = _promote(kitchen, "Q1063736", "penne")
    assert _row(kitchen, "penne")["source"] == "app"             # deletable tier, still refused

    r = kitchen.client.delete("/api/ingredients/penne")
    assert r.status_code == 409
    assert r.get_json()["error"] == "penne is still linked by 1 recipe, unlink it there first"

    assert _row(kitchen, "penne") is not None
    with kitchen.conn() as c:
        assert c.execute("SELECT ingredient_id FROM recipe_ingredients WHERE recipe_id=?",
                         (rid,)).fetchone()["ingredient_id"] == "penne"


def test_the_message_counts_distinct_recipes(kitchen):
    _promote(kitchen, "Q1063736", "penne", recipe_name="One")
    kitchen.client.post("/api/recipes", json={
        "name": "Two", "ingredients": [{"item": "penne"}, {"item": "penne"}], "steps": []})
    r = kitchen.client.delete("/api/ingredients/penne")
    assert r.get_json()["error"] == "penne is still linked by 2 recipes, unlink it there first"


def test_the_foreign_key_is_the_backstop_behind_the_pre_check(kitchen):
    """The pre-check writes the message. This is what makes it safe: recipe_ingredients.ingredient_id
    carries no ondelete, and orm_session turns foreign keys on per connection, so the database
    refuses a dangling delete even if the pre-check were bypassed."""
    import sqlalchemy
    _promote(kitchen, "Q1063736", "penne")
    with kitchen.session() as s:
        try:
            s.execute(sqlalchemy.text("DELETE FROM ingredients WHERE id='penne'"))
            s.commit()
            raised = False
        except sqlalchemy.exc.IntegrityError:
            s.rollback()
            raised = True
    assert raised
    assert _row(kitchen, "penne") is not None


# ---- the happy path: a mis-promote is reversible --------------------------------------------------

def test_an_unreferenced_promoted_row_is_deleted(kitchen):
    """The case this stage exists for. Promote by mistake, unlink it, remove the row."""
    rid = _promote(kitchen, "Q1063736", "penne")
    kitchen.client.put(f"/api/recipes/{rid}",
                       json={"name": "Holder", "ingredients": [], "steps": []})   # unlink
    before = kitchen.count("ingredients")

    r = kitchen.client.delete("/api/ingredients/penne")
    assert r.status_code == 200
    assert r.get_json() == {"deleted": "penne"}
    assert _row(kitchen, "penne") is None
    assert kitchen.count("ingredients") == before - 1 == 36


def test_child_rows_go_with_it(kitchen):
    """A promoted row has no season or region rows, but both cascade, so the delete stays correct if
    one ever does."""
    with kitchen.conn() as c:
        c.execute("INSERT INTO ingredients (id, name, source) VALUES ('probe','Probe','app')")
        c.execute("INSERT INTO ingredient_seasons (ingredient_id, month) VALUES ('probe', 6)")
    assert kitchen.count("ingredient_seasons", "ingredient_id='probe'") == 1

    assert kitchen.client.delete("/api/ingredients/probe").status_code == 200
    assert kitchen.count("ingredient_seasons", "ingredient_id='probe'") == 0
    assert kitchen.fk_orphans() == []


def test_not_found_is_404(kitchen):
    r = kitchen.client.delete("/api/ingredients/nothing_like_this")
    assert r.status_code == 404
    assert r.get_json()["error"] == "ingredient not found"


# ---- auth, and the standing invariants -------------------------------------------------------------

def test_login_gated_like_the_other_write_routes(kitchen_logged_out):
    assert kitchen_logged_out.client.delete("/api/ingredients/garlic").status_code == 401
    assert kitchen_logged_out.client.delete("/api/recipes/anything").status_code == 401


def test_the_seed_36_and_their_links_are_unreachable_by_this_route(kitchen):
    """⚠️ THE STANDING INVARIANT. Every seed row is refused on tier, and every one of them is linked
    besides, so two independent guards would each have to fail for one to be lost."""
    before_links = kitchen.count("recipe_ingredients", "ingredient_id IS NOT NULL")
    with kitchen.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM ingredients")]
    for iid in ids:
        kitchen.client.delete(f"/api/ingredients/{iid}")
    assert kitchen.count("ingredients") == 36
    assert kitchen.count("recipe_ingredients", "ingredient_id IS NOT NULL") == before_links
    assert kitchen.fk_orphans() == []
