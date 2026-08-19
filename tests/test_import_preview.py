"""U4: the preview route — POST /api/import/preview.

Paste a URL, get back what WOULD be imported. NOTHING is written, and that is asserted rather than
assumed: every success case checks row counts across all six tables the write path touches.

NO NETWORK. url_fetch.fetch is monkeypatched to return U0's committed fixtures (or a Refused), so the
route's fetch->cascade->clean->plan path runs end to end offline. That is the same seam a real fetch
crosses, so stubbing it exercises everything except urllib itself, which test_url_fetch.py owns.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest       # noqa: E402

import app          # noqa: E402
import harness      # noqa: E402
import url_cascade  # noqa: E402
import url_fetch    # noqa: E402
import url_jsonld   # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"
MANIFEST = {r["domain"]: r for r in json.loads((FIXTURES / "manifest.json").read_text())}

# Every table the write path (commit_plan) touches, plus snapshots — a preview must leave all of them
# exactly as it found them.
TABLES = ("recipes", "recipe_ingredients", "recipe_steps", "ratings", "import_flags",
          "recipe_snapshots")


def page(domain):
    row = MANIFEST[domain]
    return (FIXTURES / row["file"]).read_text(errors="replace")


def fetched(domain, url=None):
    """The Fetched a real fetch of this fixture's page would have produced."""
    return url_fetch.Fetched(url or MANIFEST[domain]["url"], page(domain), "text/html", "utf-8")


def stub_fetch(monkeypatch, result, calls=None):
    def fake(url, **kwargs):
        if calls is not None:
            calls.append(url)
        return result
    monkeypatch.setattr(url_fetch, "fetch", fake)


def counts(kitchen):
    return {t: kitchen.count(t) for t in TABLES}


def preview(kitchen, url):
    return kitchen.client.post("/api/import/preview", json={"url": url})


# --------------------------------------------------------------------------- #
# 1. A successful read, end to end
# --------------------------------------------------------------------------- #
def test_preview_returns_the_plan_it_would_write(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    r = preview(kitchen, "https://www.bbcgoodfood.com/recipes/classic-lasagne")
    assert r.status_code == 200
    body = r.get_json()

    assert body["slug"] == "easy-classic-lasagne"
    assert body["recipe"]["name"] == "Easy classic lasagne"
    assert body["recipe"]["author"] == "Angela Boggiano"
    assert body["recipe"]["servings"] == "6"
    assert body["recipe"]["total_time"] == "1 hr 15 min"
    assert body["recipe"]["source_url"] == "https://www.bbcgoodfood.com/recipes/classic-lasagne"
    assert len(body["ingredients"]) == 15
    assert len(body["steps"]) == 5
    assert body["duplicate"] is None


def test_preview_carries_provenance_for_u5_to_persist(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("seriouseats.com"))
    body = preview(kitchen, MANIFEST["seriouseats.com"]["url"]).get_json()
    assert body["read_by"] == "json-ld"
    # the exact recipe-level import_flags row U5 will write — reason carries the layer (U2's helper)
    assert body["provenance_flag"] == {"position": None, "flag": "imported_via", "reason": "json-ld"}


def test_preview_keeps_step_heading_flags(kitchen, monkeypatch):
    """hot-thai-kitchen is the fixture with HowToSections (manifest: howto_sections=2). The heading
    flags are what the client renders as section breaks, so they must survive into the response."""
    stub_fetch(monkeypatch, fetched("hot-thai-kitchen.com"))
    body = preview(kitchen, MANIFEST["hot-thai-kitchen.com"]["url"]).get_json()
    assert sum(s["is_heading"] for s in body["steps"]) == 2
    assert all({"position", "is_heading", "text"} == set(s) for s in body["steps"])


def test_preview_ingredient_rows_carry_the_split_amount(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    body = preview(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()
    first = body["ingredients"][0]
    assert first["qty"] == "1 tbsp" and first["quantity"] == "1" and first["unit"] == "tbsp"
    assert first["label"] == "olive oil"
    assert first["raw_text"] == "1 tbsp olive oil"
    # dropped on purpose: unconditionally None out of the importer (see preview_body's docstring)
    assert "ingredient_id" not in first and "note" not in first


def test_preview_omits_plan_fields_that_are_minted_or_always_empty(kitchen, monkeypatch):
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    body = preview(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()
    for absent in ("created_at", "uid", "hash", "source", "image"):
        assert absent not in body["recipe"], absent


# --------------------------------------------------------------------------- #
# 2. It writes NOTHING
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("domain", ["bbcgoodfood.com", "hot-thai-kitchen.com", "kingarthurbaking.com"])
def test_preview_writes_nothing(kitchen, monkeypatch, domain):
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched(domain))
    assert preview(kitchen, MANIFEST[domain]["url"]).status_code == 200
    assert counts(kitchen) == before


def test_repeated_previews_of_the_same_url_still_write_nothing(kitchen, monkeypatch):
    """The dedup warning is non-blocking, so a user may preview the same URL repeatedly. Doing so
    must stay free — no row, no partial recipe, no half-written plan."""
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("recipetineats.com"))
    for _ in range(3):
        assert preview(kitchen, MANIFEST["recipetineats.com"]["url"]).status_code == 200
    assert counts(kitchen) == before


# --------------------------------------------------------------------------- #
# 3. Fetch refusals -> status codes and messages
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code,status,detail", [
    ("BAD_URL", 400, "only http:// and https:// URLs can be imported"),
    ("NOT_HTML", 400, "the URL returned application/pdf, not a web page"),
    ("HTTP_ERROR", 502, "the site refused the request (HTTP 403)"),
    ("NETWORK_ERROR", 502, "could not reach the site: [Errno 8] nodename nor servname provided"),
    ("TOO_LARGE", 502, "the page is larger than 8MB"),
    ("TIMEOUT", 504, "the site did not respond within 20s"),
])
def test_fetch_refusals_map_to_sensible_statuses(kitchen, monkeypatch, code, status, detail):
    stub_fetch(monkeypatch, url_fetch.Refused(code, detail, "https://example.com/x", 0))
    r = preview(kitchen, "https://example.com/x")
    assert r.status_code == status
    body = r.get_json()
    assert body["code"] == code
    assert body["error"] == detail          # url_fetch's wording, passed through unchanged


