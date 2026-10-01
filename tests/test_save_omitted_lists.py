"""A PUT that OMITS a key leaves what that key names alone. Only an explicit value changes it.

⚠️ WHY THIS IS A DATA-SAFETY FILE AND NOT A STYLE ONE. write_plan_ahead deletes every wait and
storage row of the recipe and reinserts from the payload, so a PUT with no `waits` key deleted all of
them and answered 200. The header write had the same shape through _kept: a payload with no `notes`
key compared "" against the stored headnote, found them different, and wrote NULL over it. Live
carries 107 waits and 30 storage rows over 90 recipes, and the headnotes are the longest prose in the
database. The browser always sends every key, so nothing in the app reached this. The import review
posts plain text, a script posts what it has, and a stale bundle posts the keys it knew about.

The distinction this file pins: ABSENT means "no opinion", and an explicit empty list means "delete
them". A save cannot be allowed to express the second by accident.
"""
import app
import harness  # noqa: F401


def _recipe(client):
    rid = client.post("/api/recipes", json={
        "name": "Omit Dish", "notes": "Keep the headnote.", "descr": "A description.",
        "servings": "4", "prep_time": "10 min", "author": "Someone",
        "ingredients": [{"qty": "2", "text": "eggs"}],
        "steps": ["Beat the eggs.", "Rest the dough."],
    }).get_json()["id"]
    steps = client.get(f"/api/recipes/{rid}").get_json()["steps"]
    r = client.put(f"/api/recipes/{rid}", json={
        "name": "Omit Dish", "notes": "Keep the headnote.", "descr": "A description.",
        "servings": "4", "prep_time": "10 min", "author": "Someone",
        "ingredients": [{"quantity": "2", "unit": "", "text": "eggs"}],
        "steps": [{"id": s["id"], "text": s["text"]} for s in steps],
        "waits": [{"kind": "rest", "label": "rest 1 hour", "step_id": steps[1]["id"]},
                  {"kind": "marinate", "label": "marinate overnight"}],
        "storage": [{"where_kept": "fridge", "label": "keeps 3 days", "applies_to": "the dough"}],
    })
    assert r.status_code == 200, r.get_json()
    return rid


def _state(client, rid):
    d = client.get(f"/api/recipes/{rid}").get_json()
    return ([w["label"] for w in d["waits"]], [x["label"] for x in d["storage"]],
            d["recipe"]["notes"], d["recipe"]["descr"], [s["text"] for s in d["steps"]],
            [i["label"] for i in d["ingredients"]])


def _bare(client, rid):
    """The smallest legal save: a name, the two required lists, and nothing else."""
    d = client.get(f"/api/recipes/{rid}").get_json()
    return {"name": d["recipe"]["name"],
            "ingredients": [{"id": i["id"], "quantity": i["quantity"] or "", "unit": i["unit"] or "",
                             "text": i["label"]} for i in d["ingredients"]],
            "steps": [{"id": s["id"], "text": s["text"]} for s in d["steps"]]}


# ---- the omissions -------------------------------------------------------------------------------

def test_a_put_with_no_waits_key_keeps_the_waits(kitchen):
    rid = _recipe(kitchen.client)
    before = _state(kitchen.client, rid)
    assert before[0] == ["rest 1 hour", "marinate overnight"]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_bare(kitchen.client, rid)).status_code == 200
    assert _state(kitchen.client, rid)[0] == before[0], "an omitted waits key deleted the waits"


def test_a_put_with_no_storage_key_keeps_the_storage(kitchen):
    rid = _recipe(kitchen.client)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_bare(kitchen.client, rid)).status_code == 200
    assert _state(kitchen.client, rid)[1] == ["keeps 3 days"]


def test_a_put_with_no_notes_key_keeps_the_headnote(kitchen):
    rid = _recipe(kitchen.client)
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_bare(kitchen.client, rid)).status_code == 200
    assert _state(kitchen.client, rid)[2] == "Keep the headnote."


def test_a_put_with_no_header_keys_keeps_every_header_field(kitchen):
    """Every field in EDITABLE_HEADER_FIELDS, not just the one that prompted this."""
    rid = _recipe(kitchen.client)
    with kitchen.conn() as c:
        before = dict(c.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone())
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_bare(kitchen.client, rid)).status_code == 200
    with kitchen.conn() as c:
        after = dict(c.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone())
    changed = {k: (before[k], after[k]) for k in app.EDITABLE_HEADER_FIELDS if before[k] != after[k]}
    assert changed == {}, f"an omitted header key overwrote a stored value: {changed}"


def test_the_wait_step_link_survives_an_omitted_waits_key(kitchen):
    """The link is the part with nowhere else to live: step_id exists only on the wait row."""
    rid = _recipe(kitchen.client)
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    linked = [w["step_id"] for w in d["waits"]]
    assert any(linked), "fixture should have a linked wait"
    assert kitchen.client.put(f"/api/recipes/{rid}", json=_bare(kitchen.client, rid)).status_code == 200
    after = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert [w["step_id"] for w in after["waits"]] == linked


# ---- an explicit empty list still deletes -------------------------------------------------------

def test_an_explicit_empty_waits_list_deletes_them(kitchen):
    rid = _recipe(kitchen.client)
    body = _bare(kitchen.client, rid) | {"waits": []}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _state(kitchen.client, rid)[0] == []


def test_an_explicit_empty_storage_list_deletes_them(kitchen):
    rid = _recipe(kitchen.client)
    body = _bare(kitchen.client, rid) | {"storage": []}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert _state(kitchen.client, rid)[1] == []


def test_an_explicit_empty_notes_clears_the_headnote(kitchen):
    rid = _recipe(kitchen.client)
    body = _bare(kitchen.client, rid) | {"notes": ""}
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 200
    assert (_state(kitchen.client, rid)[2] or "") == ""


def test_a_waits_list_that_is_not_a_list_is_refused_rather_than_read_as_empty(kitchen):
    """`or []` read a null, a string and a dict as "delete them all". A wrong type is a client bug,
    so it is refused with nothing written."""
    rid = _recipe(kitchen.client)
    for bad in (None, "", "rest 1 hour", {"label": "rest"}, 0):
        body = _bare(kitchen.client, rid) | {"waits": bad}
        r = kitchen.client.put(f"/api/recipes/{rid}", json=body)
        assert r.status_code == 400, f"{bad!r} was accepted ({r.status_code})"
        assert _state(kitchen.client, rid)[0] == ["rest 1 hour", "marinate overnight"], bad


# ---- the two lists that were already safe, pinned so they stay that way -------------------------

def test_a_put_with_no_ingredients_key_is_refused_with_nothing_written(kitchen):
    rid = _recipe(kitchen.client)
    before = _state(kitchen.client, rid)
    body = _bare(kitchen.client, rid)
    del body["ingredients"]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 400
    assert _state(kitchen.client, rid) == before


def test_a_put_with_no_steps_key_is_refused_with_nothing_written(kitchen):
    rid = _recipe(kitchen.client)
    before = _state(kitchen.client, rid)
    body = _bare(kitchen.client, rid)
    del body["steps"]
    assert kitchen.client.put(f"/api/recipes/{rid}", json=body).status_code == 400
    assert _state(kitchen.client, rid) == before


def test_a_photo_reorder_with_no_order_key_is_refused(kitchen):
    """The third list a write endpoint accepts. It validates an EXACT permutation, so an absent key
    is already a 400 with nothing written — pinned here so the sweep has one place to read."""
    rid = _recipe(kitchen.client)
    r = kitchen.client.patch(f"/api/recipes/{rid}/photos/order", json={})
    assert r.status_code == 400
