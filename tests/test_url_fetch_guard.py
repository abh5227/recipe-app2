"""U0b: the server-side fetch guard — resolve-then-check, and every redirect hop.

REAL SOCKETS, NO MOCKS, matching test_url_fetch.py's approach: the thing being guarded IS transport
behaviour, and a mock of urllib would test the mock. The local server here issues genuine 302s to
genuine addresses, and DNS is steered by monkeypatching socket.getaddrinfo — the one seam that cannot
be driven from a test otherwise, since a test cannot publish an A record.

The guard refuses loopback, so these tests serve from 127.0.0.1 and drive the guard by pointing a
NAME at it. That is also the real attack: evil.example.com with an A record of 127.0.0.1.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import app
import url_fetch

PAGE = "<!DOCTYPE html><html><body>guarded</body></html>"


class Handler(BaseHTTPRequestHandler):
    """Redirect chains: /hopN steps to /hop(N+1), and /hop20 lands on /end."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/hop"):
            n = int(self.path[4:])
            self.send_response(302)
            self.send_header("Location", f"/hop{n + 1}" if n < 20 else "/end")
            self.end_headers()
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture
def dns(monkeypatch):
    """Steer getaddrinfo per hostname. Any name not in the map resolves for real.

    Returns the map so a test can say 'evil.test resolves to 127.0.0.1' — which is precisely the
    gap U4's text-only pre-filter could never see.
    """
    mapping = {}
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in mapping:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port))
                    for addr in mapping[host]]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return mapping


# --------------------------------------------------------------------------- #
# 1. Resolve-then-check: a NAME pointing somewhere private
# --------------------------------------------------------------------------- #
def test_a_name_resolving_to_loopback_is_refused(dns, server):
    """GAP 1, NOW CLOSED. Before U0b this was fetched: the URL text says 'evil.test', which no
    literal check can fault, and only resolution reveals 127.0.0.1."""
    dns["evil.test"] = ["127.0.0.1"]
    got = url_fetch.fetch(f"http://evil.test:{server}/")
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BLOCKED_ADDRESS"
    assert "evil.test resolves to 127.0.0.1" in got.detail


@pytest.mark.parametrize("addr,label", [
    ("127.0.0.1", "loopback"), ("10.0.0.5", "private 10/8"), ("192.168.1.7", "private 192.168/16"),
    ("172.16.3.4", "private 172.16/12"), ("169.254.169.254", "link-local / cloud metadata"),
    ("0.0.0.0", "unspecified"), ("::1", "IPv6 loopback"), ("fd00::1", "IPv6 unique-local"),
])
def test_names_resolving_into_any_non_public_range_are_refused(dns, addr, label):
    dns["lookup.test"] = [addr]
    got = url_fetch.fetch("http://lookup.test/recipe")
    assert isinstance(got, url_fetch.Refused), label
    assert got.code == "BLOCKED_ADDRESS", label


def test_a_multi_homed_name_is_refused_on_its_private_address(dns):
    """A public address does not redeem the private one. Accepting on the strength of the first
    public answer is the classic bypass: publish 8.8.8.8 AND 127.0.0.1, let the checker see the
    public one and the connection pick the other."""
    dns["both.test"] = ["93.184.216.34", "127.0.0.1"]
    got = url_fetch.fetch("http://both.test/recipe")
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BLOCKED_ADDRESS" and "127.0.0.1" in got.detail


def test_the_private_address_is_refused_whichever_order_dns_returns_it(dns):
    dns["both.test"] = ["127.0.0.1", "93.184.216.34"]
    assert url_fetch.fetch("http://both.test/recipe").code == "BLOCKED_ADDRESS"


def test_a_wholly_public_name_passes_the_guard(dns):
    """The guard must not become a blanket refusal. Asserts the VERDICT rather than completing a
    fetch, because a name that resolves public cannot also reach the loopback test server — the two
    requirements are contradictory, and the live-network test in test_url_fetch.py covers the rest."""
    dns["good.test"] = ["93.184.216.34"]
    assert url_fetch.destination_refusal("http://good.test/recipe") is None


def test_an_unresolvable_name_is_a_network_error_not_a_block(dns):
    """A typo must read as 'could not reach the site', never as 'that address is private' — the
    second would send the user hunting for a problem that isn't there."""
    got = url_fetch.fetch("http://no-such-host.invalid/recipe")
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "NETWORK_ERROR"


def test_an_ip_literal_is_still_refused_without_any_lookup(dns):
    """The text check runs first, so a literal costs no DNS at all. dns is empty, so a lookup would
    hit the real resolver — the assertion is that the code path never gets there."""
    got = url_fetch.fetch("http://169.254.169.254/latest/meta-data/")
    assert got.code == "BLOCKED_ADDRESS"
    assert got.detail == url_fetch.PRIVATE_NETWORK


# --------------------------------------------------------------------------- #
# 2. The redirect guard: every hop, not just the first
# --------------------------------------------------------------------------- #
# HOW THIS SECTION PROVES "EVERY HOP IS CHECKED", given that it cannot be done in one test:
# a hop can only be reached from an entry point that PASSES the guard, and no address a test can
# serve from is public. So the claim is proved in two halves that meet in the middle:
#   (a) redirect_request REFUSES a non-public Location — tested directly below, on the real method
#       with the real absolute url urllib hands it.
#   (b) redirect_request IS CALLED by urllib on every hop of a real fetch — proved by the hop
#       counter, which lives inside that method and can only fire if urllib called it 11 times.
# Together those are the guarantee. Neither half alone would be.
def test_a_redirect_to_a_private_address_is_refused():
    """GAP 2, NOW CLOSED — the one that mattered most, because the destination is one the USER never
    chose. A page 302s to the cloud metadata endpoint; the hop is judged before it is followed."""
    handler = url_fetch.GuardedRedirectHandler(allow_private=False)
    with pytest.raises(Exception) as exc:
        handler.redirect_request(None, None, 302, "Found", {},
                                 "http://169.254.169.254/latest/meta-data/")
    assert "redirected to 169.254.169.254" in str(exc.value)
    assert "not a public address" in str(exc.value)


