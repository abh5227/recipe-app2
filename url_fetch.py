"""URL import, stage 0 (U0): fetch a recipe page. NO PARSING — that is the reader's job (U1+).

This module does one thing: turn a URL the user pasted into either the page's HTML or a REASON it
could not be had. It never raises for an expected failure; a refusal is a value, so the caller can
tell "the site said no" from "that isn't a web page" and show the user which.

⚠️ THE USER AGENT IS HONEST ON PURPOSE — DO NOT "FIX" IT TO IMPERSONATE A BROWSER.
Measured across the 15 sampled sites, an honest identifier costs ZERO pages: 14 of 15 served it, the
same 14 that served a Chrome string, with byte-identical content. The single refusal (maangchi.com)
is a Cloudflare interactive challenge that no user-agent string passes — pretending to be Chrome does
not get that page either, it just makes us dishonest about who is calling. The `+url` follows the
long-standing convention of pointing at the thing making the request.

NO robots.txt CHECK, also on purpose. robots.txt governs CRAWLERS — automated agents discovering and
traversing a site. This is a single fetch of a single page the user has explicitly pasted, on their
behalf, no different in kind from their browser opening it. There is no traversal, no discovery, and
no second request.

Stdlib only (urllib + gzip), no new dependencies — proven sufficient across the 14 committed fixtures
including two ~1.4MB pages.
"""
import gzip
import io
import socket
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

USER_AGENT = "ChefsChoice/1.0 (personal recipe importer; +https://github.com/abh5227/recipe-app2)"

# The largest page sampled was 1.4MB (youtube.com, notanothercookingshow.tv). 8MiB is ~5.7x that:
# comfortably clear of any real recipe page, low enough that a pathological response can't exhaust
# memory. Enforced on BOTH the compressed and the decompressed stream, so a gzip bomb is bounded too.
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 20            # sampled fetches took 0.17-1.24s; this is a stall guard, not a budget

HTML_TYPES = ("text/html", "application/xhtml+xml")


class Fetched(NamedTuple):
    """A page we actually got."""
    url: str                    # the FINAL url after redirects — this is source_url AND the dedup key
    html: str
    content_type: str
    encoding: str


class Refused(NamedTuple):
    """A page we did not get, and why. `code` is stable; `detail` is for humans."""
    code: str                   # BAD_URL | HTTP_ERROR | TIMEOUT | NETWORK_ERROR | NOT_HTML | TOO_LARGE
    detail: str
    url: str
    status: int = 0             # the HTTP status when there was one, else 0


def _read_capped(stream, limit):
    """Read at most `limit` bytes; return (data, overflowed). Reading limit+1 is how we detect
    'longer than the cap' without materialising the whole thing."""
    data = stream.read(limit + 1)
    return (data[:limit], True) if len(data) > limit else (data, False)


def fetch(url, *, timeout=TIMEOUT_SECONDS, max_bytes=MAX_BYTES):
    """Fetch `url`. Returns Fetched or Refused — never raises for an expected failure."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        # also keeps file:// and friends out of a user-supplied string
        return Refused("BAD_URL", "only http:// and https:// URLs can be imported", url)

    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        # urllib does NOT decompress for us, so we only advertise what we decode below. Every one of
        # the 14 sampled pages came back gzipped, so this path is the normal case, not an edge case.
        "Accept-Encoding": "gzip",
    })

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Content-Type is checked BEFORE the body is read, so a PDF or a video costs us nothing.
            content_type = response.headers.get_content_type()
            if content_type not in HTML_TYPES:
                return Refused("NOT_HTML", f"the URL returned {content_type}, not a web page",
                               response.url, response.status)

            raw, too_big = _read_capped(response, max_bytes)
            if too_big:
                return Refused("TOO_LARGE", f"the page is larger than {max_bytes // (1024 * 1024)}MB",
                               response.url, response.status)

            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                try:
                    raw, too_big = _read_capped(gzip.GzipFile(fileobj=io.BytesIO(raw)), max_bytes)
                except OSError as exc:
                    return Refused("NETWORK_ERROR", f"the response was not valid gzip: {exc}",
                                   response.url, response.status)
                if too_big:
                    return Refused("TOO_LARGE", f"the page expands to more than {max_bytes // (1024 * 1024)}MB",
                                   response.url, response.status)

            # Decode from the DECLARED charset rather than assuming UTF-8. errors='replace' because a
            # single bad byte should not cost the whole import.
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                html = raw.decode(encoding, errors="replace")
            except LookupError:
                encoding = "utf-8"
                html = raw.decode(encoding, errors="replace")

            # response.url is the url AFTER redirects — urllib follows them transparently, and the
            # one we landed on is what must be stored and deduped against.
            return Fetched(response.url, html, content_type, encoding)

    except urllib.error.HTTPError as exc:
        # The real-world case: maangchi.com answers 403 from a Cloudflare challenge.
        return Refused("HTTP_ERROR", f"the site refused the request (HTTP {exc.code})", url, exc.code)
    except socket.timeout:
        return Refused("TIMEOUT", f"the site did not respond within {timeout}s", url)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            return Refused("TIMEOUT", f"the site did not respond within {timeout}s", url)
        return Refused("NETWORK_ERROR", f"could not reach the site: {exc.reason}", url)
    except (OSError, ValueError) as exc:
        return Refused("NETWORK_ERROR", f"could not reach the site: {exc}", url)
