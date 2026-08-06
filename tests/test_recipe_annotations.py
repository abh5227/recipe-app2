"""O-c-1 Stage 1b: get_recipe attaches a derived `annotations` block — the RAW diff_snapshots entries of
current-vs-original. Empty until a recipe diverges from its birth baseline (the post-O-b common case),
empty (fail-safe) when no original exists, and the actual diff once content changes. Proves the block
wires diff_snapshots end-to-end through the serve path; the client render is a later stage."""
import app
import harness  # noqa: F401  (ensures repo/tests on sys.path)


def _recipe(client, name="Anno Dish"):
    return client.post("/api/recipes", json={
        "name": name,
        "ingredients": [{"heading": "Base"}, {"qty": "2", "text": "eggs"}, {"qty": "1 cup", "text": "flour"}],
        "steps": ["Beat the eggs"],
    }).get_json()["id"]


def test_unedited_recipe_has_empty_annotations(kitchen):
    # current == original at birth -> byte-equal short-circuit -> []
    rid = _recipe(kitchen.client)
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert d["annotations"] == []


def test_edited_recipe_has_annotations(kitchen):
    rid = _recipe(kitchen.client)
    # diverge from the birth baseline: eggs amount 2 -> 4 (original stays "2", never re-captured on edit)
    r = kitchen.client.put(f"/api/recipes/{rid}", json={
        "name": "Anno Dish",
        "ingredients": [{"heading": "Base"}, {"qty": "4", "text": "eggs"}, {"qty": "1 cup", "text": "flour"}],
        "steps": ["Beat the eggs"],
    })
    assert r.status_code == 200

    ann = kitchen.client.get(f"/api/recipes/{rid}").get_json()["annotations"]
    assert ann != []
    # the eggs amount change: ONE ingredient/modified/amount, anchored at new_pos 0 (first REAL line —
    # the heading is excluded from the heading-excluded index), from "2" to "4".
    amt = [c for c in ann if c.get("kind") == "ingredient" and c.get("type") == "modified"
           and c.get("field") == "amount"]
    assert len(amt) == 1
    assert amt[0]["new_pos"] == 0
    assert amt[0]["from"] == "2" and amt[0]["to"] == "4"


def test_recipe_without_original_has_empty_annotations(kitchen):
    # fail-safe: a recipe with no reason='original' baseline (a pre-O-b state) must not error -> []
    rid = _recipe(kitchen.client)
    with kitchen.conn() as c:
        c.execute("DELETE FROM recipe_snapshots WHERE recipe_id = ? AND reason = 'original'", (rid,))
    d = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    assert d["annotations"] == []
