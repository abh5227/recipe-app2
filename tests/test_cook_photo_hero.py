"""Cook-photo POINT/linked-hero behavior (Stage 4 build 2c): promote-to-hero, auto-promote-if-none (with
the no-hijack guard), and the linked-hero CLEAR + file cleanup on ALL THREE removal paths — explicit
delete, undo_cook cascade, and delete_recipe cascade — plus the hero-orphan fix. This is the crux of the
album backend; the linked-hero clear is tested hard. Endpoints hit directly; disk isolated to the temp
images dir (harness rebinds images.IMAGES_DIR); recipes.db hidden in CI."""
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


def _own_recipe(client, name="Hero Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _img_bytes(size=(70, 70)):
    buf = io.BytesIO(); Image.new("RGB", size, "red").save(buf, format="JPEG"); return buf.getvalue()


def _log_cook(client, rid):
    return client.post(f"/api/recipes/{rid}/cooked", json={}).get_json()["cook_log_id"]


def _post_photo(client, rid, cook_log_id=None):
    data = {"image": (io.BytesIO(_img_bytes()), "p.jpg")}
    if cook_log_id is not None:
        data["cook_log_id"] = str(cook_log_id)
    return client.post(f"/api/recipes/{rid}/photos", data=data, content_type="multipart/form-data").get_json()


def _upload_hero(client, rid):
    return client.post(f"/api/recipes/{rid}/image",
                       data={"image": (io.BytesIO(_img_bytes()), "hero.jpg")},
                       content_type="multipart/form-data")


def _hero(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT image FROM recipes WHERE id = ?", (rid,)).fetchone()[0]


def _rows(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT * FROM cook_photos WHERE recipe_id = ?", (rid,)).fetchall()


def _on_disk(path):
    return images.IMAGES_DIR / path[len("images/"):]


def _cook_files():
    d = images.IMAGES_DIR / "cooks"
    return list(d.glob("*.jpg")) if d.is_dir() else []


# ---- PROMOTE ------------------------------------------------------------------------------------

def test_promote_sets_and_updates_hero(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    first = _post_photo(a, rid)                              # auto-hero (no hero yet) -> hero = first
    assert _hero(kitchen, rid) == first["path"]
    second = _post_photo(a, rid)                            # hero exists now -> not auto-promoted
    assert _hero(kitchen, rid) == first["path"]
    r = a.post(f"/api/photos/{second['id']}/promote")       # explicit promote -> hero updates to second
    assert r.status_code == 200 and r.get_json()["image"] == second["path"]
    assert _hero(kitchen, rid) == second["path"]            # POINT/linked to the cook photo's own path


def test_promote_non_recipe_owner_403(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "A's Recipe")                      # A owns the recipe
    _bid, b = _user_client("hero-b@test.local")
    clid_b = _log_cook(b, rid)                              # B cooks A's recipe -> B's cook
    photo = _post_photo(b, rid, cook_log_id=clid_b)        # B's photo on B's cook (allowed)
    r = b.post(f"/api/photos/{photo['id']}/promote")       # B promotes -> writes A's recipes.image -> 403
    assert r.status_code == 403
    assert _hero(kitchen, rid) is None                      # A's hero untouched


def test_promote_missing_photo_404(kitchen):
    assert kitchen.client.post("/api/photos/999999/promote").status_code == 404


# ---- AUTO-PROMOTE (with the no-hijack guard) ----------------------------------------------------

def test_auto_promote_when_no_hero(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    body = _post_photo(a, rid)                              # standalone attach, no hero yet
    assert body["is_hero"] is True
    assert _hero(kitchen, rid) == body["path"]


def test_no_auto_promote_when_hero_exists(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    assert _upload_hero(a, rid).status_code == 200          # a normal hero already set
    before = _hero(kitchen, rid)
    body = _post_photo(a, rid)                              # attach -> must NOT overwrite the existing hero
    assert body["is_hero"] is False
    assert _hero(kitchen, rid) == before


def test_no_hijack_auto_promote_on_unowned_recipe(kitchen):
    # A owns a hero-less recipe; B cooks it and attaches a photo to B's cook -> must NOT set A's hero.
    a = kitchen.client
    rid = _own_recipe(a, "A's Heroless Recipe")
    _bid, b = _user_client("hero-hijack-b@test.local")
    clid_b = _log_cook(b, rid)
    body = _post_photo(b, rid, cook_log_id=clid_b)
    assert body["is_hero"] is False                         # no hijack
    assert _hero(kitchen, rid) is None                      # A's empty hero stays empty


# ---- EXPLICIT-DELETE hero-clear (the load-bearing test) -----------------------------------------

def test_delete_hero_photo_clears_hero_and_file(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    photo = _post_photo(a, rid)                             # auto-hero
    assert _hero(kitchen, rid) == photo["path"]
    r = a.delete(f"/api/photos/{photo['id']}")
    assert r.status_code == 200
    assert _hero(kitchen, rid) is None                      # hero CLEARED (it pointed at this photo)
    assert not _on_disk(photo["path"]).exists()            # file gone
    assert _rows(kitchen, rid) == []                        # row gone


def test_delete_non_hero_photo_leaves_hero_intact(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    hero_photo = _post_photo(a, rid)                        # auto-hero = A
    other = _post_photo(a, rid)                             # B (not the hero)
    assert _hero(kitchen, rid) == hero_photo["path"]
    r = a.delete(f"/api/photos/{other['id']}")             # delete the NON-hero photo
    assert r.status_code == 200
    assert _hero(kitchen, rid) == hero_photo["path"]       # hero UNTOUCHED
    assert _on_disk(hero_photo["path"]).exists()           # hero file intact


# ---- CASCADE via undo_cook ----------------------------------------------------------------------

def test_undo_cook_clears_hero_and_unlinks_photo(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    clid = _log_cook(a, rid)
    photo = _post_photo(a, rid, cook_log_id=clid)          # attached to the cook + auto-hero
    assert _hero(kitchen, rid) == photo["path"]
    a.post(f"/api/recipes/{rid}/uncook")                   # undo the cook -> cascade removes the photo row
    assert _rows(kitchen, rid) == []                        # cook_photos row cascade-gone
    assert not _on_disk(photo["path"]).exists()            # file unlinked (app-level, after cascade)
    assert _hero(kitchen, rid) is None                      # surviving recipe's hero CLEARED


def test_undo_cook_non_hero_photo_unlinks_but_hero_untouched(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    assert _upload_hero(a, rid).status_code == 200          # a normal hero (not a cook photo)
    hero_before = _hero(kitchen, rid)
    clid = _log_cook(a, rid)
    photo = _post_photo(a, rid, cook_log_id=clid)          # hero exists -> not the hero
    a.post(f"/api/recipes/{rid}/uncook")
    # the COOK's photo cascades on undo; the uploaded hero's row is COOK-LESS (cook_log_id NULL) -> it SURVIVES.
    surviving = _rows(kitchen, rid)
    assert [row["path"] for row in surviving] == [hero_before]   # only the cook-less hero row remains
    assert not _on_disk(photo["path"]).exists()            # the cook photo's file unlinked
    assert _hero(kitchen, rid) == hero_before               # hero untouched
    assert _on_disk(hero_before).exists()                   # hero file intact


# ---- CASCADE via delete_recipe (+ hero-orphan fix) ----------------------------------------------

def test_delete_recipe_unlinks_all_cook_photo_files(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    clid = _log_cook(a, rid)
    p1 = _post_photo(a, rid, cook_log_id=clid)             # auto-hero
    p2 = _post_photo(a, rid)                               # another album photo
    a.post(f"/api/photos/{p2['id']}/promote")             # move hero to p2
    files = [_on_disk(p1["path"]), _on_disk(p2["path"])]
    assert all(f.exists() for f in files)
    r = a.delete(f"/api/recipes/{rid}")
    assert r.status_code == 200
    assert _rows(kitchen, rid) == []                        # rows cascade-gone
    assert not any(f.exists() for f in files)              # ALL cook-photo files unlinked
    assert _cook_files() == []                              # no orphans left in images/cooks


def test_delete_recipe_unlinks_legacy_slugflat_hero_orphan_fix(kitchen):
    # HERO-ORPHAN FIX (legacy path): an IMPORTED/legacy hero is a slug-flat images/<slug>.jpg with NO
    # cook_photos row (uploads now make uuid cook-photos instead — see test_upload_image). delete_recipe
    # still appends recipes.image's own file to the unlink list, so a legacy hero isn't orphaned on disk.
    a = kitchen.client
    rid = _own_recipe(a)
    hero_path = images.save_image(_img_bytes(), slug=rid)  # the legacy slug-flat hero shape, no cook_photos row
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET image = ? WHERE id = ?", (hero_path, rid))
        c.commit()
    hero_file = _on_disk(hero_path)
    assert hero_file.exists()
    assert _rows(kitchen, rid) == []                        # no cook_photos row — the genuine orphan case
    assert a.delete(f"/api/recipes/{rid}").status_code == 200
    assert not hero_file.exists()                           # orphan-fix unlinked recipes.image's own file


def test_delete_recipe_keeps_file_a_copy_still_shares(kitchen):
    # copy_recipe carries the image PATH, so a copy's hero can point at the original's file. Deleting the
    # ORIGINAL must NOT unlink a file the copy still uses (the unlink_unreferenced guard).
    a = kitchen.client
    rid = _own_recipe(a)
    photo = _post_photo(a, rid)                            # auto-hero = a cook photo
    shared = _on_disk(photo["path"])
    copy_id = a.post(f"/api/recipes/{rid}/copy").get_json()["id"]   # copy carries recipes.image = photo path
    assert _hero(kitchen, copy_id) == photo["path"]        # copy shares the file
    a.delete(f"/api/recipes/{rid}")                        # delete the ORIGINAL
    assert shared.exists()                                  # file kept — the copy still references it
