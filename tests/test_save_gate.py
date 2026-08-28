"""validate_recipe_payload, the save-time link gate (app.py).

⚠️ CHARACTERIZATION FIRST. This file was written BEFORE the add-on-save change and run green against
the unchanged gate. The gate had no tests at all, and it is the function add-on-save turns from a
validator into a writer, so the point of the first half of this file is to pin what it did BEFORE
anything moved. Anything below marked "characterization" describes behavior that must not change.

The gate is reached from two routes, POST /api/recipes and PUT /api/recipes/<rid>, and both call it on
their own session before commit. Both are exercised, because a rule that holds on create and not on
edit is a rule with a hole in it.

⚠️ THE RENAME IS THE ONLY EDIT THE CHARACTERIZATION TESTS NEEDED. validate_recipe_payload became
resolve_recipe_payload when it gained a create path, so the four tests that call it directly changed
one identifier. The nine that go through the routes were not touched at all, and they stayed green
across the change, which is the signal that mattered.
"""
import pytest

import app


def _payload(**over):
    base = {"name": "Gate Test", "ingredients": [], "steps": []}
    base.update(over)
    return base


def _create(kitchen, **over):
    return kitchen.client.post("/api/recipes", json=_payload(**over))


# ---- characterization: the return contract, called directly -------------------------------------

def test_returns_clean_and_none_for_a_valid_payload(kitchen):
    """(clean, error). clean carries exactly name/ingredients/steps, nothing else from the payload."""
    with kitchen.session() as s:
        clean, err = app.resolve_recipe_payload(s, _payload(
            ingredients=[{"qty": "2", "item": "carrot", "label": "carrots"}],
            steps=["Grate [[carrot]]."]))
    assert err is None
    assert set(clean) == {"name", "ingredients", "steps"}
    assert clean["name"] == "Gate Test"


def test_returns_none_and_a_message_when_it_refuses(kitchen):
    with kitchen.session() as s:
        clean, err = app.resolve_recipe_payload(s, _payload(
            ingredients=[{"item": "not_a_real_ingredient"}]))
    assert clean is None
    assert err == "an ingredient line links to 'not_a_real_ingredient', which isn't in your library"


def test_a_name_is_required(kitchen):
    with kitchen.session() as s:
        for name in ("", "   ", None):
            clean, err = app.resolve_recipe_payload(s, _payload(name=name))
            assert (clean, err) == (None, "a name is required")


def test_ingredients_and_steps_must_be_lists(kitchen):
    with kitchen.session() as s:
        for bad in ({"ingredients": "nope"}, {"steps": "nope"}, {"ingredients": None}):
            clean, err = app.resolve_recipe_payload(s, _payload(**bad))
            assert (clean, err) == (None, "ingredients and steps must be lists")


# ---- characterization: line links ----------------------------------------------------------------

def test_a_line_linked_to_an_existing_ingredient_is_accepted(kitchen):
    r = _create(kitchen, ingredients=[{"qty": "2", "item": "carrot", "label": "carrots"}])
    assert r.status_code == 201
    rid = r.get_json()["id"]
    with kitchen.conn() as c:
        assert c.execute("SELECT ingredient_id FROM recipe_ingredients WHERE recipe_id=?",
                         (rid,)).fetchone()["ingredient_id"] == "carrot"


def test_an_unknown_item_is_rejected_with_the_current_message(kitchen):
    r = _create(kitchen, ingredients=[{"qty": "1", "item": "penne"}])
    assert r.status_code == 400
    assert r.get_json()["error"] == \
        "an ingredient line links to 'penne', which isn't in your library"
    assert kitchen.count("recipes", "id='gate-test'") == 0     # nothing written


def test_a_line_with_no_item_is_plain_text_and_always_fine(kitchen):
    """Brand-new ingredients are allowed as text. They just are not links."""
    r = _create(kitchen, ingredients=[{"qty": "1 cup", "text": "something nobody has heard of"}])
    assert r.status_code == 201


# ---- characterization: step links ----------------------------------------------------------------