def test_a_site_that_refuses_says_the_site_refused(kitchen, monkeypatch):
    """maangchi.com's Cloudflare 403 is the real-world case (url_fetch's docstring). The user must
    learn the SITE said no — not that their recipe was unreadable, which would be false and would
    send them off to fix a page that is fine."""
    stub_fetch(monkeypatch, url_fetch.Refused(
        "HTTP_ERROR", "the site refused the request (HTTP 403)", "https://www.maangchi.com/recipe/x", 403))
    r = preview(kitchen, "https://www.maangchi.com/recipe/x")
    assert r.status_code == 502
    body = r.get_json()
    assert "refused" in body["error"] and "403" in body["error"]
    assert body["status"] == 403
    assert "unreadable" not in body["error"] and "recipe" not in body["error"]


# --------------------------------------------------------------------------- #
# 4. Reader refusals -> 422 with every layer's reason
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("domain,message", [
    ("lahbco.com", "json-ld: found Article and ImageObject, not Recipe"),
    ("notanothercooking.tv", "json-ld: found BlogPosting and ImageObject, not Recipe"),
    ("nigella.com", "json-ld: no JSON-LD on the page"),
    ("youtube.com", "json-ld: no JSON-LD on the page"),
])
def test_unreadable_pages_are_422_with_the_composed_message(kitchen, monkeypatch, domain, message):
    stub_fetch(monkeypatch, fetched(domain))
    r = preview(kitchen, MANIFEST[domain]["url"])
    assert r.status_code == 422                     # fetched fine; simply carries no usable recipe
    body = r.get_json()
    assert body["code"] == "NO_RECIPE_FOUND"
    assert body["error"] == message
    assert [f["layer"] for f in body["refusals"]] == ["json-ld"]


def test_an_unreadable_page_writes_nothing(kitchen, monkeypatch):
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("lahbco.com"))
    assert preview(kitchen, MANIFEST["lahbco.com"]["url"]).status_code == 422
    assert counts(kitchen) == before


# --------------------------------------------------------------------------- #
# 5. URL normalization + the duplicate warning
# --------------------------------------------------------------------------- #
SAME = [
    ("http://example.com/r/1", "https://example.com/r/1", "scheme"),
    ("https://www.example.com/r/1", "https://example.com/r/1", "www."),
    ("https://amp.example.com/r/1", "https://example.com/r/1", "amp. host"),
    ("https://example.com/r/1/", "https://example.com/r/1", "trailing slash"),
    ("https://example.com/r/1/amp", "https://example.com/r/1", "/amp segment"),
    ("https://example.com/r/1/amp/", "https://example.com/r/1", "/amp/ segment"),
    ("https://example.com:443/r/1", "https://example.com/r/1", "default port"),
    ("https://example.com/r/1#method", "https://example.com/r/1", "fragment"),
    ("https://example.com/r/1?utm_source=nl&utm_medium=email", "https://example.com/r/1", "utm_*"),
    ("https://example.com/r/1?fbclid=abc", "https://example.com/r/1", "fbclid"),
    ("https://example.com/r/1?ref=twitter", "https://example.com/r/1", "ref"),
    ("https://example.com/r/1?amp=1", "https://example.com/r/1", "amp param"),
    ("https://example.com/?p=12", "https://example.com?p=12", "root path"),
    ("https://example.com/r?b=2&a=1", "https://example.com/r?a=1&b=2", "param order"),
    ("https://WWW.EXAMPLE.COM/r/1", "https://example.com/r/1", "host case"),
]


