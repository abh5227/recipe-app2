"""Cook-photo album endpoints (Stage 4 build 2b): attach / caption / delete over the cook_photos table,
plus log_cook returning the new cook_log_id. Hits the endpoints directly (no browser). Disk writes are
isolated to the kitchen's temp images dir (harness rebinds images.IMAGES_DIR). Reuses the 2a seams
(save_cook_photo/delete_image) via the endpoints — the file/validation behavior itself is proven in
test_images.py; here we prove the ROUTING, GATING, and DB effects.

Owner-split gating under test: attach-to-a-cook = cook-owner; attach-standalone = recipe-owner;
caption/delete = photo-owner. NO promote/hero logic exists yet (that's 2c)."""
import io

from PIL import Image

import app
import images
import harness


def _user_client(email):
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _own_recipe(client, name="Album Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _img_bytes(size=(60, 60), fmt="JPEG", exif_orientation=None):
    im = Image.new("RGB", size, "red")
    buf = io.BytesIO()
    if exif_orientation is not None:
        ex = im.getexif(); ex[274] = exif_orientation
        im.save(buf, format="JPEG", exif=ex)
    else:
        im.save(buf, format=fmt)
    return buf.getvalue()


def _log_cook(client, rid, date=None):
    body = {"date": date} if date else {}
    return client.post(f"/api/recipes/{rid}/cooked", json=body).get_json()


def _post_photo(client, rid, img=None, cook_log_id=None, caption=None, filename="cook.jpg"):
    data = {"image": (io.BytesIO(img if img is not None else _img_bytes()), filename)}
    if cook_log_id is not None:
        data["cook_log_id"] = str(cook_log_id)
    if caption is not None:
        data["caption"] = caption
    return client.post(f"/api/recipes/{rid}/photos", data=data, content_type="multipart/form-data")


def _rows(kitchen, rid=None):
    with kitchen.conn() as c:
        sql = "SELECT * FROM cook_photos" + (" WHERE recipe_id = ?" if rid else "")
        return c.execute(sql, (rid,) if rid else ()).fetchall()


def _on_disk(path):
    return images.IMAGES_DIR / path[len("images/"):]


# ---- log_cook returns the new cook_log_id (the at-log-time attach hook) --------------------------

def test_log_cook_returns_cook_log_id(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    body = _log_cook(a, rid)
    assert isinstance(body["cook_log_id"], int)          # additive: the id the client attaches a photo to
    assert body["cook_count"] == 1                        # existing stats still returned


def test_cooked_and_rated_returns_cook_log_id(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    body = a.post(f"/api/recipes/{rid}/cooked-and-rated", json={"rating": 5}).get_json()
    assert isinstance(body["cook_log_id"], int)
    assert body["rating"] == 5


# ---- ATTACH to a cook ---------------------------------------------------------------------------

def test_attach_to_own_cook_success(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Cook Attach Dish")
    clid = _log_cook(a, rid)["cook_log_id"]
    r = _post_photo(a, rid, cook_log_id=clid, caption="golden")
    assert r.status_code == 201
    body = r.get_json()
    assert body["cook_log_id"] == clid and body["caption"] == "golden"
    assert body["path"].startswith("images/cooks/") and body["path"].endswith(".jpg")
    assert body["cooked_on"]                              # the cook's date is echoed for a cook-linked photo
    rows = _rows(kitchen, rid)
    assert len(rows) == 1 and rows[0]["cook_log_id"] == clid and rows[0]["user_id"]
    saved = _on_disk(body["path"])
    assert saved.exists() and Image.open(saved).format == "JPEG"


# ---- ATTACH standalone (no cook) ----------------------------------------------------------------

def test_attach_standalone_success_null_cook(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Standalone Attach Dish")
    r = _post_photo(a, rid)                               # no cook_log_id
    assert r.status_code == 201
    body = r.get_json()
    assert body["cook_log_id"] is None and body["cooked_on"] is None
    rows = _rows(kitchen, rid)
    assert len(rows) == 1 and rows[0]["cook_log_id"] is None
    assert _on_disk(body["path"]).exists()


# ---- ATTACH gating ------------------------------------------------------------------------------

def test_attach_to_another_users_cook_403_no_write(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "Shared Corpus Dish")           # A owns the recipe
    _bid, b = _user_client("cookphoto-b@test.local")
    clid_b = _log_cook(b, rid)["cook_log_id"]            # B cooks the SAME recipe -> B's cook
    r = _post_photo(a, rid, cook_log_id=clid_b)          # A tries to attach to B's cook
    assert r.status_code == 403
    assert _rows(kitchen, rid) == []                      # nothing written
    assert not any(images.IMAGES_DIR.glob("cooks/*.jpg"))  # no file either


def test_attach_standalone_to_unowned_recipe_403(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "A's Private Dish")
    _bid, b = _user_client("cookphoto-c@test.local")
    r = _post_photo(b, rid)                               # B attaches a standalone photo to A's recipe
    assert r.status_code == 403                           # recipe-owner gate
    assert _rows(kitchen, rid) == []


def test_attach_cook_from_different_recipe_404(kitchen):
    a = kitchen.client
    rid1 = _own_recipe(a, "Recipe One")
    rid2 = _own_recipe(a, "Recipe Two")
    clid2 = _log_cook(a, rid2)["cook_log_id"]            # a cook belonging to recipe TWO
    r = _post_photo(a, rid1, cook_log_id=clid2)          # attached to recipe ONE -> mismatch
    assert r.status_code == 404
    assert _rows(kitchen, rid1) == []


def test_attach_missing_recipe_404(kitchen):
    assert _post_photo(kitchen.client, "no-such-recipe").status_code == 404


def test_attach_requires_auth(kitchen_logged_out):
    assert kitchen_logged_out.client.post("/api/recipes/x/photos").status_code == 401


# ---- ATTACH validation --------------------------------------------------------------------------

def test_attach_non_image_400_no_write(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post_photo(a, rid, img=b"not an image at all")
    assert r.status_code == 400                           # shared _validate via save_cook_photo
    assert _rows(kitchen, rid) == []
    assert not any(images.IMAGES_DIR.glob("cooks/*.jpg"))


def test_attach_missing_file_part_400(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = a.post(f"/api/recipes/{rid}/photos", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_attach_overlength_caption_400(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post_photo(a, rid, caption="x" * 61)            # over the cap (60) -> rejected
    assert r.status_code == 400
    assert _rows(kitchen, rid) == []                      # rejected before any write


# ---- CAPTION edit -------------------------------------------------------------------------------

def _attach(client, rid, **kw):
    return _post_photo(client, rid, **kw).get_json()["id"]


def test_caption_edit_by_owner(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    pid = _attach(a, rid, caption="first")
    r = a.patch(f"/api/photos/{pid}", json={"caption": "revised"})
    assert r.status_code == 200 and r.get_json()["caption"] == "revised"


def test_caption_clear_to_empty_allowed(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    pid = _attach(a, rid, caption="to be cleared")
    r = a.patch(f"/api/photos/{pid}", json={"caption": "   "})   # blank -> cleared
    assert r.status_code == 200 and r.get_json()["caption"] is None


def test_caption_non_owner_403(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    pid = _attach(a, rid, caption="mine")
    _bid, b = _user_client("cookphoto-cap-b@test.local")
    assert b.patch(f"/api/photos/{pid}", json={"caption": "hijack"}).status_code == 403


def test_caption_overlength_400(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    pid = _attach(a, rid)
    assert a.patch(f"/api/photos/{pid}", json={"caption": "x" * 60}).status_code == 200   # at the cap -> OK
    assert a.patch(f"/api/photos/{pid}", json={"caption": "x" * 61}).status_code == 400    # over the cap -> rejected


def test_caption_missing_photo_404(kitchen):
    assert kitchen.client.patch("/api/photos/999999", json={"caption": "x"}).status_code == 404


# ---- DELETE -------------------------------------------------------------------------------------

def test_delete_by_owner_removes_row_and_file(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    body = _post_photo(a, rid).get_json()
    pid, saved = body["id"], _on_disk(body["path"])
    assert saved.exists()
    r = a.delete(f"/api/photos/{pid}")
    assert r.status_code == 200
    assert _rows(kitchen, rid) == []                      # row gone
    assert not saved.exists()                             # file gone (delete_image)


def test_delete_non_owner_403_row_and_file_intact(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    body = _post_photo(a, rid).get_json()
    pid, saved = body["id"], _on_disk(body["path"])
    _bid, b = _user_client("cookphoto-del-b@test.local")
    assert b.delete(f"/api/photos/{pid}").status_code == 403
    assert len(_rows(kitchen, rid)) == 1                  # row intact
    assert saved.exists()                                 # file intact


def test_delete_with_missing_file_still_succeeds(kitchen):
    # delete_image is idempotent: a photo whose file was already removed still deletes cleanly (row gone).
    a = kitchen.client
    rid = _own_recipe(a)
    body = _post_photo(a, rid).get_json()
    pid = body["id"]
    _on_disk(body["path"]).unlink()                       # file vanishes out from under the row
    r = a.delete(f"/api/photos/{pid}")
    assert r.status_code == 200
    assert _rows(kitchen, rid) == []


def test_delete_missing_photo_404(kitchen):
    assert kitchen.client.delete("/api/photos/999999").status_code == 404
