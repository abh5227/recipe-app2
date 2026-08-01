"""Cook-photo album DISPLAY data (Stage 4 build 3a): the `photos` array folded into GET /api/recipes/<id>.
Proves the read the album renders from — per-photo shape (least-exposure), hero-first-then-recent order,
the cook's date present for cook-linked / absent for standalone, and is_hero (recipes.image == path).
State is driven through the REAL attach/promote endpoints; disk isolated to the temp images dir."""
import io

from PIL import Image

import app
import harness


def _own_recipe(client, name="Album Payload Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _img_bytes():
    buf = io.BytesIO(); Image.new("RGB", (60, 60), "red").save(buf, format="JPEG"); return buf.getvalue()


def _log_cook(client, rid, date=None):
    body = {"date": date} if date else {}
    return client.post(f"/api/recipes/{rid}/cooked", json=body).get_json()["cook_log_id"]


def _post_photo(client, rid, cook_log_id=None, caption=None):
    data = {"image": (io.BytesIO(_img_bytes()), "p.jpg")}
    if cook_log_id is not None:
        data["cook_log_id"] = str(cook_log_id)
    if caption is not None:
        data["caption"] = caption
    return client.post(f"/api/recipes/{rid}/photos", data=data, content_type="multipart/form-data").get_json()


def _upload_hero(client, rid):
    return client.post(f"/api/recipes/{rid}/image",
                       data={"image": (io.BytesIO(_img_bytes()), "h.jpg")}, content_type="multipart/form-data")


def _photos(client, rid):
    return client.get(f"/api/recipes/{rid}").get_json()["photos"]


def test_empty_recipe_has_empty_photos(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "No Photos Dish")
    assert _photos(a, rid) == []                              # empty album -> [] (client renders no section)


def test_photos_shape_date_and_hero(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Shape Dish")
    clid = _log_cook(a, rid)
    cook = _post_photo(a, rid, cook_log_id=clid, caption="cook one")   # cook-linked; first attach auto-heros it
    solo = _post_photo(a, rid)                                         # standalone, no cook

    photos = _photos(a, rid)
    assert {p["id"] for p in photos} == {cook["id"], solo["id"]}
    by_id = {p["id"]: p for p in photos}
    # least-exposure: exactly the album fields, no user_id/added_at internals
    assert set(by_id[cook["id"]]) == {"id", "path", "caption", "cooked_on", "is_hero"}
    # cook-linked carries the cook's DATE + caption; standalone has NO date
    assert by_id[cook["id"]]["cooked_on"] and by_id[cook["id"]]["caption"] == "cook one"
    assert by_id[solo["id"]]["cooked_on"] is None
    # is_hero reflects the POINT/linked hero (the cook photo auto-promoted on first attach)
    assert by_id[cook["id"]]["is_hero"] is True
    assert by_id[solo["id"]]["is_hero"] is False


def test_photos_ordered_by_cook_date_hero_stays_in_place(kitchen):
    # Finalized order: cook-linked NEWEST cook first, undated last. The hero is NOT floated — it wears the
    # badge in its natural cooked_on position.
    a = kitchen.client
    rid = _own_recipe(a, "Order Dish")
    old = _post_photo(a, rid, cook_log_id=_log_cook(a, rid, "2023-01-05"))   # older cook; first attach -> auto-hero
    new = _post_photo(a, rid, cook_log_id=_log_cook(a, rid, "2024-06-20"))   # newer cook
    solo = _post_photo(a, rid)                                               # standalone (no date) -> last

    photos = _photos(a, rid)
    assert [p["id"] for p in photos] == [new["id"], old["id"], solo["id"]]   # newest cook, older cook, then undated
    by_id = {p["id"]: p for p in photos}
    assert by_id[old["id"]]["is_hero"] is True                               # the hero wears the badge...
    assert photos[0]["id"] == new["id"]                                      # ...but does NOT float to the top


def test_photos_recency_when_no_cook_photo_is_hero(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Recency Dish")
    _upload_hero(a, rid)                                      # a NORMAL hero -> cook-photo attaches don't auto-promote
    p1 = _post_photo(a, rid)
    p2 = _post_photo(a, rid)
    p3 = _post_photo(a, rid)

    photos = _photos(a, rid)
    assert [p["id"] for p in photos] == [p3["id"], p2["id"], p1["id"]]   # pure most-recently-added order
    assert all(p["is_hero"] is False for p in photos)        # the hero is the normal image, not a cook photo