def test_an_unknown_step_key_is_rejected_with_the_current_message(kitchen):
    r = _create(kitchen, steps=["Boil the [[penne]]."])
    assert r.status_code == 400
    assert r.get_json()["error"] == "a step links to 'penne', which isn't in your library"


def test_a_known_step_key_is_accepted_in_both_forms(kitchen):
    assert _create(kitchen, steps=["Grate [[carrot]]."]).status_code == 201
    assert _create(kitchen, name="Gate Two",
                   steps=["Grate [[carrot|the carrots]]."]).status_code == 201


def test_a_step_heading_is_scanned_but_a_dict_step_s_text_is_not(kitchen):
    """⚠️ CHARACTERIZATION OF A QUIRK, not an endorsement. The scan reads a string step whole, and for
    a dict step reads only .get('heading'). A dict step's 'text' is never scanned. That is consistent
    with write_recipe_rows, which only ever writes a dict step as a heading."""
    assert _create(kitchen, steps=[{"heading": "With [[penne]]"}]).status_code == 400
    assert _create(kitchen, steps=[{"text": "With [[penne]]"}]).status_code == 201


# ---- characterization: the same rules on the edit route -------------------------------------------

def test_the_edit_route_applies_the_same_gate(kitchen):
    rid = _create(kitchen).get_json()["id"]
    bad_item = kitchen.client.put(f"/api/recipes/{rid}", json=_payload(
        ingredients=[{"item": "penne"}]))
    assert bad_item.status_code == 400
    assert bad_item.get_json()["error"] == \
        "an ingredient line links to 'penne', which isn't in your library"

    bad_step = kitchen.client.put(f"/api/recipes/{rid}", json=_payload(steps=["Boil [[penne]]."]))
    assert bad_step.status_code == 400
    assert bad_step.get_json()["error"] == "a step links to 'penne', which isn't in your library"

    ok = kitchen.client.put(f"/api/recipes/{rid}", json=_payload(
        ingredients=[{"qty": "2", "item": "carrot", "label": "carrots"}]))
    assert ok.status_code == 200


def test_a_refused_edit_leaves_the_recipe_untouched(kitchen):
    rid = _create(kitchen, ingredients=[{"qty": "2", "item": "carrot", "label": "carrots"}],
                  steps=["Original step."]).get_json()["id"]
    kitchen.client.put(f"/api/recipes/{rid}", json=_payload(
        name="Renamed", ingredients=[{"item": "penne"}], steps=["New step."]))
    with kitchen.conn() as c:
        assert c.execute("SELECT name FROM recipes WHERE id=?", (rid,)).fetchone()["name"] == "Gate Test"
        assert c.execute("SELECT text FROM recipe_steps WHERE recipe_id=?",
                         (rid,)).fetchone()["text"] == "Original step."


def test_the_gate_creates_nothing_today(kitchen):
    """⚠️ THE BASELINE THE CHANGE IS MEASURED AGAINST. Before add-on-save the gate is read-only: a
    refused save leaves the ingredient count exactly where it was, and so does an accepted one."""
    before = kitchen.count("ingredients")
    _create(kitchen, ingredients=[{"item": "penne"}])                      # refused
    _create(kitchen, name="Ok", ingredients=[{"item": "carrot"}])          # accepted
    assert kitchen.count("ingredients") == before == 36


# =================================================================================================
# ADD-ON-SAVE (stage 5): item_library_id creates a row. Everything above still holds.
# =================================================================================================

def _lib(kitchen, *pairs):
    with kitchen.conn() as c:
        c.executemany("INSERT INTO library_names (library_id, canonical) VALUES (?,?)", pairs)


def _ing(kitchen, ident):
    with kitchen.conn() as c:
        return c.execute("SELECT id, name, source, library_id, descr, pairs FROM ingredients "
                         "WHERE id=?", (ident,)).fetchone()


# ---- case 3 first, because it is the state a fresh clone is in -----------------------------------

