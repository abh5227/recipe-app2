"""Bulk "Delete all test recipes" (delete_test_recipes) FILE cleanup — the 2c gather+unlink that its
sibling delete_recipe has but this endpoint was MISSING: the DB cascade removed the cook_photos/hero ROWS
but the endpoint never unlinked the FILES, so every bulk-deleted test recipe orphaned its images on disk.
Pins the fix + its copy-share guard:
  - a test recipe's cook-photo file is unlinked on bulk-delete,
  - a test recipe's own (unshared) hero file is unlinked,
  - BUT a hero SHARED with a surviving APP recipe (copy carries the image path) is NOT unlinked.
Disk isolated to the temp images dir (harness rebinds images.IMAGES_DIR); recipes.db hidden in CI."""
import io

from PIL import Image

import images


def _img():
    buf = io.BytesIO(); Image.new("RGB", (60, 60), "red").save(buf, format="JPEG"); return buf.getvalue()


def _mk(client, name, is_test=False):
    body = {"name": name, "ingredients": [], "steps": []}
    if is_test:
        body["is_test"] = True
    return client.post("/api/recipes", json=body).get_json()["id"]


def _attach_photo(client, rid):
    return client.post(f"/api/recipes/{rid}/photos",
                       data={"image": (io.BytesIO(_img()), "p.jpg")},
                       content_type="multipart/form-data").get_json()


def _upload_hero(client, rid):
    client.post(f"/api/recipes/{rid}/image",
                data={"image": (io.BytesIO(_img()), "h.jpg")},
                content_type="multipart/form-data")


def _hero_path(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT image FROM recipes WHERE id = ?", (rid,)).fetchone()[0]


def _disk(path):
    return images.IMAGES_DIR / path[len("images/"):]


def test_bulk_delete_unlinks_test_cook_photo_file(kitchen):
    a = kitchen.client
    t = _mk(a, "Scratch Photo", is_test=True)
    photo = _attach_photo(a, t)
    assert _disk(photo["path"]).exists()                         # the file is on disk before the delete

    assert a.delete("/api/test-recipes").status_code == 200

    assert kitchen.count("cook_photos", f"recipe_id='{t}'") == 0  # row cascaded (as before)
    assert not _disk(photo["path"]).exists()                     # AND the file is unlinked (the fix)


def test_bulk_delete_unlinks_unshared_test_hero(kitchen):
    a = kitchen.client
    t = _mk(a, "Scratch Hero", is_test=True)
    _upload_hero(a, t)
    hpath = _hero_path(kitchen, t)
    assert hpath and _disk(hpath).exists()

    a.delete("/api/test-recipes")

    assert not _disk(hpath).exists()                             # an unshared test hero is unlinked (no orphan)


def test_bulk_delete_preserves_hero_shared_with_surviving_app_recipe(kitchen):
    a = kitchen.client
    keeper = _mk(a, "Keeper", is_test=False)                     # a surviving APP recipe
    _upload_hero(a, keeper)
    shared = _hero_path(kitchen, keeper)
    assert _disk(shared).exists()

    # copy the app recipe AS TEST — copy_recipe carries the image PATH, so both point at the SAME file
    t = a.post(f"/api/recipes/{keeper}/copy", json={"is_test": True}).get_json()["id"]
    assert _hero_path(kitchen, t) == shared                      # shared path, one file on disk

    a.delete("/api/test-recipes")                                # removes the test copy only

    assert a.get(f"/api/recipes/{t}").status_code == 404         # the test copy is gone
    assert _disk(shared).exists()                                # BUT the surviving app recipe still uses the file
    assert _hero_path(kitchen, keeper) == shared                 # -> the copy-share guard kept it (not over-deleted)
