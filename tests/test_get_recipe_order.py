"""O-c-1 Stage 1a: get_recipe must return ingredients/steps in the SAME sequence that
serialize_recipe_content uses (position, id) — because annotation new_pos is computed against the
serializer's order, so the served/rendered order must be that identical sequence or client anchors
misalign. Guards the (position, id) tiebreak on both order_by clauses."""
import json

import app
import harness  # noqa: F401  (ensures repo/tests on sys.path)


def _make(client):
    return client.post("/api/recipes", json={
        "name": "Order Align",
        "ingredients": [
            {"heading": "Base"},
            {"qty": "2", "text": "eggs"},
            {"qty": "1 cup", "text": "flour"},
            {"heading": "Topping"},
            {"qty": "3 tbsp", "text": "sugar"},
        ],
        "steps": ["Mix", "Bake", "Cool"],
    }).get_json()["id"]


def test_get_recipe_order_matches_serialize(kitchen):
    rid = _make(kitchen.client)
    payload = kitchen.client.get(f"/api/recipes/{rid}").get_json()
    with app.orm_session() as s:
        blob = json.loads(app.serialize_recipe_content(s, rid))

    # ingredients: identical sequence (position order + content signature)
    served_ing = [(x["position"], x.get("qty"), x.get("label"), x.get("raw_text")) for x in payload["ingredients"]]
    blob_ing = [(x["position"], x.get("qty"), x.get("label"), x.get("raw_text")) for x in blob["ingredients"]]
    assert served_ing == blob_ing
    assert [x["position"] for x in payload["ingredients"]] == sorted(x["position"] for x in payload["ingredients"])

    # steps: identical sequence
    served_steps = [(x["position"], x.get("text")) for x in payload["steps"]]
    blob_steps = [(x["position"], x.get("text")) for x in blob["steps"]]
    assert served_steps == blob_steps