def test_an_empty_lookup_creates_nothing_and_the_gate_stays_default_deny(kitchen):
    """⚠️ THE SELF-DISABLED STATE, AND THE MOST IMPORTANT TEST HERE. library_names is loaded from a
    gitignored server-side file, so a fresh clone and CI have none. Every item_library_id therefore
    falls into case 3 and is refused, and no row can be created by any request."""
    assert kitchen.count("library_names") == 0
    before = kitchen.count("ingredients")
    r = _create(kitchen, ingredients=[{"qty": "1", "item_library_id": "Q1063736"}])
    assert r.status_code == 400
    assert r.get_json()["error"] == \
        "an ingredient line links to library id 'Q1063736', which isn't in the library"
    assert kitchen.count("ingredients") == before == 36


def test_a_library_id_not_in_the_lookup_is_refused(kitchen):
    """Junk-proofing. Creation only ever happens for a key the table sanctions, so a stale or
    invented id creates nothing."""
    _lib(kitchen, ("Q1063736", "penne"))
    before = kitchen.count("ingredients")
    r = _create(kitchen, ingredients=[{"item_library_id": "Q_MADE_UP"}])
    assert r.status_code == 400
    assert kitchen.count("ingredients") == before


# ---- case 2b: create -----------------------------------------------------------------------------

def test_a_new_library_link_creates_the_row_and_links_to_it(kitchen):
    _lib(kitchen, ("Q1063736", "penne"))
    rid = _create(kitchen, ingredients=[
        {"qty": "200g", "item_library_id": "Q1063736", "label": "penne"}]).get_json()["id"]

    row = _ing(kitchen, "penne")
    assert row["name"] == "penne"                  # the canonical, from the TABLE
    assert row["source"] == "app"                  # stage 6 may delete it; not one of the seed 36
    assert row["library_id"] == "Q1063736"         # provenance recorded
    assert row["descr"] is None and row["pairs"] is None
    assert kitchen.count("ingredients") == 37

    with kitchen.conn() as c:
        assert c.execute("SELECT ingredient_id FROM recipe_ingredients WHERE recipe_id=?",
                         (rid,)).fetchone()["ingredient_id"] == "penne"


def test_the_name_comes_from_the_lookup_not_the_request(kitchen):
    """⚠️ THE JUNK-PROOFING, STATED AS A TEST. A caller supplies a key. It cannot choose the name."""
    _lib(kitchen, ("Q1063736", "penne"))
    _create(kitchen, ingredients=[{"item_library_id": "Q1063736",
                                   "label": "TOTALLY MADE UP", "name": "ALSO MADE UP"}])
    assert _ing(kitchen, "penne")["name"] == "penne"


def test_the_slug_is_minted_by_the_shared_rule(kitchen):
    """The same ingredient_slug the search route uses for matched_by:'slug'. Unicode survives."""
    _lib(kitchen, ("Q1", "Egg Pasta"), ("Q2", "масло сливочное"))
    _create(kitchen, ingredients=[{"item_library_id": "Q1"}, {"item_library_id": "Q2"}])
    assert _ing(kitchen, app.ingredient_slug("Egg Pasta"))["id"] == "egg_pasta"
    assert _ing(kitchen, "масло_сливочное") is not None


def test_two_lines_naming_the_same_new_library_row_create_it_once(kitchen):
    _lib(kitchen, ("Q1063736", "penne"))
    before = kitchen.count("ingredients")
    r = _create(kitchen, ingredients=[{"item_library_id": "Q1063736"},
                                      {"item_library_id": "Q1063736"}])
    assert r.status_code == 201
    assert kitchen.count("ingredients") == before + 1


# ---- case 2a: check-then-link, the 32-of-36 collision --------------------------------------------

