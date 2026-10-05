"""DELETE /api/test-recipes, and the Browse header that offers it, cover the caller's own rows only.

⚠️ WHY THIS FILE EXISTS. The route matched source='test' with no owner clause, and copy_recipe
stamps every copy with owner=current_user.id. So any logged-in account could wipe any other
account's test copies, and the Browse header told them how many there were to wipe: its count came
from GET /api/recipes, which is deliberately not owner-filtered, so B saw "Delete 1 test recipe"
because A had made one. Measured on live at the time: 4 accounts, one of them the real one.

⚠️ THE FILE SWEEP IS THE HALF THAT WOULD HAVE BEEN WORSE. Gathering every test recipe's photos and
then deleting only your own unlinks another account's hero while its recipe row survives, which is a
live row pointing at a file that is gone. Both the gather and the delete read one scoped set.
"""
import io

from PIL import Image

import harness
import images


def _img():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(buf, format="JPEG")
    return buf.getvalue()


def _second_client(kitchen, email="other@test.local"):
    """A second logged-in account against the SAME database, the way the harness makes the first."""
    import app
    uid = harness.ensure_test_user(email=email)
    client = app.app.test_client()                    # a fresh cookie jar, so the two do not share
    harness.login_test_client(client, uid)
    return client, uid


def _mk_test(client, name):
    r = client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": [],
                                          "is_test": True})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["id"]


def _my_test_count(client):
    """What the Browse header counts, computed the way static/app.js computes it.

    ⚠️ is_mine, NOT owner. list_recipes pops the raw owner id and sends the boolean instead, so a
    count written against r.owner is a flat zero on every row. Caught by this test."""
    rows = client.get("/api/recipes").get_json()
    assert all("owner" not in r for r in rows), \
        "the raw owner id is exposed now, so the least-exposure comment in list_recipes is stale"
    return len([r for r in rows if r["source"] == "test" and r["is_mine"]])


# ---- B cannot delete A's test copies -------------------------------------------------------------

def test_another_account_cannot_delete_my_test_recipes(kitchen):
    """⚠️ THE DEFECT, STATED DIRECTLY. B's delete used to take A's rows with it."""
    a = kitchen.client
    mine = _mk_test(a, "Andy's scratch")
    b, _ = _second_client(kitchen)

    assert b.delete("/api/test-recipes").get_json()["deleted"] == 0, \
        "B deleted rows it does not own"
    assert a.get(f"/api/recipes/{mine}").status_code == 200, "A's test recipe survives B's delete"
    assert kitchen.count("recipes", f"id='{mine}'") == 1


def test_each_account_deletes_only_its_own_and_the_other_is_untouched(kitchen):
    a = kitchen.client
    b, _ = _second_client(kitchen)
    a_rid = _mk_test(a, "A scratch")
    b_rid = _mk_test(b, "B scratch")

    assert b.delete("/api/test-recipes").get_json()["deleted"] == 1
    assert kitchen.count("recipes", f"id='{b_rid}'") == 0, "B's own row is gone"
    assert kitchen.count("recipes", f"id='{a_rid}'") == 1, "A's row is not"

    assert a.delete("/api/test-recipes").get_json()["deleted"] == 1
    assert kitchen.count("recipes", f"id='{a_rid}'") == 0, "A's own delete still works"


# ---- A's count excludes B's ----------------------------------------------------------------------

def test_my_count_excludes_another_account_s_test_recipes(kitchen):
    """⚠️ THE BUTTON IS THE OTHER HALF OF THE SAME BUG. A count taken from the unfiltered list told
    one account how many of somebody else's copies were there, and then offered to delete them."""
    a = kitchen.client
    b, _ = _second_client(kitchen)

    _mk_test(b, "B scratch one")
    _mk_test(b, "B scratch two")

    assert _my_test_count(a) == 0, "A's header counts none of B's two"
    assert _my_test_count(b) == 2

    _mk_test(a, "A scratch")
    assert _my_test_count(a) == 1, "and counts its own"
    assert _my_test_count(b) == 2, "B's count is unaffected by A's"


