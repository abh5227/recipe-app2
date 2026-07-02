"""HTTP API behavior for recipes, ratings, the cooking log, and the ingredient guide."""


def test_list_recipes(kitchen):
    r = kitchen.client.get("/api/recipes")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 5
    assert all("source" in row for row in data)


def test_get_seed_recipe_shape(kitchen):
    d = kitchen.client.get("/api/recipes/gai-yang").get_json()
    assert d["is_seed"] is True
    assert d["is_editable"] is False
    assert len(d["people"]) == 2
    assert d["changes"] == {}
    for key in ("recipe", "ingredients", "steps", "stats"):
        assert key in d


def test_missing_recipe_404(kitchen):
    assert kitchen.client.get("/api/recipes/does-not-exist").status_code == 404


def test_create_edit_delete_app_recipe(kitchen):
    create = kitchen.client.post("/api/recipes", json={
        "name": "Test Dish",
        "ingredients": [{"qty": "1", "text": "thing"}],
        "steps": ["do it"],
    })
    assert create.status_code == 201
    rid = create.get_json()["id"]
    assert rid == "test-dish"

    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert d["is_editable"] is True
    assert d["is_seed"] is False
    assert d["changes"] == {}

    # a duplicate name (same slug) is rejected
    dup = kitchen.client.post("/api/recipes", json={"name": "Test Dish", "ingredients": [], "steps": []})
    assert dup.status_code == 409

    edit = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Test Dish",
        "ingredients": [{"qty": "2", "text": "thing"}],
        "steps": ["do it", "and more"],
    })
    assert edit.status_code == 200

    assert kitchen.client.delete(f"/api/recipes/{rid}").status_code == 200
    assert kitchen.client.get(f"/api/recipes/{rid}").status_code == 404


def test_edit_preserves_unchanged_harvested_grams(kitchen):
    # The create path writes NULL grams; set grams/secondary_measure directly to simulate an
    # imported recipe. These are PLAIN lines (created via {qty, text}) -> label=NULL with the name
    # in raw_text, mirroring the imported 15 and exercising the raw_text side of the
    # (qty, label||raw_text) key. flour and cocoa share a qty ("1 cup"), so ONLY the name (raw_text)
    # tells them apart -- a label-only key would collide here and carry the wrong weight.
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Grams Keep Test",
        "ingredients": [{"qty": "1 cup", "text": "flour"},
                        {"qty": "1 cup", "text": "cocoa"},
                        {"qty": "2 cups", "text": "milk"}],
        "steps": ["mix"],
    }).get_json()["id"]
    with kitchen.conn() as c:
        # guard the premise: the seeded lines really are plain (label NULL, name in raw_text)
        rows = c.execute("SELECT label FROM recipe_ingredients WHERE recipe_id=?", (rid,)).fetchall()
        assert all(r["label"] is None for r in rows)
        c.execute("UPDATE recipe_ingredients SET grams=120.0, secondary_measure='1 cup' WHERE recipe_id=? AND raw_text='flour'", (rid,))
        c.execute("UPDATE recipe_ingredients SET grams=50.0 WHERE recipe_id=? AND raw_text='cocoa'", (rid,))
        c.execute("UPDATE recipe_ingredients SET grams=480.0 WHERE recipe_id=? AND raw_text='milk'", (rid,))

    def weight(name):
        with kitchen.conn() as c:
            r = c.execute("SELECT grams, secondary_measure FROM recipe_ingredients "
                          "WHERE recipe_id=? AND raw_text=?", (rid, name)).fetchone()
        return (r["grams"], r["secondary_measure"])

    # (a) flour + cocoa UNCHANGED (same qty, told apart only by raw_text); (b) milk's qty CHANGED
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Grams Keep Test",
        "ingredients": [{"qty": "1 cup", "text": "flour"},
                        {"qty": "1 cup", "text": "cocoa"},
                        {"qty": "3 cups", "text": "milk"}],
        "steps": ["mix", "bake"],
    }).status_code == 200
    assert weight("flour") == (120.0, "1 cup")   # (a) unchanged plain line -> preserved via raw_text key
    assert weight("cocoa") == (50.0, None)        # (a) same qty as flour -> kept its OWN grams, not flour's
    assert weight("milk") == (None, None)         # (b) changed qty -> harvested value cleared

    # (c) note-only change on flour (note isn't part of the key) -> grams preserved
    assert kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Grams Keep Test",
        "ingredients": [{"qty": "1 cup", "text": "flour", "note": "sifted"},
                        {"qty": "1 cup", "text": "cocoa"},
                        {"qty": "3 cups", "text": "milk"}],
        "steps": ["mix", "bake"],
    }).status_code == 200
    assert weight("flour") == (120.0, "1 cup")


