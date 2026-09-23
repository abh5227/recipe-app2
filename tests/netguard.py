"""Suite-wide assertion that no test reaches the open internet.

WHY THIS EXISTS, WITH THE CASE THAT CAUSED IT. url_fetch.fetch is stubbed per test against U0's
committed fixtures, and that stub was believed to be the whole network boundary. It was not.
url_image.fetch_image is a SECOND transport path, which is the entire point of U3, so adding the
hero-image import quietly gave 10 commit tests a real connection to real recipe sites while their
own docstring said NO NETWORK. The suite stayed green, and the only visible symptom was 12 seconds
of extra runtime. Nothing in the suite would have caught it.

A stub protects the door it is nailed to. This protects the wall. Any future code that opens a new
way out fails on the first test that reaches it, rather than months later or never.

WHAT IS BLOCKED: a TCP connect to anything that is not loopback. That is the shape the real defect
took, and it is what a silent fetch of a third-party resource has to do.

WHAT IS NOT BLOCKED, DELIBERATELY:
  - loopback (127.0.0.0/8, ::1, localhost) — the url_fetch transport tests serve from a local
    HTTPServer on 127.0.0.1, and CI's Postgres suite connects to localhost:5432. Both are the
    machine talking to itself, which is not the risk.
  - AF_UNIX and anything whose address is not a host/port tuple.
  - NAME RESOLUTION. getaddrinfo does not go through socket.connect, so a DNS lookup still happens.
    Blocking it would break destination_refusal, whose whole job is to resolve a name before
    judging it, and a lookup does not retrieve the resource. The connect that WOULD retrieve it is
    blocked, which is where the damage lives.

HOW TO OPT IN: mark the test @pytest.mark.network. Nothing in this suite does, which is the point.
If something ever needs to, the marker makes that a visible, reviewable choice in the diff.
"""
import ipaddress
import socket

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex

_allowed = {"network": False}


class OutboundNetworkBlocked(BaseException):
    """⚠️ A BaseException ON PURPOSE, AND THE GUARD IS WORTHLESS OTHERWISE.

    The code under test is full of honest `except OSError` and `except Exception` handlers that turn
    a network failure into a graceful refusal, because that is exactly what they are supposed to do
    in production. If this inherited from Exception, url_image.fetch_image would catch it, report
    "could not reach the image", and the test would pass while the connection was being attempted
    for real. The guard has to be something no application handler can swallow.
    """


def _is_local(address):
    """Is this address the machine talking to itself? Anything else is outbound."""
    if not isinstance(address, tuple) or not address:
        return True                                  # AF_UNIX path, or something with no host
    host = address[0]
    if not isinstance(host, str) or host == "":
        return True
    host = host.split("%")[0]                        # drop an IPv6 zone id (fe80::1%lo0)
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False                                 # a NAME that is not localhost: treat as outbound


def _refuse(address):
    raise OutboundNetworkBlocked(
        f"a test tried to open a connection to {address!r}. The suite does not reach the network: "
        f"stub the transport (see conftest.no_image_network) or, if this test genuinely needs the "
        f"internet, mark it @pytest.mark.network."
    )


def _guarded_connect(self, address):
    if not _allowed["network"] and not _is_local(address):
        _refuse(address)
    return _REAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    if not _allowed["network"] and not _is_local(address):
        _refuse(address)
    return _REAL_CONNECT_EX(self, address)


def install():
    """Patch the class, once, at conftest import — early enough to cover collection too."""
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def uninstall():
    socket.socket.connect = _REAL_CONNECT
    socket.socket.connect_ex = _REAL_CONNECT_EX


def set_allowed(value):
    """Flipped per test by conftest's autouse fixture, from the @pytest.mark.network marker."""
    _allowed["network"] = bool(value)


def is_allowed():
    return _allowed["network"]