def test_a_redirect_to_a_name_that_resolves_private_is_refused(dns):
    """The hop check resolves too — a redirect to a NAME gets the same treatment as the entry url."""
    dns["sneaky.test"] = ["10.1.2.3"]
    handler = url_fetch.GuardedRedirectHandler(allow_private=False)
    with pytest.raises(Exception) as exc:
        handler.redirect_request(None, None, 302, "Found", {}, "http://sneaky.test/x")
    assert "redirected to sneaky.test" in str(exc.value)


def test_the_refusal_blames_the_site_not_the_pasted_link(dns):
    """Distinct wording from BLOCKED_ADDRESS on purpose: the user's URL was fine and the SITE sent
    them somewhere it shouldn't. Telling them their link was bad would be false."""
    handler = url_fetch.GuardedRedirectHandler(allow_private=False)
    with pytest.raises(Exception) as exc:
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/x")
    assert "redirected to" in str(exc.value)
    assert url_fetch.PRIVATE_NETWORK not in str(exc.value)


def test_a_public_redirect_chain_still_works_and_reports_the_final_url(server):
    """Redirects that stay allowed MUST still be followed — the URL after redirects is the dedup key
    (test_url_fetch.test_captures_the_url_after_redirects), so breaking this would break dedup."""
    got = url_fetch.fetch(f"http://127.0.0.1:{server}/hop18", allow_private=True)   # 3 hops -> /end
    assert isinstance(got, url_fetch.Fetched)
    assert got.url.endswith("/end")
    assert "guarded" in got.html


def test_urllib_really_calls_the_guard_on_every_hop(server):
    """Half (b): a 20-hop chain trips the counter that lives INSIDE redirect_request. It can only
    fire if urllib invoked that method on hop after hop of a real fetch — which is what makes the
    per-hop refusal above a guarantee rather than an untested method."""
    got = url_fetch.fetch(f"http://127.0.0.1:{server}/hop1", allow_private=True)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "TOO_MANY_REDIRECTS"
    assert f"more than {url_fetch.MAX_REDIRECTS} times" in got.detail


def test_the_limit_is_read_at_call_time_not_frozen(server, monkeypatch):
    """Pins the call-time read. A `max_redirects=MAX_REDIRECTS` default argument would snapshot the
    global once at class-definition time and this rebinding would silently do nothing."""
    monkeypatch.setattr(url_fetch, "MAX_REDIRECTS", 3)
    got = url_fetch.fetch(f"http://127.0.0.1:{server}/hop1", allow_private=True)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "TOO_MANY_REDIRECTS" and "more than 3 times" in got.detail


def test_urllibs_own_default_is_the_same_ten(server):
    """MAX_REDIRECTS matches urllib's HTTPRedirectHandler.max_redirections. Enforcing our own is not
    a tightening — it is what turns exhaustion into a refusal VALUE with its own code instead of an
    HTTPError that would surface as a misleading HTTP_ERROR."""
    import urllib.request
    assert url_fetch.MAX_REDIRECTS == urllib.request.HTTPRedirectHandler.max_redirections == 10


def test_the_hop_counter_is_per_fetch(server):
    """A shared counter would leak between calls and refuse the second short chain. Each fetch builds
    its own handler, so three separate chains all succeed."""
    for _ in range(3):
        got = url_fetch.fetch(f"http://127.0.0.1:{server}/hop18", allow_private=True)
        assert isinstance(got, url_fetch.Fetched), got


# --------------------------------------------------------------------------- #
# 3. The shared classification (one copy, two callers)
# --------------------------------------------------------------------------- #
def test_the_route_prefilter_delegates_to_the_fetcher(dns):
    """app.private_host_refusal is now a thin wrapper. Pinned so a future edit cannot reintroduce a
    second copy that drifts from url_fetch's."""
    for host in ("localhost", "127.0.0.1", "10.0.0.1", "169.254.169.254"):
        assert app.private_host_refusal(f"http://{host}/x") is not None
    for host in ("example.com", "8.8.8.8"):
        assert app.private_host_refusal(f"http://{host}/x") is None


def test_the_route_prefilter_still_does_not_resolve(dns):
    """DELIBERATE, and no longer a gap: the pre-filter is a cheap text check that saves a network
    call on an obvious paste. The NAME case is caught one layer down, in url_fetch — which is what
    the next assertion proves."""
    dns["evil.test"] = ["127.0.0.1"]
    assert app.private_host_refusal("http://evil.test/x") is None      # text alone cannot tell
    assert url_fetch.destination_refusal("http://evil.test/x")[0] == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("host,expected", [
    ("localhost", url_fetch.ON_THIS_MACHINE), ("LOCALHOST", url_fetch.ON_THIS_MACHINE),
    ("foo.localhost", url_fetch.ON_THIS_MACHINE), ("localhost.", url_fetch.ON_THIS_MACHINE),
    ("127.0.0.1", url_fetch.PRIVATE_NETWORK), ("::1", url_fetch.PRIVATE_NETWORK),
    ("example.com", None), ("8.8.8.8", None), ("", None), (None, None),
])
def test_blocked_literal_classifies_from_text_alone(host, expected):
    assert url_fetch.blocked_literal(host) == expected