@pytest.mark.parametrize("a,b,why", SAME, ids=[c[2] for c in SAME])
def test_urls_that_are_the_same_page_normalize_together(a, b, why):
    assert app.normalize_source_url(a) == app.normalize_source_url(b) != ""


DIFFERENT = [
    ("https://example.com/r/1", "https://example.com/r/2", "different path"),
    ("https://example.com/r/1", "https://other.com/r/1", "different host"),
    ("https://example.com/r/1", "https://example.com/R/1", "path case is significant"),
    ("https://example.com/?p=12", "https://example.com/?p=13", "meaningful query kept"),
    ("https://example.com:8080/r/1", "https://example.com/r/1", "non-default port kept"),
]


@pytest.mark.parametrize("a,b,why", DIFFERENT, ids=[c[2] for c in DIFFERENT])
def test_urls_that_are_different_pages_stay_apart(a, b, why):
    assert app.normalize_source_url(a) != app.normalize_source_url(b)


@pytest.mark.parametrize("bad", ["", "   ", "not a url", "ftp://example.com/r", "file:///etc/passwd",
                                 "https://", "https://example.com:notaport/r"])
def test_unimportable_urls_have_no_dedup_key(bad):
    assert app.normalize_source_url(bad) == ""


def _own_recipe(client, name, source_url):
    r = client.post("/api/recipes", json={"name": name, "ingredients": [], "steps": [],
                                          "source_url": source_url})
    assert r.status_code == 201
    return r.get_json()["id"]


def test_duplicate_warning_fires_across_url_variants(kitchen, monkeypatch):
    """The stored URL and the pasted one differ by www., scheme, a trailing slash AND tracking params
    — the exact shape of 'I already saved this from a newsletter link'."""
    rid = _own_recipe(kitchen.client, "Classic Lasagne",
                      "http://www.bbcgoodfood.com/recipes/classic-lasagne/?utm_source=newsletter")
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    body = preview(kitchen, "https://www.bbcgoodfood.com/recipes/classic-lasagne").get_json()
    assert body["duplicate"] == {
        "id": rid, "name": "Classic Lasagne",
        "source_url": "http://www.bbcgoodfood.com/recipes/classic-lasagne/?utm_source=newsletter",
    }


def test_the_duplicate_warning_never_blocks_the_preview(kitchen, monkeypatch):
    """A warning, not a skip: the full plan still comes back and the status is still 200, because
    re-importing a recipe you already have is the USER's call to make."""
    _own_recipe(kitchen.client, "Classic Lasagne", MANIFEST["bbcgoodfood.com"]["url"])
    before = counts(kitchen)
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    r = preview(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    assert r.status_code == 200
    body = r.get_json()
    assert body["duplicate"] is not None
    assert len(body["ingredients"]) == 15 and len(body["steps"]) == 5    # the whole plan, undiminished
    assert counts(kitchen) == before


def test_no_duplicate_warning_for_a_url_not_yet_imported(kitchen, monkeypatch):
    _own_recipe(kitchen.client, "Something Else", "https://example.com/other-recipe")
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))
    body = preview(kitchen, MANIFEST["bbcgoodfood.com"]["url"]).get_json()
    assert body["duplicate"] is None


def test_the_same_dish_from_another_site_is_not_a_duplicate(kitchen, monkeypatch):
    """Explicitly out of scope: two publishers' versions of one dish are two typeset recipes, with
    different words, amounts and photos. Collapsing them would destroy the comparison, not help it."""
    _own_recipe(kitchen.client, "Banana Bread", "https://www.allrecipes.com/banana-bread-recipe-123")
    stub_fetch(monkeypatch, fetched("seriouseats.com"))
    body = preview(kitchen, MANIFEST["seriouseats.com"]["url"]).get_json()
    assert body["duplicate"] is None