def test_seed_recipe_is_read_only(kitchen):
    assert kitchen.client.put("/api/recipes/gai-yang", json={
        "name": "x", "ingredients": [], "steps": []}).status_code == 403
    assert kitchen.client.delete("/api/recipes/gai-yang").status_code == 403


def test_rating(kitchen):
    ok = kitchen.client.post("/api/recipes/gai-yang/rating", json={"rating": 4})
    assert ok.status_code == 200
    assert ok.get_json()["rating"] == 4
    assert kitchen.client.post("/api/recipes/gai-yang/rating", json={"rating": 9}).status_code == 400


def test_cook_log(kitchen):
    after_cook = kitchen.client.post("/api/recipes/gai-yang/cooked", json={}).get_json()
    assert after_cook["cook_count"] == 1
    after_uncook = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()
    assert after_uncook["cook_count"] == 0


def test_provisional_marker_tracks_non_app_source(kitchen):
    # any non-app cook source (e.g. the forthcoming 'rating-inferred') renders provisional...
    with kitchen.conn() as c:
        c.execute("INSERT INTO cook_log (recipe_id, cooked_on, source) VALUES (?, ?, ?)",
                  ("gai-yang", "2025-01-01", "rating-inferred"))
    inferred = kitchen.client.get("/api/recipes/gai-yang").get_json()["stats"]
    assert inferred["last_cooked_provisional"] is True

    # ...while a real app-logged cook (via the endpoint) stays confirmed
    kitchen.client.post("/api/recipes/aloo-gobhi/cooked", json={})
    confirmed = kitchen.client.get("/api/recipes/aloo-gobhi").get_json()["stats"]
    assert confirmed["last_cooked_provisional"] is False


def test_cooked_with_valid_past_date(kitchen):
    # a real past date logs a cook ON that date, still a real 'app' cook
    s = kitchen.client.post("/api/recipes/gai-yang/cooked", json={"date": "2024-05-01"}).get_json()
    assert s["cook_count"] == 1
    with kitchen.conn() as c:
        row = c.execute("SELECT cooked_on, source FROM cook_log WHERE recipe_id='gai-yang'").fetchone()
    assert row["cooked_on"] == "2024-05-01" and row["source"] == "app"


def test_cooked_future_date_rejected(kitchen):
    # the backend is the real gate (the input's max is bypassable): 400 AND nothing inserted
    r = kitchen.client.post("/api/recipes/gai-yang/cooked", json={"date": "2999-01-01"})
    assert r.status_code == 400
    assert kitchen.count("cook_log", "recipe_id='gai-yang'") == 0


def test_cooked_malformed_date_rejected(kitchen):
    r = kitchen.client.post("/api/recipes/gai-yang/cooked", json={"date": "not-a-date"})
    assert r.status_code == 400
    assert kitchen.count("cook_log", "recipe_id='gai-yang'") == 0


def test_cooked_no_date_logs_today(kitchen):
    # unchanged behavior: no date -> the cook_log default date('now') (UTC, matching the insert)
    import datetime
    today_utc = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    s = kitchen.client.post("/api/recipes/gai-yang/cooked", json={}).get_json()
    assert s["cook_count"] == 1
    with kitchen.conn() as c:
        row = c.execute("SELECT cooked_on FROM cook_log WHERE recipe_id='gai-yang'").fetchone()
    assert row["cooked_on"] == today_utc


def test_cooked_and_rated(kitchen):
    # one atomic call logs a cook AND sets the rating
    s = kitchen.client.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 5}).get_json()
    assert s["cook_count"] == 1 and s["rating"] == 5
    # invalid rating -> 400
    assert kitchen.client.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 9}).status_code == 400
    # unknown recipe -> 404
    assert kitchen.client.post("/api/recipes/nope/cooked-and-rated", json={"rating": 3}).status_code == 404


def test_undo_to_zero_clears_rating(kitchen):
    # cook + rate, then undo back to 0 -> rating cleared (never uncooked-but-rated)
    kitchen.client.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 5})
    s = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()
    assert s["cook_count"] == 0 and s["rating"] is None


def test_undo_with_cooks_remaining_keeps_rating(kitchen):
    # two cooks + a rating; undo one -> still cooked, rating stands
    kitchen.client.post("/api/recipes/gai-yang/cooked", json={})
    kitchen.client.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 4})
    s = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()
    assert s["cook_count"] == 1 and s["rating"] == 4


def test_uncook_nonexistent_is_404(kitchen):
    assert kitchen.client.post("/api/recipes/does-not-exist/uncook", json={}).status_code == 404


def test_uncook_reports_removed_cook_and_cleared_rating(kitchen):
    # undo the only cook + its rating -> response reports exactly what it removed (for a redo)
    kitchen.client.post("/api/recipes/gai-yang/cooked", json={"date": "2024-05-01"})
    kitchen.client.post("/api/recipes/gai-yang/rating", json={"rating": 5})
    u = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()["undone"]
    assert u["cooked_on"] == "2024-05-01" and u["source"] == "app" and u["cleared_rating"] == 5


