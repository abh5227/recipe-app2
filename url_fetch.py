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

SERVER-SIDE FETCH GUARD (U0b). This module makes the SERVER retrieve a user-supplied address, so it
refuses anything that is not a public destination — checked by RESOLVING the name, not just by reading
it, and re-checked on EVERY redirect hop. See the address-guard section below for what that does and
does not close.

Stdlib only (urllib + gzip + socket + ipaddress), no new dependencies — proven sufficient across the
14 committed fixtures including two ~1.4MB pages.
"""
import gzip
import io
import ipaddress
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


# --------------------------------------------------------------------------- #
# The address guard: what this server is allowed to retrieve
# --------------------------------------------------------------------------- #
# A user pastes a URL and the SERVER fetches it. That is the classic server-side request forgery
# shape: the pasted address can name the machine the app runs on (127.0.0.1), the network it sits in
# (10.x/192.168.x), or a cloud metadata endpoint (169.254.169.254), and the server reaches all three
# from inside the perimeter in a way the user's own browser could not.
#
# Two things are checked, because checking only the URL text is not enough:
#   1. RESOLVE-THEN-CHECK  — the hostname is resolved and EVERY returned address must be public. A
#      name is not safe because it looks like one: evil.example.com can simply have an A record of
#      127.0.0.1. A multi-homed name is refused if ANY of its addresses is non-public, never accepted
#      on the strength of a public one.
#   2. EVERY REDIRECT HOP  — urllib follows redirects transparently, so a public page that 302s to
#      169.254.169.254 would otherwise be fetched with no check at all. That hop is the case that
#      matters most: it is a destination the USER never chose.
#
# ⚠️ TOCTOU IS DOCUMENTED, NOT CLOSED, AND THAT IS A DELIBERATE CHOICE. Resolving and then connecting
# is inherently racy: DNS can answer 8.8.8.8 for the check and 127.0.0.1 for the connect a moment
# later (DNS rebinding). Closing it means connecting to the ALREADY-VALIDATED ip while preserving the
# Host header — and for https, passing server_hostname through by hand so SNI and certificate
# validation still work. That is a custom transport layer whose own failure mode (silently broken
# certificate validation) is worse than the race it removes. The race needs an attacker controlling
# DNS for a name the user pasted AND sub-second timing; the flat cases above need neither, which is
# why they are the ones closed here. Revisit if this app ever accepts URLs from someone who is not
# its owner.
MAX_REDIRECTS = 10              # urllib's own default (HTTPRedirectHandler.max_redirections), enforced
                                # here too so exhausting it is a REFUSAL VALUE with its own code rather
                                # than an HTTPError whose message would have to be parsed back apart.

ON_THIS_MACHINE = "that address is on this machine — imports only reach public websites"
PRIVATE_NETWORK = "that address is on a private network — imports only reach public websites"


def is_public_ip(ip):
    """Is this address one the open internet routes to? Everything else is refused."""
    return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
                or ip.is_unspecified or ip.is_multicast)


def blocked_literal(host):
    """Reason to refuse `host` judged from its TEXT alone, or None. NEVER resolves DNS.

    THE SINGLE COPY OF THIS CLASSIFICATION. app.private_host_refusal — U4's cheap pre-filter, which
    rejects an obviously-private URL before the route touches the network at all — delegates here
    rather than keeping its own, so the two can never drift apart.
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return None
    if host == "localhost" or host.endswith(".localhost"):
        return ON_THIS_MACHINE
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None                          # a NAME — only resolve_refusal can judge it
    return None if is_public_ip(ip) else PRIVATE_NETWORK


def resolve_refusal(host, port):
    """Resolve `host` and return (code, detail) if ANY address is non-public, else None."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return ("NETWORK_ERROR", f"could not reach the site: {exc}")
    for info in infos:
        raw = info[4][0].split("%")[0]       # drop any IPv6 zone id (fe80::1%lo0) before parsing
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:                   # pragma: no cover — getaddrinfo returns parseable addresses
            continue
        if not is_public_ip(ip):
            # Names the resolved address: "it resolves to 127.0.0.1" is actionable, where a bare
            # "blocked" leaves the user unable to tell a misconfiguration from an attack.
            return ("BLOCKED_ADDRESS", f"{host} resolves to {ip}, which is not a public address")
    return None


def destination_refusal(url):
    """(code, detail) if `url` must not be retrieved, else None. Text check first, then DNS."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return None                          # no host to judge — fetch() answers this as BAD_URL
    literal = blocked_literal(host)
    if literal:
        return ("BLOCKED_ADDRESS", literal)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None                          # malformed port — let the connection attempt report it
    return resolve_refusal(host, port)


