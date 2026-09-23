"""The suite-wide no-network guard, tested like anything else.

A guard nobody exercises is a guard nobody knows is off. These pin that it bites, that application
error handling cannot swallow it, that the machine can still talk to itself, and that the one
documented way past it works.
"""
import http.server
import socket
import threading
import urllib.error
import urllib.request

import pytest

import netguard
import url_fetch
import url_image

_REAL_FETCH_IMAGE = url_image.fetch_image      # before conftest's no_image_network stub


# --------------------------------------------------------------------- it bites
def test_an_outbound_connection_is_refused():
    with pytest.raises(netguard.OutboundNetworkBlocked) as exc:
        socket.create_connection(("93.184.216.34", 80), timeout=2)     # a public address, by number
    assert "does not reach the network" in str(exc.value)


def test_an_outbound_connection_by_NAME_is_refused_too():
    """Resolution is allowed and the connect is not, so a hostname gets no further than a literal."""
    with pytest.raises(netguard.OutboundNetworkBlocked):
        urllib.request.urlopen("https://www.kingarthurbaking.com/", timeout=2)


def test_the_guard_cannot_be_swallowed_by_ordinary_error_handling():
    """⚠️ THE REASON IT IS A BaseException. The code under test is full of honest `except OSError`
    and `except Exception` handlers that turn a network failure into a graceful refusal, which is
    exactly right in production. If this were an Exception, every one of them would catch the guard,
    report "could not reach the site", and let the test pass while the connection was attempted."""
    assert not issubclass(netguard.OutboundNetworkBlocked, Exception)
    with pytest.raises(netguard.OutboundNetworkBlocked):
        try:
            socket.create_connection(("93.184.216.34", 80), timeout=2)
        except Exception:                                              # noqa: BLE001 - the point
            pytest.fail("an `except Exception` swallowed the guard")


def test_the_hero_fetch_is_caught_by_the_wall_and_not_only_by_its_stub(monkeypatch):
    """THE REGRESSION THIS EXISTS FOR. url_image.fetch_image is a second transport path, invisible
    to the url_fetch.fetch stub, and 10 commit tests were retrieving real photos through it. With
    the per-test stub removed, the wall behind it still stops the call."""
    monkeypatch.setattr(url_image, "fetch_image", _REAL_FETCH_IMAGE)   # drop conftest's stub
    with pytest.raises(netguard.OutboundNetworkBlocked):
        url_image.fetch_image("https://www.kingarthurbaking.com/hero.jpg", timeout=2)


# ------------------------------------------------------- the machine talks to itself
def test_loopback_still_works_because_that_is_not_the_risk():
    """The url_fetch transport tests serve from 127.0.0.1 and CI's Postgres suite connects to
    localhost:5432. Blocking those would break the suite without closing anything."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = b"<html><body>local</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        got = url_fetch.fetch(f"http://127.0.0.1:{port}/", allow_private=True)
        assert isinstance(got, url_fetch.Fetched) and "local" in got.html
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("address,local", [
    (("127.0.0.1", 80), True),
    (("127.0.0.53", 53), True),
    (("::1", 80), True),
    (("fe80::1%lo0", 80), False),          # link-local is not loopback
    (("localhost", 5432), True),
    (("db.localhost", 5432), True),
    (("", 0), True),
    ("/var/run/some.sock", True),          # AF_UNIX: not a tuple
    (("10.0.0.1", 80), False),
    (("93.184.216.34", 443), False),
    (("example.com", 443), False),
])
def test_what_counts_as_local(address, local):
    assert netguard._is_local(address) is local


# ------------------------------------------------------------------- the opt-in
def test_no_test_in_this_suite_opts_in():
    """The marker exists so that needing the internet is a visible choice in a diff. Today nothing
    needs it, and the full suite runs with zero outbound connections."""
    assert netguard.is_allowed() is False


@pytest.mark.network
def test_the_marker_is_the_documented_way_past_the_guard():
    """Asserts the wiring, not a real connection: this suite has nothing to legitimately call, and a
    test that reached a third-party host to prove it could would be the very thing being guarded."""
    assert netguard.is_allowed() is True
