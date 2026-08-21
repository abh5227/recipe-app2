"""U0: the fetcher's transport behaviour, and the committed HTML fixtures.

Every case runs against a LOCALHOST server, not the internet: gzip, redirects, 403, non-HTML,
oversize and timeout are all exercised for real (a real socket, a real urllib call, real headers)
while staying deterministic and CI-safe. Mocking urllib would have tested the mock — the whole point
of this stage is that the transport details are right, and those live in the parts a mock replaces.

The one test that talks to the real internet is gated behind RUN_NETWORK_TESTS=1 and is skipped
otherwise, so it never runs in CI (no workflow sets that variable).
"""
import gzip
import json
import os
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import url_fetch

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"

PAGE = "<!DOCTYPE html><html><head><title>Bún chả</title></head><body>ok</body></html>"


def fetch(url, **kwargs):
    """url_fetch.fetch with the U0b address guard turned OFF.

    Every transport case below serves from 127.0.0.1, which the guard refuses BY DESIGN — that is the
    point of the guard, not a flaw in these tests. They are about gzip, charsets, caps and timeouts,
    so they opt out explicitly and the guard is exercised by its own tests in
    tests/test_url_fetch_guard.py. The live-network test deliberately does NOT use this wrapper: it
    must prove a real public fetch still works WITH the guard on.
    """
    kwargs.setdefault("allow_private", True)
    return url_fetch.fetch(url, **kwargs)


class Handler(BaseHTTPRequestHandler):
    """Serves one scripted behaviour per path. Records the request headers it saw."""
    seen = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", ctype="text/html; charset=utf-8", extra=None):
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Handler.seen[self.path] = dict(self.headers)
        if self.path == "/plain":
            return self._send(200, PAGE.encode())
        if self.path == "/gzipped":
            return self._send(200, gzip.compress(PAGE.encode()), extra={"Content-Encoding": "gzip"})
        if self.path == "/latin1":
            body = "<html><body>café</body></html>".encode("latin-1")
            return self._send(200, body, ctype="text/html; charset=iso-8859-1")
        if self.path == "/nocharset":
            return self._send(200, "<html><body>café</body></html>".encode(), ctype="text/html")
        # The header forms REAL sites send. Measured across 4 of the 14 fixture domains:
        # recipetineats + minimalistbaker send "text/html; charset=UTF-8" (uppercase charset VALUE),
        # allrecipes + seriouseats send "text/html;charset=utf-8" (no space). Every other path in this
        # file sends one lowercase spelling, so none of them exercised a parameter or a capital.
        if self.path == "/upper-charset":
            return self._send(200, PAGE.encode(), ctype="text/html; charset=UTF-8")
        if self.path == "/nospace-charset":
            return self._send(200, PAGE.encode(), ctype="text/html;charset=utf-8")
        if self.path == "/upper-type":
            return self._send(200, PAGE.encode(), ctype="TEXT/HTML; CHARSET=UTF-8")
        if self.path == "/xhtml":
            return self._send(200, PAGE.encode(), ctype="application/xhtml+xml; charset=UTF-8")
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/landed")
            self.end_headers()
            return
        if self.path == "/landed":
            return self._send(200, PAGE.encode())
        if self.path == "/forbidden":
            return self._send(403, b"nope")
        if self.path == "/notfound":
            return self._send(404, b"gone")
        if self.path == "/pdf":
            return self._send(200, b"%PDF-1.4", ctype="application/pdf")
        if self.path == "/huge":
            return self._send(200, b"x" * 40_000)
        if self.path == "/gzipbomb":
            return self._send(200, gzip.compress(b"y" * 200_000), extra={"Content-Encoding": "gzip"})
        if self.path == "/slow":
            time.sleep(3)
            return self._send(200, PAGE.encode())
        return self._send(404, b"?")


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)          # port 0 = let the OS pick a free one
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


# ----------------------------------------------------------------- the happy paths
def test_fetches_a_plain_page(server):
    got = fetch(f"{server}/plain")
    assert isinstance(got, url_fetch.Fetched)
    assert "Bún chả" in got.html                            # decoded, not bytes
    assert got.content_type == "text/html"


def test_decompresses_gzip(server):
    """EVERY sampled page came back gzipped and urllib does not decompress — without this the
    reader would be handed binary. This is the single most load-bearing line in the fetcher."""
    got = fetch(f"{server}/gzipped")
    assert isinstance(got, url_fetch.Fetched)
    assert got.html == PAGE
    assert "gzip" in Handler.seen["/gzipped"].get("Accept-Encoding", "")


def test_sends_the_honest_user_agent(server):
    fetch(f"{server}/plain")
    ua = Handler.seen["/plain"]["User-Agent"]
    assert ua == url_fetch.USER_AGENT
    assert "ChefsChoice" in ua and "+https://" in ua        # identifies itself AND points at itself
    assert "Mozilla" not in ua and "Chrome" not in ua       # never impersonates a browser


def test_captures_the_url_after_redirects(server):
    """source_url and the dedup key must be where we LANDED, not what was pasted."""
    got = fetch(f"{server}/redirect")
    assert isinstance(got, url_fetch.Fetched)
    assert got.url.endswith("/landed")


def test_decodes_the_declared_charset(server):
    got = fetch(f"{server}/latin1")
    assert isinstance(got, url_fetch.Fetched)
    assert got.encoding == "iso-8859-1"
    assert "café" in got.html                               # mis-decoding gives 'cafÃ©' or a replacement


