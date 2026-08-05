"""Photo upload endpoint (Stage 2): POST /api/recipes/<id>/image — owner-checked multipart upload that
resizes + strips metadata + stores via the images.save_cook_photo seam. Hits the endpoint directly (no
browser). Disk writes are isolated to the kitchen's temp images dir (harness rebinds images.IMAGES_DIR).

Hero↔album unification: an uploaded hero is stored uuid-unique ('images/cooks/<uuid>.jpg', like an album
photo), inserted as a COOK-LESS cook_photos row, AND promoted to the hero — so it appears in the album,
and replacing it leaves the previous hero as a plain album photo. These tests read the SERVER-minted path
from the response (no longer the predictable slug-flat 'images/<rid>.jpg')."""
import io
from pathlib import Path

import pytest
from PIL import Image

import app
import images
import harness

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _user_client(email):
    uid = harness.ensure_test_user(email=email)
    c = app.app.test_client()
    harness.login_test_client(c, uid)
    return uid, c


def _own_recipe(client, name="Photo Dish"):
    return client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": []}).get_json()["id"]


def _img_bytes(size=(50, 50), fmt="JPEG", mode="RGB", exif_gps=False):
    im = Image.new(mode, size, "red")
    buf = io.BytesIO()
    if exif_gps:
        ex = im.getexif(); ex[34853] = {2: (1, 2, 3)}   # 34853 = GPSInfo IFD
        im.save(buf, format="JPEG", exif=ex)
    else:
        im.save(buf, format=fmt)
    return buf.getvalue()


def _post(client, rid, data_bytes, filename="photo.jpg", field="image"):
    return client.post(f"/api/recipes/{rid}/image",
                       data={field: (io.BytesIO(data_bytes), filename)},
                       content_type="multipart/form-data")