class _BlockedRedirect(Exception):
    """A redirect hop pointed somewhere non-public. Not a URLError subclass on purpose, so it can
    never be swallowed by fetch()'s existing network handlers."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


class _TooManyRedirects(Exception):
    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates every hop BEFORE it is followed, and counts them.

    urllib resolves a relative Location against the current URL before calling redirect_request, so
    `newurl` here is always absolute and can be judged directly. A fresh instance is built per fetch,
    which is what makes the hop counter correct under concurrent calls.
    """

    def __init__(self, allow_private=False, max_redirects=None):
        self.allow_private = allow_private
        # Read at CALL time, never frozen as a default argument: `max_redirects=MAX_REDIRECTS` in the
        # signature would snapshot the module global once at class-definition time, so rebinding it
        # (a test, a future config) would silently have no effect. Same defect the db_state default
        # carried — see its docstring.
        self.max_redirects = MAX_REDIRECTS if max_redirects is None else max_redirects
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > self.max_redirects:
            raise _TooManyRedirects(f"the page redirected more than {self.max_redirects} times")
        if not self.allow_private:
            refusal = destination_refusal(newurl)
            if refusal:
                # Distinct from BLOCKED_ADDRESS on purpose: the user's URL was fine and the SITE sent
                # them somewhere it shouldn't. Blaming the pasted link would be false.
                where = urlsplit(newurl).hostname or newurl
                raise _BlockedRedirect(f"the page redirected to {where}, which is not a public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetched(NamedTuple):
    """A page we actually got."""
    url: str                    # the FINAL url after redirects — this is source_url AND the dedup key
    html: str
    content_type: str
    encoding: str


class Refused(NamedTuple):
    """A page we did not get, and why. `code` is stable; `detail` is for humans."""
    code: str                   # BAD_URL | HTTP_ERROR | TIMEOUT | NETWORK_ERROR | NOT_HTML |
                                # TOO_LARGE | BLOCKED_ADDRESS | BLOCKED_REDIRECT | TOO_MANY_REDIRECTS
    detail: str
    url: str
    status: int = 0             # the HTTP status when there was one, else 0


def _read_capped(stream, limit):
    """Read at most `limit` bytes; return (data, overflowed). Reading limit+1 is how we detect
    'longer than the cap' without materialising the whole thing."""
    data = stream.read(limit + 1)
    return (data[:limit], True) if len(data) > limit else (data, False)


def fetch(url, *, timeout=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, allow_private=False):
    """Fetch `url`. Returns Fetched or Refused — never raises for an expected failure.

    allow_private=True disables the address guard ENTIRELY and exists for one reason: the transport
    tests serve from 127.0.0.1, which the guard refuses by design. Nothing in the app passes it — the
    import route calls fetch(url) and gets the guard. Do not reach for it to make a fetch "work".
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        # also keeps file:// and friends out of a user-supplied string
        return Refused("BAD_URL", "only http:// and https:// URLs can be imported", url)

    # Checked BEFORE any connection: a refused address costs no packets at all.
    if not allow_private:
        refusal = destination_refusal(url)
        if refusal:
            return Refused(refusal[0], refusal[1], url)

    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        # urllib does NOT decompress for us, so we only advertise what we decode below. Every one of
        # the 14 sampled pages came back gzipped, so this path is the normal case, not an edge case.
        "Accept-Encoding": "gzip",
    })

    # A per-call opener, so the hop counter belongs to THIS fetch. build_opener keeps every other
    # default handler and drops only the stock redirect handler our subclass replaces.
    opener = urllib.request.build_opener(GuardedRedirectHandler(allow_private))

    try:
        with opener.open(request, timeout=timeout) as response:
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

    except _BlockedRedirect as exc:
        return Refused("BLOCKED_REDIRECT", exc.detail, url)
    except _TooManyRedirects as exc:
        return Refused("TOO_MANY_REDIRECTS", exc.detail, url)
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
