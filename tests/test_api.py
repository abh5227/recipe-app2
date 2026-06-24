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