def test_uncook_undone_no_cleared_rating_when_cooks_remain(kitchen):
    # a second cook + rating; undo one -> rating survived, so cleared_rating is None
    kitchen.client.post("/api/recipes/gai-yang/cooked", json={})
    kitchen.client.post("/api/recipes/gai-yang/cooked-and-rated", json={"rating": 4})
    u = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()["undone"]
    assert u["source"] == "app" and u["cleared_rating"] is None


def test_redo_readds_exact_cooked_on_and_source(kitchen):
    r = kitchen.client.post("/api/recipes/gai-yang/redo-cook",
                            json={"cooked_on": "2024-11-16", "source": "rating-inferred"}).get_json()
    assert r["cook_count"] == 1
    with kitchen.conn() as c:
        row = c.execute("SELECT cooked_on, source FROM cook_log WHERE recipe_id='gai-yang'").fetchone()
    assert row["cooked_on"] == "2024-11-16" and row["source"] == "rating-inferred"   # non-app source round-trips


def test_redo_restores_rating_only_when_given(kitchen):
    # with rating -> restored
    s = kitchen.client.post("/api/recipes/gai-yang/redo-cook",
                            json={"cooked_on": "2024-05-01", "source": "app", "rating": 5}).get_json()
    assert s["cook_count"] == 1 and s["rating"] == 5
    # without rating on a fresh recipe -> cook added, no rating
    s2 = kitchen.client.post("/api/recipes/aloo-gobhi/redo-cook",
                             json={"cooked_on": "2024-05-01", "source": "app"}).get_json()
    assert s2["cook_count"] == 1 and s2["rating"] is None


def test_undo_then_redo_round_trips_cook_and_rating(kitchen):
    # the full one-shot: cook+rate -> uncook (clears both) -> redo the reported cook -> both restored
    kitchen.client.post("/api/recipes/gai-yang/cooked", json={"date": "2024-05-01"})
    kitchen.client.post("/api/recipes/gai-yang/rating", json={"rating": 5})
    u = kitchen.client.post("/api/recipes/gai-yang/uncook", json={}).get_json()
    assert u["cook_count"] == 0 and u["rating"] is None
    body = {"cooked_on": u["undone"]["cooked_on"], "source": u["undone"]["source"],
            "rating": u["undone"]["cleared_rating"]}
    s = kitchen.client.post("/api/recipes/gai-yang/redo-cook", json=body).get_json()
    assert s["cook_count"] == 1 and s["rating"] == 5


def test_redo_bad_source_400_inserts_nothing(kitchen):
    r = kitchen.client.post("/api/recipes/gai-yang/redo-cook",
                            json={"cooked_on": "2024-05-01", "source": "bogus"})
    assert r.status_code == 400
    assert kitchen.count("cook_log", "recipe_id='gai-yang'") == 0


def test_redo_future_date_400_inserts_nothing(kitchen):
    r = kitchen.client.post("/api/recipes/gai-yang/redo-cook",
                            json={"cooked_on": "2999-01-01", "source": "app"})
    assert r.status_code == 400
    assert kitchen.count("cook_log", "recipe_id='gai-yang'") == 0


def test_redo_malformed_date_400_inserts_nothing(kitchen):
    r = kitchen.client.post("/api/recipes/gai-yang/redo-cook",
                            json={"cooked_on": "nope", "source": "app"})
    assert r.status_code == 400
    assert kitchen.count("cook_log", "recipe_id='gai-yang'") == 0


def test_deleting_recipe_clears_its_stats(kitchen):
    # deletion relies on ON DELETE CASCADE to remove the recipe's rating + cook history
    cl = kitchen.client
    cl.post("/api/recipes", json={"name": "Temp", "ingredients": [{"qty": "1", "text": "x"}], "steps": ["go"]})
    cl.post("/api/recipes/temp/rating", json={"rating": 5})
    cl.post("/api/recipes/temp/cooked", json={})
    assert kitchen.count("ratings", "recipe_id='temp'") == 1
    assert kitchen.count("cook_log", "recipe_id='temp'") == 1

    assert cl.delete("/api/recipes/temp").status_code == 200
    assert kitchen.count("ratings", "recipe_id='temp'") == 0
    assert kitchen.count("cook_log", "recipe_id='temp'") == 0
    assert kitchen.fk_orphans() == []


def test_ingredients_and_in_season(kitchen):
    lst = kitchen.client.get("/api/ingredients").get_json()
    assert len(lst) == 36
    assert all("id" in i and "name" in i for i in lst)

    one = kitchen.client.get("/api/ingredients/garlic")
    assert one.status_code == 200
    assert "season" in one.get_json()

    sm = kitchen.client.get("/api/in-season/6").get_json()
    assert sm["month"] == 6
    assert isinstance(sm["ingredients"], list)
