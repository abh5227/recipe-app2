"""U5: the commit route — POST /api/import/commit.

WRITE-THEN-EDIT. The row is created and the client opens it in the editor; the user fixes the import
with the ordinary editing surface. So the things worth pinning here are what LANDS in the database and
what deliberately does NOT: the provenance flag lands, the reason='original' baseline does not — that
one waits for the first save, which is the first content the user has actually approved.

NO NETWORK: url_fetch.fetch is monkeypatched to U0's committed fixtures, exactly as U4's tests do.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest       # noqa: E402

import app          # noqa: E402
import harness      # noqa: E402
import import_write # noqa: E402
import url_fetch    # noqa: E402
import url_image    # noqa: E402

_REAL_IMAGE_FETCH = url_image.fetch_image   # captured before conftest's no_image_network stub

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"
MANIFEST = {r["domain"]: r for r in json.loads((FIXTURES / "manifest.json").read_text())}

TABLES = ("recipes", "recipe_ingredients", "recipe_steps", "ratings", "import_flags",
          "recipe_snapshots")


def fetched(domain, url=None):
    row = MANIFEST[domain]
    return url_fetch.Fetched(url or row["url"], (FIXTURES / row["file"]).read_text(errors="replace"),
                             "text/html", "utf-8")


def stub_fetch(monkeypatch, result, calls=None):
    def fake(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        return result
    monkeypatch.setattr(url_fetch, "fetch", fake)


def counts(kitchen):
    return {t: kitchen.count(t) for t in TABLES}


def commit(kitchen, url):
    return kitchen.client.post("/api/import/commit", json={"url": url})


def rows(kitchen, sql, *args):
    with kitchen.conn() as c:
        return c.execute(sql, args).fetchall()


# --------------------------------------------------------------------------- #
# 1. A successful import, end to end
# --------------------------------------------------------------------------- #
def test_import_writes_the_recipe_and_returns_its_id(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    r = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    assert r.status_code == 201
    body = r.get_json()
    assert body["id"] == body["slug"] == "easy-classic-lasagne"
    assert body["read_by"] == "json-ld"
    assert body["duplicate"] is None

    rec = rows(kitchen, "SELECT * FROM recipes WHERE id = ?", body["id"])[0]
    assert rec["name"] == "Easy classic lasagne"
    assert rec["author"] == "Angela Boggiano"
    assert rec["servings"] == "6"
    assert rec["total_time"] == "1 hr 15 min"
    assert rec["source_url"] == MANIFEST["bbcgoodfood.com"]["url"]
    assert rec["source"] == "app"          # an ordinary owned recipe, not a special tier


def test_import_writes_every_row_the_plan_carried(kitchen, monkeypatch):
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    after = counts(kitchen)
    assert after["recipes"] == before["recipes"] + 1
    assert after["recipe_ingredients"] == before["recipe_ingredients"] + 15
    assert after["recipe_steps"] == before["recipe_steps"] + 5


def test_step_heading_flags_survive_the_write(kitchen, monkeypatch):
    """hot-thai-kitchen is the HowToSections fixture. The headings are the structure the editor
    renders as section breaks, so losing them here would be invisible until someone opened it."""
    stub_fetch(monkeypatch, fetched("hot-thai-kitchen.com"))
    rid = commit(kitchen, MANIFEST["hot-thai-kitchen.com"]["url"]).get_json()["id"]
    steps = rows(kitchen, "SELECT is_heading FROM recipe_steps WHERE recipe_id = ? ORDER BY position", rid)
    assert len(steps) == 12
    assert sum(s["is_heading"] for s in steps) == 2


def test_the_imported_recipe_is_owned_by_the_importer(kitchen, monkeypatch):
    """plan_recipe carries no owner (the batch importer has no request user), but the photo/album
    routes gate on rec.owner — an ownerless import would 403 the importer off their own photos."""
    uid = harness.ensure_test_user()
    stub_fetch(monkeypatch, fetched("seriouseats.com"))
    rid = commit(kitchen, MANIFEST["seriouseats.com"]["url"]).get_json()["id"]
    assert rows(kitchen, "SELECT owner FROM recipes WHERE id = ?", rid)[0]["owner"] == uid


def test_the_import_is_immediately_editable(kitchen, monkeypatch):
    """The whole point of write-then-edit: the client navigates here and the editor must open."""
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    rid = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()["id"]
    got = kitchen.client.get("/api/recipes/" + rid).get_json()
    assert got["is_editable"] is True
    assert len(got["ingredients"]) == 15 and len(got["steps"]) == 5


# --------------------------------------------------------------------------- #
# 2. Provenance lands; the baseline does NOT (yet)
# --------------------------------------------------------------------------- #
def test_provenance_is_recorded_as_a_recipe_level_flag(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    rid = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()["id"]
    flags = rows(kitchen, "SELECT position, flag, reason FROM import_flags "
                          "WHERE recipe_id = ? AND flag = 'imported_via'", rid)
    assert len(flags) == 1
    assert flags[0]["position"] is None          # recipe-level, not a line
    assert flags[0]["reason"] == "json-ld"       # the FIRST recipe-level flag to use `reason`


def test_no_original_baseline_exists_before_the_first_save(kitchen, monkeypatch):
    """THE POINT OF THE STAGE. A baseline captured now would be the PUBLISHER's text, so every parse
    error the user is about to fix would render as one of "your changes" forever."""
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    rid = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()["id"]
    assert rows(kitchen, "SELECT id FROM recipe_snapshots WHERE recipe_id = ? AND reason = 'original'",
                rid) == []
    # and with no baseline the annotations layer is simply empty, never an error
    assert kitchen.client.get("/api/recipes/" + rid).get_json()["annotations"] == []


def test_the_first_save_captures_the_baseline_from_what_was_approved(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    rid = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()["id"]
    got = kitchen.client.get("/api/recipes/" + rid).get_json()

    payload = {"name": got["recipe"]["name"], "ingredients": [{"text": "CORRECTED olive oil"}],
               "steps": ["Corrected step."]}
    assert kitchen.client.put("/api/recipes/" + rid, json=payload).status_code == 200

    snaps = rows(kitchen, "SELECT id FROM recipe_snapshots WHERE recipe_id = ? AND reason = 'original'", rid)
    assert len(snaps) == 1                        # captured now, not at import
    # The baseline IS the corrected content, so the correction leaves NO annotation behind.
    assert kitchen.client.get("/api/recipes/" + rid).get_json()["annotations"] == []


def test_edits_after_the_first_save_do_produce_annotations(kitchen, monkeypatch):
    """The other half: baseline-at-confirm must not mean baseline-never. Once captured, ordinary
    change tracking behaves exactly as it does for any other recipe."""
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    rid = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()["id"]
    name = kitchen.client.get("/api/recipes/" + rid).get_json()["recipe"]["name"]
    base = {"name": name, "ingredients": [{"text": "olive oil"}], "steps": ["Step one."]}
    kitchen.client.put("/api/recipes/" + rid, json=base)                       # confirm
    kitchen.client.put("/api/recipes/" + rid,                                  # a real later edit
                       json={**base, "ingredients": [{"text": "olive oil"}, {"text": "garlic"}]})
    assert kitchen.client.get("/api/recipes/" + rid).get_json()["annotations"] != []


def test_the_baseline_gate_does_not_fire_for_an_ordinary_recipe(kitchen):
    """A recipe with NO imported_via flag must never have a baseline minted on save —
    sync_original_heading_layout's docstring: that would declare it born in its edited state and
    erase every annotation it should have had. Ordinary recipes get theirs at CREATE."""
    rid = kitchen.client.post("/api/recipes", json={
        "name": "Ordinary Dish", "ingredients": [{"text": "salt"}], "steps": ["Mix."]}).get_json()["id"]
    with kitchen.conn() as c:      # remove the create-time baseline to model a pre-O-b recipe
        c.execute("DELETE FROM recipe_snapshots WHERE recipe_id = ? AND reason = 'original'", (rid,))
    kitchen.client.put("/api/recipes/" + rid,
                       json={"name": "Ordinary Dish", "ingredients": [{"text": "pepper"}], "steps": ["Stir."]})
    assert rows(kitchen, "SELECT id FROM recipe_snapshots WHERE recipe_id = ? AND reason = 'original'",
                rid) == []


# --------------------------------------------------------------------------- #
# 3. The SSRF guard stays on
# --------------------------------------------------------------------------- #
def test_the_commit_route_never_disables_the_ssrf_guard(kitchen, monkeypatch):
    """url_fetch.allow_private turns U0b's guard OFF wholesale. It exists for url_fetch's own
    loopback transport tests; a route passing it would silently reopen both closed gaps."""
    calls = []
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"), calls)
    commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    assert len(calls) == 1
    assert "allow_private" not in calls[0][1]


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/",
                                 "http://localhost:8000/admin", "http://10.0.0.5/secret"])
def test_private_addresses_are_refused_before_any_fetch(kitchen, monkeypatch, url):
    calls = []
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"), calls)
    before = counts(kitchen)
    r = commit(kitchen, url)
    assert r.status_code == 400 and r.get_json()["code"] == "BLOCKED_HOST"
    assert calls == [] and counts(kitchen) == before


# --------------------------------------------------------------------------- #
# 4. Failure leaves nothing behind
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code,status", [
    ("BAD_URL", 400), ("NOT_HTML", 400), ("HTTP_ERROR", 502), ("NETWORK_ERROR", 502),
    ("TOO_LARGE", 502), ("TIMEOUT", 504), ("BLOCKED_ADDRESS", 400), ("BLOCKED_REDIRECT", 502),
    ("TOO_MANY_REDIRECTS", 502),
])
def test_a_fetch_that_worked_at_preview_can_fail_at_commit(kitchen, monkeypatch, code, status):
    """The fetch is repeated, so anything that can change between preview and commit — the site goes
    down, Cloudflare starts challenging, a redirect is added — surfaces here with U4's own wording
    and status. The write is the LAST thing that happens, so nothing exists to clean up."""
    before = counts(kitchen)
    stub_fetch(monkeypatch, url_fetch.Refused(code, "detail here", "https://example.com/x", 0))
    r = commit(kitchen, "https://example.com/x")
    assert (r.status_code, r.get_json()["code"]) == (status, code)
    assert counts(kitchen) == before


def test_an_unreadable_page_is_422_and_writes_nothing(kitchen, monkeypatch):
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("lahbco.com"))
    r = commit(kitchen, MANIFEST["lahbco.com"]["url"])
    assert r.status_code == 422
    assert r.get_json()["error"] == "json-ld: found Article and ImageObject, not Recipe"
    assert counts(kitchen) == before


def test_a_failed_write_leaves_no_partial_recipe(kitchen, monkeypatch):
    """The insert loop is mid-transaction when it throws, so the recipe row is already in the session.
    Only the missing commit keeps it out of the database — assert that rather than trusting it."""
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    real = import_write.commit_plan

    def boom(executor, plan, **kwargs):
        real(executor, plan, **kwargs)          # write every row...
        raise RuntimeError("write failed after the rows went in")

    monkeypatch.setattr(import_write, "commit_plan", boom)
    r = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    assert r.status_code == 500                 # the honest outcome: an error, not a half-written recipe
    assert counts(kitchen) == before


@pytest.mark.parametrize("payload", [{}, {"url": ""}, {"url": "   "}])
def test_a_missing_url_is_a_400(kitchen, payload):
    r = kitchen.client.post("/api/import/commit", json=payload)
    assert r.status_code == 400 and r.get_json()["code"] == "BAD_URL"


def test_commit_requires_login(kitchen_logged_out):
    r = kitchen_logged_out.client.post("/api/import/commit", json={"url": "https://example.com/r"})
    assert r.status_code == 401


def test_commit_is_not_reachable_by_navigation(kitchen):
    assert kitchen.client.get("/api/import/commit").status_code == 405


# --------------------------------------------------------------------------- #
# 5. Re-importing an address you already have
# --------------------------------------------------------------------------- #
def test_reimporting_the_same_url_proceeds_and_warns(kitchen, monkeypatch):
    """A WARNING, never a block. Two versions of a recipe is a legitimate thing to want, and the
    import has already happened by the time the warning is read — it names the twin so the user can
    decide to keep or cancel."""
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    first = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()
    assert first["duplicate"] is None

    second_res = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    second = second_res.get_json()
    assert second_res.status_code == 201                       # proceeded
    assert second["id"] != first["id"]                         # a distinct recipe, mint_slug suffixed
    assert second["duplicate"]["id"] == first["id"]            # naming the twin
    assert kitchen.count("recipes", f"id = '{second['id']}'") == 1


def test_the_duplicate_warning_survives_url_variants(kitchen, monkeypatch):
    """Normalized on both sides (U4's normalize_source_url) — the newsletter link with utm params is
    recognised as the recipe you already have."""
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    first = commit(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()
    stub_fetch(monkeypatch, fetched(
        "bbcgoodfood.com", "http://www.bbcgoodfood.com/recipes/classic-lasagne/?utm_source=nl"))
    assert commit(kitchen, "http://www.bbcgoodfood.com/recipes/classic-lasagne/?utm_source=nl"
                  ).get_json()["duplicate"]["id"] == first["id"]


# --------------------------------------------------------------------------- #
# The hero, which is fetched AFTER the commit and never inside it
# --------------------------------------------------------------------------- #
def _jpeg(w, h):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 70, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def stub_image(monkeypatch, by_url=None, calls=None):
    """Answer url_image.fetch_image from a dict. Anything unlisted is a 404, so a test states the
    urls it expects to be asked for and nothing reaches the network."""
    import url_image
    by_url = by_url or {}

    def fake(url, **kwargs):
        if calls is not None:
            calls.append(url)
        value = by_url.get(url)
        if value is None:
            return url_fetch.Refused("HTTP_ERROR", "the image host refused the request (HTTP 404)", url, 404)
        if isinstance(value, url_fetch.Refused):
            return value
        return url_image.FetchedImage(url, value, "image/jpeg")

    monkeypatch.setattr(url_image, "fetch_image", fake)


def test_a_real_import_lands_with_its_hero(kitchen, monkeypatch):
    """The happy path. kingarthurbaking publishes one ImageObject at 1248x832, over the 800 bar, so
    exactly one request is made and the recipe arrives with a picture."""
    import url_jsonld
    stub_fetch(monkeypatch, fetched("kingarthurbaking.com"))
    url = MANIFEST["kingarthurbaking.com"]["url"]
    candidates = url_jsonld.read(fetched("kingarthurbaking.com").html, url)["images"]
    asked = []
    stub_image(monkeypatch, {candidates[0]: _jpeg(1248, 832)}, calls=asked)

    body = commit(kitchen, url).get_json()
    assert body["hero"].startswith("images/cooks/")
    assert asked == [candidates[0]]                      # stopped at the first, over the bar

    stored = rows(kitchen, "SELECT image FROM recipes WHERE id=?", body["id"])[0][0]
    assert stored == body["hero"]


def test_the_imported_hero_is_also_an_album_row_like_every_other_hero(kitchen, monkeypatch):
    """⚠️ MEASURED, NOT TIDY. All 120 heroes in the live database also carry a cook_photos row with
    the same path, 0 exceptions, and is_hero derives from recipes.image == p.path across the album.
    A hero with no album row would show on the card and be missing from the album."""
    import url_jsonld
    stub_fetch(monkeypatch, fetched("kingarthurbaking.com"))
    url = MANIFEST["kingarthurbaking.com"]["url"]
    candidates = url_jsonld.read(fetched("kingarthurbaking.com").html, url)["images"]
    stub_image(monkeypatch, {candidates[0]: _jpeg(1248, 832)})

    body = commit(kitchen, url).get_json()
    album = rows(kitchen, "SELECT path, cook_log_id, position FROM cook_photos WHERE recipe_id=?", body["id"])
    assert len(album) == 1
    assert album[0][0] == body["hero"]
    assert album[0][1] is None                           # cook-less, as an uploaded hero is
    assert album[0][2] == 0


def test_the_thumbnails_are_skipped_and_the_full_size_photo_is_stored(kitchen, monkeypatch):
    """hot-thai-kitchen publishes 225x225, 260x195 and 320x180 before its 1200x1200. Bare [0] would
    store a thumbnail against a LONG_EDGE of 1600."""
    import url_jsonld
    stub_fetch(monkeypatch, fetched("hot-thai-kitchen.com"))
    url = MANIFEST["hot-thai-kitchen.com"]["url"]
    candidates = url_jsonld.read(fetched("hot-thai-kitchen.com").html, url)["images"]
    assert len(candidates) == 4
    asked = []
    stub_image(monkeypatch, dict(zip(candidates, [_jpeg(225, 225), _jpeg(260, 195),
                                                  _jpeg(320, 180), _jpeg(1200, 1200)])), calls=asked)

    body = commit(kitchen, url).get_json()
    assert asked == candidates                           # all four, in the page's order

    import images as images_mod
    from PIL import Image
    on_disk = images_mod.IMAGES_DIR / body["hero"][len("images/"):]
    assert max(Image.open(on_disk).size) == 1200         # the full-size photo, not the 225 thumbnail


@pytest.mark.parametrize("label,answer", [
    ("the address guard blocks it", url_fetch.Refused(
        "BLOCKED_ADDRESS", "that address is on a private network", "x")),
    ("the host is gone", url_fetch.Refused("HTTP_ERROR", "HTTP 404", "x", 404)),
    ("the bytes are not an image", b"%PDF-1.4 not a photograph"),
])
def test_a_failing_image_leaves_a_complete_recipe_rather_than_no_recipe(kitchen, monkeypatch,
                                                                       label, answer):
    """⚠️ THE REASON THE FETCH IS AFTER THE COMMIT. Every one of these happens on a third-party host,
    long after the recipe itself is perfect. Inside the transaction each would destroy a good
    import."""
    import url_jsonld
    stub_fetch(monkeypatch, fetched("kingarthurbaking.com"))
    url = MANIFEST["kingarthurbaking.com"]["url"]
    candidates = url_jsonld.read(fetched("kingarthurbaking.com").html, url)["images"]
    stub_image(monkeypatch, {candidates[0]: answer})

    response = commit(kitchen, url)
    body = response.get_json()
    assert response.status_code == 201, label
    assert body["hero"] is None, label
    rid = body["id"]
    assert rows(kitchen, "SELECT image FROM recipes WHERE id=?", rid)[0][0] is None, label
    assert rows(kitchen, "SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id=?", rid)[0][0] == 12, label
    assert rows(kitchen, "SELECT COUNT(*) FROM recipe_steps WHERE recipe_id=?", rid)[0][0] > 0, label
    assert rows(kitchen, "SELECT COUNT(*) FROM cook_photos WHERE recipe_id=?", rid)[0][0] == 0, label


def test_a_page_publishing_no_image_imports_cleanly(kitchen, monkeypatch):
    page = """<!doctype html><html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Plain Lentils",
     "recipeIngredient":["200 g lentils"],
     "recipeInstructions":[{"@type":"HowToStep","text":"Simmer until soft."}]}
    </script></head><body></body></html>"""
    stub_fetch(monkeypatch, url_fetch.Fetched("https://example.test/lentils", page, "text/html", "utf-8"))
    asked = []
    stub_image(monkeypatch, {}, calls=asked)

    body = commit(kitchen, "https://example.test/lentils").get_json()
    assert body["hero"] is None
    assert asked == []                                   # nothing to fetch, so nothing was fetched
    assert rows(kitchen, "SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id=?", body["id"])[0][0] == 1


def test_a_page_publishing_a_private_image_url_cannot_make_the_server_fetch_it(kitchen, monkeypatch):
    """The recipe url is typed by the user. THIS url is published by the page, so the guard is what
    stands between a pasted link and the server retrieving its own metadata endpoint."""
    import url_image
    page = """<!doctype html><html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Recipe","name":"Short Ribs",
     "image":"http://169.254.169.254/latest/meta-data/iam/",
     "recipeIngredient":["2 kg short ribs"],
     "recipeInstructions":[{"@type":"HowToStep","text":"Braise."}]}
    </script></head><body></body></html>"""
    stub_fetch(monkeypatch, url_fetch.Fetched("https://example.test/ribs", page, "text/html", "utf-8"))
    monkeypatch.setattr(url_image, "fetch_image", _REAL_IMAGE_FETCH)   # the REAL guard, not a stub

    body = commit(kitchen, "https://example.test/ribs").get_json()
    assert body["hero"] is None
    assert rows(kitchen, "SELECT image FROM recipes WHERE id=?", body["id"])[0][0] is None
    assert rows(kitchen, "SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id=?", body["id"])[0][0] == 1