def test_the_client_computes_the_count_with_the_owner_in_it():
    """The server scoping the delete is half the fix. A count that still included another account's
    rows would promise a delete that no longer happens, so the two have to agree."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "static" / "app.js").read_text()
    line = next(l for l in src.splitlines() if "const testCount" in l or "r.source === \"test\"" in l)
    block = src[src.index("const testCount"):src.index("const testCount") + 160]
    assert "is_mine" in block, \
        f"the Browse-header count is not owner-scoped: {line.strip()}"
    assert "r.owner" not in block, \
        "the count reads r.owner, which list_recipes does not send, so it is a flat zero"


# ---- the file sweep is scoped the same way -------------------------------------------------------

def _hero(client, rid):
    client.post(f"/api/recipes/{rid}/image", data={"image": (io.BytesIO(_img()), "h.jpg")},
                content_type="multipart/form-data")


def _hero_path(kitchen, rid):
    with kitchen.conn() as c:
        return c.execute("SELECT image FROM recipes WHERE id = ?", (rid,)).fetchone()[0]


def _disk(path):
    return images.IMAGES_DIR / path[len("images/"):]


def test_another_account_s_delete_does_not_unlink_my_photo_file(kitchen):
    """⚠️ A LIVE ROW POINTING AT A FILE THAT IS GONE is worse than the cross-owner delete. The
    gather and the delete read ONE scoped set, so B's delete cannot reach A's file.

    ⚠️ THE PHOTO IS DEMOTED FIRST, AND WITHOUT THAT THIS TEST COULD NOT FAIL. The first version
    uploaded one photo and stopped, and POST /photos auto-promotes the first photo to hero, so A's
    surviving recipe carried it in recipes.image and unlink_unreferenced's hero check protected the
    file whatever the sweep had collected. Measured: the assertion passed against the UNSCOPED
    gather it exists to pin. A second hero upload leaves the first path as a plain album photo,
    which is the only state in which the scoping is what saves the file."""
    a = kitchen.client
    mine = _mk_test(a, "A with a photo")
    photo = a.post(f"/api/recipes/{mine}/photos",
                   data={"image": (io.BytesIO(_img()), "p.jpg")},
                   content_type="multipart/form-data").get_json()
    _hero(a, mine)                                     # a NEW hero, so the first path is album-only
    assert _hero_path(kitchen, mine) != photo["path"], "the photo is still the hero, so this is vacuous"
    assert _disk(photo["path"]).exists()

    b, _ = _second_client(kitchen)
    assert b.delete("/api/test-recipes").get_json()["deleted"] == 0

    assert _disk(photo["path"]).exists(), "B's delete unlinked A's photo file"
    assert kitchen.count("cook_photos", f"recipe_id='{mine}'") == 2, "and left the rows alone"


def test_a_surviving_album_row_keeps_its_file_when_a_shared_copy_is_deleted(kitchen):
    """⚠️ TWO COLUMNS NAME A FILE AND THE GUARD ASKED ONE. unlink_unreferenced checked
    recipes.image only, so a surviving cook_photos row was invisible to it. The hero-upload route is
    what makes the two diverge: it writes BOTH, and a replacement hero leaves the old path as a
    plain album photo. Reproduced through the API, with a 200 and no sign anything happened.

    A owns a recipe and uploads hero P. B copies it AS TEST, and copy_recipe carries the image path,
    so B's row points at P too. A uploads a new hero, so P is now only an album photo of A's. B
    deletes its test recipes, which gathers P. P must survive, because A's album row still names it.
    """
    a = kitchen.client
    keeper = a.post("/api/recipes", json={"name": "A Keeper", "ingredients": [],
                                          "steps": []}).get_json()["id"]
    _hero(a, keeper)
    P = _hero_path(kitchen, keeper)
    assert P and _disk(P).exists()

    b, _ = _second_client(kitchen)
    copy = b.post(f"/api/recipes/{keeper}/copy", json={"is_test": True}).get_json()["id"]
    assert _hero_path(kitchen, copy) == P, "the copy must share the path for this to be the case"

    _hero(a, keeper)                                   # a replacement hero: P becomes album-only
    assert _hero_path(kitchen, keeper) != P
    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM cook_photos WHERE path = ?", (P,)).fetchone()[0] >= 1

    assert b.delete("/api/test-recipes").get_json()["deleted"] == 1

    assert _disk(P).exists(), \
        "a file A's surviving album row still points at was unlinked by B's delete"
    with kitchen.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM cook_photos WHERE path = ?", (P,)).fetchone()[0] >= 1


def test_the_same_loss_with_one_account_is_closed_too(kitchen):
    """All three callers share unlink_unreferenced, so the single-account spelling was broken the
    same way. Named so the fix is not mistaken for a cross-owner special case."""
    a = kitchen.client
    keeper = a.post("/api/recipes", json={"name": "Keeper", "ingredients": [],
                                          "steps": []}).get_json()["id"]
    _hero(a, keeper)
    P = _hero_path(kitchen, keeper)
    a.post(f"/api/recipes/{keeper}/copy", json={"is_test": True})
    _hero(a, keeper)                                   # P is now album-only on the app recipe
    assert a.delete("/api/test-recipes").get_json()["deleted"] == 1
    assert _disk(P).exists(), "the owner's own test-delete unlinked their own album photo"


def test_my_own_delete_still_unlinks_my_photo_file(kitchen):
    """The scoping must not have turned the cleanup off. Its own tests cover the rest."""
    a = kitchen.client
    mine = _mk_test(a, "A with a photo")
    photo = a.post(f"/api/recipes/{mine}/photos",
                   data={"image": (io.BytesIO(_img()), "p.jpg")},
                   content_type="multipart/form-data").get_json()
    on_disk = images.IMAGES_DIR / photo["path"][len("images/"):]
    assert on_disk.exists()

    assert a.delete("/api/test-recipes").get_json()["deleted"] == 1
    assert not on_disk.exists(), "the owner's own bulk delete no longer cleans up its files"


# ---- and an app-tier recipe is still never touched -----------------------------------------------

def test_the_bulk_delete_still_refuses_to_touch_an_app_recipe(kitchen):
    """The tier gate is unchanged. Owner scoping narrows the set, it does not widen it."""
    a = kitchen.client
    keeper = a.post("/api/recipes", json={"name": "Keeper", "ingredients": [],
                                          "steps": []}).get_json()["id"]
    scratch = _mk_test(a, "Scratch")
    assert a.delete("/api/test-recipes").get_json()["deleted"] == 1
    assert kitchen.count("recipes", f"id='{keeper}'") == 1
    assert kitchen.count("recipes", f"id='{scratch}'") == 0