def test_defaults_to_utf8_when_no_charset_is_declared(server):
    got = fetch(f"{server}/nocharset")
    assert isinstance(got, url_fetch.Fetched)
    assert got.encoding == "utf-8" and "café" in got.html


@pytest.mark.parametrize("path,label", [
    ("/upper-charset", "text/html; charset=UTF-8 — uppercase charset value"),
    ("/nospace-charset", "text/html;charset=utf-8 — no space before the parameter"),
    ("/upper-type", "TEXT/HTML; CHARSET=UTF-8 — uppercase MEDIA TYPE"),
    ("/xhtml", "application/xhtml+xml with a charset parameter"),
])
def test_content_type_parameters_and_case_do_not_refuse_a_page(server, path, label):
    """The media type is compared case-insensitively and its PARAMETERS are ignored, per RFC 9110:
    a media type is case-insensitive and charset is a parameter, not part of the type.

    This is a REGRESSION GUARD, not a bug fix — response.headers.get_content_type() already lowercases
    the type and strips parameters, so all four forms pass today and always have. It is pinned because
    every other test in this file sends ONE lowercase spelling, so nothing here would notice if that
    call were ever replaced with a raw-header comparison — and a raw `== "text/html"` would refuse the
    real header two of the four sampled fixture sites actually send.
    """
    got = fetch(f"{server}{path}")
    assert isinstance(got, url_fetch.Refused) is False, f"{label} was refused"
    assert got.html == PAGE


# ----------------------------------------------------------------- the refusals
def test_http_error_is_a_refusal_not_an_exception(server):
    """maangchi.com's Cloudflare 403 is the real-world case this models."""
    got = fetch(f"{server}/forbidden")
    assert isinstance(got, url_fetch.Refused)
    assert (got.code, got.status) == ("HTTP_ERROR", 403)
    assert "403" in got.detail


def test_404_is_distinguishable_from_403(server):
    got = fetch(f"{server}/notfound")
    assert got.code == "HTTP_ERROR" and got.status == 404


def test_non_html_is_refused_by_content_type(server):
    got = fetch(f"{server}/pdf")
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "NOT_HTML" and "application/pdf" in got.detail


def test_oversize_is_refused(server):
    got = fetch(f"{server}/huge", max_bytes=1000)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "TOO_LARGE"


def test_oversize_after_decompression_is_refused(server):
    """The cap binds the DECOMPRESSED stream too — a small gzip body that expands hugely is caught."""
    got = fetch(f"{server}/gzipbomb", max_bytes=5000)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "TOO_LARGE" and "expands" in got.detail


def test_timeout_is_a_refusal(server):
    got = fetch(f"{server}/slow", timeout=0.5)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "TIMEOUT"


def test_unreachable_host_is_a_refusal():
    got = fetch("http://127.0.0.1:9/nothing-listens-here", timeout=2)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "NETWORK_ERROR"


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd", "ftp://example.test/x", "not a url", "", "javascript:alert(1)",
])
def test_non_http_urls_are_refused(bad):
    got = fetch(bad)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BAD_URL"


# ----------------------------------------------------------------- the committed fixtures
def test_manifest_matches_the_files_on_disk():
    rows = json.loads((FIXTURES / "manifest.json").read_text())
    assert len(rows) == 14
    for r in rows:
        f = FIXTURES / r["file"]
        assert f.exists(), f"{r['file']} is in the manifest but not on disk"
        assert f.stat().st_size == r["bytes"], f"{r['file']} changed size since the manifest was written"
    on_disk = {f.name for f in FIXTURES.glob("*.html")}
    assert on_disk == {r["file"] for r in rows}, "a fixture exists that the manifest does not record"


def test_the_fixture_corpus_covers_every_reader_case():
    """The later stages depend on this spread, so it is pinned: 9 JSON-LD, 1 microdata-only,
    4 with no structured data at all, and exactly one page carrying HowToSections."""
    rows = json.loads((FIXTURES / "manifest.json").read_text())
    cases = {}
    for r in rows:
        cases[r["case"]] = cases.get(r["case"], 0) + 1
    assert cases == {"json-ld": 9, "microdata": 1, "none": 4}
    sectioned = [r for r in rows if r["howto_sections"]]
    assert len(sectioned) == 1
    assert sectioned[0]["domain"] == "hot-thai-kitchen.com" and sectioned[0]["howto_sections"] == 2


def test_fixtures_are_real_pages_not_stubs():
    rows = json.loads((FIXTURES / "manifest.json").read_text())
    for r in rows:
        html = (FIXTURES / r["file"]).read_text(errors="replace")
        assert len(html) > 50_000, f"{r['file']} looks trimmed — layers 2 and 4 need real body markup"
        assert "<body" in html.lower(), f"{r['file']} has no body"


# ----------------------------------------------------------------- live network (never in CI)
@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1",
                    reason="hits the real internet; set RUN_NETWORK_TESTS=1 to run. No workflow sets it.")
def test_live_fetch_of_a_real_recipe_page():
    got = url_fetch.fetch("https://www.seriouseats.com/classic-banana-bread-recipe")
    assert isinstance(got, url_fetch.Fetched), got
    assert got.url.startswith("https://")
    assert "<html" in got.html.lower() and len(got.html) > 50_000
