"""Cook-photo album DISPLAY data (Stage 4 build 3a): the `photos` array folded into GET /api/recipes/<id>.
Proves the read the album renders from — per-photo shape (least-exposure), stored-position (append) order
(3d-i), the cook's date present for cook-linked / absent for standalone, and is_hero (recipes.image == path).
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


def test_photos_ordered_by_stored_position_append(kitchen):
    # 3d-i: the album orders by STORED position, and new photos APPEND (max+1) — so photos show in ATTACH
    # order, NOT cooked_on order. (cooked_on still governs each photo's displayed DATE, independently.)
    a = kitchen.client
    rid = _own_recipe(a, "Order Dish")
    first = _post_photo(a, rid, cook_log_id=_log_cook(a, rid, "2023-01-05"))   # OLDER cook, attached 1st -> pos 0 (auto-hero)
    second = _post_photo(a, rid, cook_log_id=_log_cook(a, rid, "2024-06-20"))  # NEWER cook, attached 2nd -> pos 1
    solo = _post_photo(a, rid)                                                 # standalone, attached 3rd -> pos 2

    photos = _photos(a, rid)
    # append order (pos 0,1,2) DIFFERS from cooked_on-desc ([second, first, solo]) -> proves it's position-ordered
    assert [p["id"] for p in photos] == [first["id"], second["id"], solo["id"]]
    by_id = {p["id"]: p for p in photos}
    assert by_id[first["id"]]["is_hero"] is True                               # the hero wears the badge in its position (0)
    assert by_id[first["id"]]["cooked_on"] == "2023-01-05"                     # date still from cooked_on...
    assert by_id[second["id"]]["cooked_on"] == "2024-06-20"                    # ...independent of the position order
    assert by_id[solo["id"]]["cooked_on"] is None


def test_uploaded_hero_is_an_album_photo_and_appends_in_order(kitchen):
    # Hero↔album unification: an uploaded hero is ITSELF an album photo (is_hero=True), at album position 0;
    # subsequent cook-photo attaches append after it and are NOT the hero. ("a photo is a photo.")
    a = kitchen.client
    rid = _own_recipe(a, "Recency Dish")
    _upload_hero(a, rid)                                      # now creates a cook-less album row + promotes it
    p1 = _post_photo(a, rid)
    p2 = _post_photo(a, rid)
    p3 = _post_photo(a, rid)

    photos = _photos(a, rid)
    assert [p["id"] for p in photos[1:]] == [p1["id"], p2["id"], p3["id"]]   # attaches append after the hero (positions 1,2,3)
    assert photos[0]["is_hero"] is True                      # the uploaded hero IS the album's first photo
    assert all(p["is_hero"] is False for p in photos[1:])    # the later attaches are not the hero
    assert len(photos) == 4                                  # hero + 3 attaches