def _db_image(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT image FROM recipes WHERE id = ?", (rid,)).fetchone()[0]


def _disk(path):
    """A stored DB path ('images/cooks/<uuid>.jpg') -> the file under the temp images dir."""
    return images.IMAGES_DIR / path[len("images/"):]


def _cook_photos(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute(
            "SELECT id, cook_log_id, user_id, path, position FROM cook_photos WHERE recipe_id = ? "
            "ORDER BY position, id", (rid,),
        ).fetchall()


# ---- happy path ---------------------------------------------------------------------------------

def test_owner_upload_success(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, _img_bytes())
    assert r.status_code == 200
    body = r.get_json()
    assert list(body) == ["image"]                         # least-exposure: ONLY the path
    path = body["image"]
    assert path.startswith("images/cooks/") and path.endswith(".jpg")   # uuid-unique, like album photos
    assert _db_image(kitchen, rid) == path                 # DB hero updated (promoted)
    assert _disk(path).exists()                            # file in the (temp) images dir
    # "a photo is a photo": the uploaded hero is ALSO a cook-less album row (is_hero derives via recipes.image)
    rows = _cook_photos(kitchen, rid)
    assert len(rows) == 1
    assert rows[0]["cook_log_id"] is None                  # cook-less (a direct hero upload, no cook)
    assert rows[0]["path"] == path and rows[0]["position"] == 0


def test_replace_hero_keeps_old_as_album_photo(kitchen):
    # "a photo is a photo": replacing the hero (a 2nd upload) leaves the FIRST as a plain album photo —
    # its row + file stay, it just stops matching recipes.image; the new one is the hero.
    a = kitchen.client
    rid = _own_recipe(a)
    first = _post(a, rid, _img_bytes()).get_json()["image"]
    second = _post(a, rid, _img_bytes()).get_json()["image"]
    assert first != second                                 # uuid-unique -> distinct files/rows
    assert _db_image(kitchen, rid) == second               # the NEW one is the hero
    rows = _cook_photos(kitchen, rid)
    assert [r["path"] for r in rows] == [first, second]    # BOTH rows survive, in append order (position 0,1)
    assert _disk(first).exists() and _disk(second).exists()   # nothing deleted


# ---- authorization (security-critical) ----------------------------------------------------------

def test_non_owner_403_no_write(kitchen):
    a = kitchen.client
    rid = _own_recipe(a, "A's Dish")
    before = _db_image(kitchen, rid)
    _bid, b = _user_client("upload-b@test.local")
    r = _post(b, rid, _img_bytes())
    assert r.status_code == 403
    assert _db_image(kitchen, rid) == before               # DB UNCHANGED — a 403 that wrote would be a vuln
    assert not (images.IMAGES_DIR / f"{rid}.jpg").exists()  # nothing written


def test_unauthenticated_gated(kitchen_logged_out):
    c = kitchen_logged_out.client
    assert c.post("/api/recipes/whatever/image").status_code == 401


def test_missing_recipe_404(kitchen):
    assert _post(kitchen.client, "no-such-recipe", _img_bytes()).status_code == 404


# ---- input validation ---------------------------------------------------------------------------

def test_non_image_bytes_400_no_write(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    before = _db_image(kitchen, rid)
    r = _post(a, rid, b"not an image at all")
    assert r.status_code == 400
    assert _db_image(kitchen, rid) == before
    assert not (images.IMAGES_DIR / f"{rid}.jpg").exists()


def test_missing_file_part_400(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = a.post(f"/api/recipes/{rid}/image", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_disallowed_format_400(kitchen):        # S3: Pillow decodes BMP, but it's not in the allowlist
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, _img_bytes(fmt="BMP"), filename="x.bmp")
    assert r.status_code == 400
    assert not (images.IMAGES_DIR / f"{rid}.jpg").exists()


# ---- S1 path traversal: TWO distinct guarantees -------------------------------------------------

def test_client_filename_is_ignored(kitchen):
    # Proves the CLIENT filename is never used: a traversal filename is harmless because the stored
    # name derives from rec.id. (This does NOT exercise the is_relative_to guard — see the next test.)
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, _img_bytes(), filename="../../evil.jpg")
    assert r.status_code == 200
    assert _disk(r.get_json()["image"]).exists()                             # stored under a server uuid
    assert not (images.IMAGES_DIR.parent.parent / "evil.jpg").exists()       # nothing escaped the dir


def test_save_image_containment_guard_rejects_escaping_slug():
    # Exercises the SECURITY-LOAD-BEARING is_relative_to check directly: a slug that resolves OUTSIDE
    # IMAGES_DIR must raise and write nothing. This is what keeps "name = rec.id" safe regardless of
    # what recipe-id formats are or ever become (defense that actually fires).
    escaping = "../../evil"
    with pytest.raises(images.ImageValidationError):
        images.save_image(_img_bytes(), slug=escaping)
    assert not (images.IMAGES_DIR.parent.parent / "evil.jpg").exists()       # guard fired before any write


# ---- S4 EXIF/GPS stripping ----------------------------------------------------------------------

def test_exif_gps_stripped(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, _img_bytes(exif_gps=True))
    assert r.status_code == 200
    saved = Image.open(_disk(r.get_json()["image"]))
    exif = saved.getexif()
    assert 34853 not in exif and len(dict(exif)) == 0        # no GPS, no EXIF at all


# ---- S2 decompression bomb (guard path, cheaply) ------------------------------------------------

def test_decompression_bomb_400(kitchen, monkeypatch):
    a = kitchen.client
    rid = _own_recipe(a)
    monkeypatch.setattr(images.Image, "MAX_IMAGE_PIXELS", 10)  # 100x100 = 10_000 px >> 2*10 -> bomb
    r = _post(a, rid, _img_bytes(size=(100, 100)))
    assert r.status_code == 400
    assert _cook_photos(kitchen, rid) == []                 # nothing inserted on validation failure
    assert _db_image(kitchen, rid) is None                  # hero not set either


# ---- HEIC/HEIF input (iPhone/Photos) ------------------------------------------------------------

def _heic_bytes(size=(1600, 1200), gps=False):
    im = Image.new("RGB", size, "red")
    buf = io.BytesIO()
    if gps:
        ex = im.getexif(); ex[34853] = {2: (1, 2, 3)}   # 34853 = GPSInfo IFD
        im.save(buf, format="HEIF", exif=ex)
    else:
        im.save(buf, format="HEIF")
    return buf.getvalue()


def test_owner_heic_upload_success_stored_as_jpeg(kitchen):
    # iPhone/Photos HEIC now accepted (allowlist includes HEIF); the SAME pipeline stores a JPEG under
    # the server slug — HEIC is input-only, output stays JPEG.
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, _heic_bytes(), filename="IMG_1234.heic")
    assert r.status_code == 200
    path = r.get_json()["image"]
    assert path.startswith("images/cooks/") and path.endswith(".jpg")   # uuid-unique, input HEIC -> JPEG out
    assert _db_image(kitchen, rid) == path
    saved = _disk(path)
    assert saved.exists()
    assert Image.open(saved).format == "JPEG"           # decoded HEIC re-encoded to JPEG on disk


def test_heic_exif_gps_stripped(kitchen):
    # HEIC carries GPS too — the existing strip must still yield a metadata-free JPEG from HEIC input.
    a = kitchen.client
    rid = _own_recipe(a)
    src = _heic_bytes(gps=True)
    assert 34853 in Image.open(io.BytesIO(src)).getexif()   # precondition: the source really has GPS
    r = _post(a, rid, src, filename="IMG_1234.heic")
    assert r.status_code == 200
    exif = Image.open(_disk(r.get_json()["image"])).getexif()
    assert 34853 not in exif and len(dict(exif)) == 0


def test_real_iphone_heic_upload_success(kitchen):
    # Regression against a REAL iPhone HEIC (HEVC-encoded, 3024x4032, real device EXIF) — the synthetic
    # HEIF fixtures prove the decode/re-encode plumbing; this proves real-device quirks flow through the
    # same pipeline to a downscaled, metadata-free JPEG.
    fixture = FIXTURES / "IMG_5424.heic"
    assert fixture.exists(), "committed real-HEIC fixture missing"
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, fixture.read_bytes(), filename="IMG_5424.heic")
    assert r.status_code == 200
    saved = _disk(r.get_json()["image"])
    assert saved.exists()
    out = Image.open(saved)
    assert out.format == "JPEG" and max(out.size) == 1600     # 12 MP downscaled to long-edge 1600
    assert len(dict(out.getexif())) == 0                       # all real EXIF stripped


# ---- S7 wire-size cap ---------------------------------------------------------------------------

def test_oversize_rejected_413(kitchen):
    a = kitchen.client
    rid = _own_recipe(a)
    r = _post(a, rid, b"\0" * (11 * 1024 * 1024))            # > MAX_CONTENT_LENGTH (10 MB)
    assert r.status_code == 413
    assert _cook_photos(kitchen, rid) == []                 # nothing inserted (rejected at the wire cap)