def test_a_taken_slug_links_to_the_existing_row_and_leaves_it_alone(kitchen):
    """⚠️ WITHOUT THIS THE INSERT IS A PRIMARY-KEY CONFLICT. garlic is a hand-authored seed row with
    library_id NULL, and the library's garlic canonical slugifies straight onto its id."""
    _lib(kitchen, ("Q21546392", "garlic"))
    before_row = _ing(kitchen, "garlic")
    before_count = kitchen.count("ingredients")

    rid = _create(kitchen, ingredients=[{"item_library_id": "Q21546392"}]).get_json()["id"]

    after = _ing(kitchen, "garlic")
    assert kitchen.count("ingredients") == before_count            # nothing inserted
    assert after["name"] == before_row["name"]                     # name not overwritten
    assert after["descr"] == before_row["descr"]                   # the hand-written prose survives
    assert after["pairs"] == before_row["pairs"]
    assert after["source"] == "seed"                               # tier NOT flipped to app
    assert after["library_id"] is None                             # provenance NOT stamped on
    with kitchen.conn() as c:
        assert c.execute("SELECT ingredient_id FROM recipe_ingredients WHERE recipe_id=?",
                         (rid,)).fetchone()["ingredient_id"] == "garlic"


def test_a_second_library_row_with_the_same_slug_links_rather_than_collides(kitchen):
    """Two library rows can share a canonical (red onion is Q108910183 and Q622350). The second one
    to be linked finds the slug taken and links, rather than raising."""
    _lib(kitchen, ("QA", "shallot pearl"), ("QB", "shallot pearl"))
    r = _create(kitchen, ingredients=[{"item_library_id": "QA"}, {"item_library_id": "QB"}])
    assert r.status_code == 201
    assert kitchen.count("ingredients", "id='shallot_pearl'") == 1
    assert _ing(kitchen, "shallot_pearl")["library_id"] == "QA"    # the first one to arrive


# ---- both keys, and the edit route ----------------------------------------------------------------

def test_sending_both_keys_is_refused_rather_than_guessed(kitchen):
    _lib(kitchen, ("Q1063736", "penne"))
    r = _create(kitchen, ingredients=[{"item": "carrot", "item_library_id": "Q1063736"}])
    assert r.status_code == 400
    assert r.get_json()["error"] == "an ingredient line sends both an item and a library id — pick one"
    assert kitchen.count("ingredients") == 36


def test_the_edit_route_creates_too(kitchen):
    _lib(kitchen, ("Q1063736", "penne"))
    rid = _create(kitchen).get_json()["id"]
    r = kitchen.client.put(f"/api/recipes/{rid}", json=_payload(
        ingredients=[{"qty": "200g", "item_library_id": "Q1063736"}]))
    assert r.status_code == 200
    assert _ing(kitchen, "penne")["source"] == "app"


# ---- steps are untouched ---------------------------------------------------------------------------

def test_a_step_key_still_cannot_create(kitchen):
    """⚠️ Step-link promotion is dropped. Even with the library holding penne, a [[penne]] step is
    refused exactly as before, and nothing is created."""
    _lib(kitchen, ("Q1063736", "penne"))
    before = kitchen.count("ingredients")
    r = _create(kitchen, steps=["Boil the [[penne]]."])
    assert r.status_code == 400
    assert r.get_json()["error"] == "a step links to 'penne', which isn't in your library"
    assert kitchen.count("ingredients") == before


def test_a_step_key_works_once_a_line_has_promoted_it(kitchen):
    """The line creates the row, so a step in the SAME payload can reference the new slug. The step
    path is still a plain membership check, it just sees a set the line already grew."""
    _lib(kitchen, ("Q1063736", "penne"))
    r = _create(kitchen, ingredients=[{"item_library_id": "Q1063736"}],
                steps=["Boil the [[penne]]."])
    assert r.status_code == 201


# ---- the transaction ------------------------------------------------------------------------------

def test_a_created_row_rolls_back_when_the_save_fails_later(kitchen):
    """⚠️ THE WRITER'S SAFETY PROPERTY. The gate creates on the caller's session and does not commit.
    A duplicate recipe name fails with 409 AFTER the gate has already inserted, and `with
    orm_session()` closes without committing, so the row must not survive."""
    _lib(kitchen, ("Q1063736", "penne"))
    _create(kitchen, name="Clash")                       # take the slug
    before = kitchen.count("ingredients")

    r = _create(kitchen, name="Clash", ingredients=[{"item_library_id": "Q1063736"}])
    assert r.status_code == 409                          # fails after the gate ran
    assert kitchen.count("ingredients") == before        # and the created row is gone
    assert _ing(kitchen, "penne") is None