def test_dedup_uses_the_url_after_redirects(kitchen, monkeypatch):
    """url_fetch reports response.url — where it LANDED. A shortlink must dedup against the page it
    resolves to, not against the shortlink, or every share link looks new."""
    rid = _own_recipe(kitchen.client, "Lasagne", MANIFEST["bbcgoodfood.com"]["url"])
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))          # Fetched.url = the FINAL url
    body = preview(kitchen, "https://bbcgd.co/xyz123").get_json()
    assert body["duplicate"]["id"] == rid
    assert body["recipe"]["source_url"] == MANIFEST["bbcgoodfood.com"]["url"]


# --------------------------------------------------------------------------- #
# 6. The server-side fetch guard (partial by design — see private_host_refusal)
# --------------------------------------------------------------------------- #
BLOCKED = ["http://localhost:8000/admin", "http://LOCALHOST/x", "http://foo.localhost/x",
           "http://127.0.0.1/x", "http://127.9.9.9/x", "http://[::1]/x",
           "http://10.0.0.5/secret", "http://192.168.1.1/", "http://172.16.0.1/",
           "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/"]


@pytest.mark.parametrize("url", BLOCKED)
def test_private_addresses_are_refused_before_any_fetch(kitchen, monkeypatch, url):
    calls = []
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"), calls)
    r = kitchen.client.post("/api/import/preview", json={"url": url})
    assert r.status_code == 400
    assert r.get_json()["code"] == "BLOCKED_HOST"
    assert calls == []                      # refused BEFORE the network is touched, not after


@pytest.mark.parametrize("url", ["https://www.bbcgoodfood.com/recipes/classic-lasagne",
                                 "https://8.8.8.8/recipe", "https://example.com/r"])
def test_public_addresses_are_not_refused(url):
    assert app.private_host_refusal(url) is None


def test_a_dns_name_is_not_resolved_here(kitchen):
    """PINS THE KNOWN GAP so it can't be mistaken for coverage: the guard reads the URL only. A name
    that RESOLVES to a private address passes, as does a public URL that redirects to one. Closing
    either needs resolve-then-check plus a redirect handler inside url_fetch (U0), out of scope here."""
    assert app.private_host_refusal("http://internal.example.com/x") is None


# --------------------------------------------------------------------------- #
# 7. Method, auth and payload
# --------------------------------------------------------------------------- #
def test_preview_is_not_reachable_by_navigation(kitchen):
    """POST-only on purpose: a GET that makes the server fetch an arbitrary URL is reachable by a
    link, an <img> or a prefetch — the same shape as a GET that writes."""
    assert kitchen.client.get("/api/import/preview").status_code == 405


def test_preview_requires_login(kitchen_logged_out):
    r = kitchen_logged_out.client.post("/api/import/preview", json={"url": "https://example.com/r"})
    assert r.status_code == 401


def test_a_logged_out_request_never_fetches(kitchen_logged_out, monkeypatch):
    calls = []
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"), calls)
    kitchen_logged_out.client.post("/api/import/preview", json={"url": "https://example.com/r"})
    assert calls == []


@pytest.mark.parametrize("payload", [{}, {"url": ""}, {"url": "   "}, {"nope": "x"}])
def test_a_missing_url_is_a_400(kitchen, payload):
    r = kitchen.client.post("/api/import/preview", json=payload)
    assert r.status_code == 400
    assert r.get_json()["code"] == "BAD_URL"


# --------------------------------------------------------------------------- #
# 8. The defensive twin branch
# --------------------------------------------------------------------------- #
def test_a_reader_supplied_uid_that_already_exists_is_a_409(kitchen, monkeypatch):
    """Structurally unreachable with today's readers (url_jsonld sets uid=""), so it is driven with a
    stubbed Read. The branch exists so a future reader that DOES supply a uid gets a real answer
    rather than a KeyError on plan['recipe']."""
    rid = _own_recipe(kitchen.client, "The Twin", "https://example.com/twin")
    with kitchen.conn() as c:
        c.execute("UPDATE recipes SET uid = ? WHERE id = ?", ("twin-uid", rid))

    normalized = dict(url_jsonld.read(page("bbcgoodfood.com"), MANIFEST["bbcgoodfood.com"]["url"]),
                      uid="twin-uid")
    monkeypatch.setattr(url_cascade, "read",
                        lambda url, html: url_cascade.Read(normalized, {"layer": "stub"}))
    stub_fetch(monkeypatch, fetched("bbcgoodfood.com"))

    before = counts(kitchen)
    r = preview(kitchen, MANIFEST["bbcgoodfood.com"]["url"])
    assert r.status_code == 409
    body = r.get_json()
    assert body["code"] == "ALREADY_IMPORTED"
    assert body["twin"] == {"slug": rid, "name": "The Twin"}
    assert counts(kitchen) == before
