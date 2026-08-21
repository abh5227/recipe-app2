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
