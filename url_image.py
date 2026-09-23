"""URL import, stage 3 (U3): fetch the page's hero photo. A SIBLING of url_fetch, never a wider gate.

url_jsonld already extracts the candidate urls (pure, no network). This module turns that list into
ONE stored hero, or into a reason there is none. It runs AFTER the recipe row is committed, so every
failure here is a returned value and nothing in it can raise into the import.

⚠️ WHY THIS IS NOT JUST url_fetch.fetch WITH A WIDER HTML_TYPES. fetch() reads the Content-Type
BEFORE the body and refuses anything that is not HTML, which is the whole reason a pasted PDF or
video costs nothing. Widening HTML_TYPES to admit images would hand that same permission to the
RECIPE reader, so a pasted .jpg would be downloaded and then fail further in. What is worth sharing
is not the gate, it is the address guard, and destination_refusal + GuardedRedirectHandler are
IMPORTED here rather than re-implemented. One copy of the classification, the same discipline
blocked_literal already keeps for app.private_host_refusal.

⚠️ AND THE ADDRESS GUARD MATTERS MORE HERE THAN IT DOES THERE. The recipe url was typed by the user.
These urls were published by the page they typed, so they are attacker-influenced in a way the first
one is not. A page is free to say "image": "http://169.254.169.254/latest/meta-data/…" and the
server would retrieve it from inside the perimeter. That is exactly what U0b exists for, so every
candidate is judged before a packet is sent and every redirect hop is re-judged.
"""
import io
import socket
import urllib.error
import urllib.request
import warnings
from typing import NamedTuple
from urllib.parse import urlsplit

from PIL import Image

import images
import url_fetch
from url_fetch import Refused, destination_refusal

# Measured across the 9 Recipe-bearing fixtures by fetching EVERY candidate url, 13 images in all:
# the largest source as published is 548,102 bytes (nytimes, 1600x900) and the median is 129,583.
# 4MiB is ~7.6x the largest, which is the same headroom url_fetch's 8MiB gives its 1.4MB largest
# page. Sized from that measurement rather than copied across from the HTML cap: a hero is a photo,
# not a document.
MAX_IMAGE_BYTES = 4 * 1024 * 1024

# The bar a candidate has to clear to be taken on sight. Heroes are stored at images.LONG_EDGE
# (1600), so anything under a few hundred pixels is a thumbnail pretending to be a photograph.
# 800 is half of LONG_EDGE: comfortably usable, and low enough that the 6 of 9 fixtures whose first
# candidate is already the full-size image still cost exactly one fetch.
MIN_LONG_EDGE = 800

# A CHEAP PRE-FILTER, NEVER THE ACCEPTANCE TEST. Read before the body, so a PDF served at an image
# url costs no download. What actually decides is images._validate, which accepts only what Pillow
# DECODES as JPEG/PNG/WEBP/HEIF and ignores the declared type entirely (images.py S3). This one
# bounds the download, that one bounds what reaches the disk.
IMAGE_TYPES = ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif")


class FetchedImage(NamedTuple):
    url: str                    # the FINAL url after redirects
    data: bytes
    content_type: str


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
def fetch_image(url, *, timeout=url_fetch.TIMEOUT_SECONDS, max_bytes=MAX_IMAGE_BYTES,
                allow_private=False):
    """Fetch one image url. Returns FetchedImage or Refused, never raising for an expected failure.

    allow_private=True disables the address guard ENTIRELY, exactly as in url_fetch.fetch and for
    exactly the same single reason: the transport tests serve from 127.0.0.1, which the guard
    refuses by design. Nothing in the app passes it.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        # Also keeps data:, file: and friends out of a value the PAGE chose.
        return Refused("BAD_URL", "only http:// and https:// images can be fetched", url)

    if not allow_private:
        refusal = destination_refusal(url)          # resolve-then-check, before any packet
        if refusal:
            return Refused(refusal[0], refusal[1], url)

    request = urllib.request.Request(url, headers={
        "User-Agent": url_fetch.USER_AGENT,
        "Accept": "image/*",
        # NO Accept-Encoding: gzip, unlike the HTML path. Images are already compressed and every
        # sampled response came back uncompressed, so not advertising it leaves this path with no
        # decompression step at all and therefore no gzip bomb to bound a second time.
    })
    opener = urllib.request.build_opener(url_fetch.GuardedRedirectHandler(allow_private))

    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in IMAGE_TYPES:
                return Refused("NOT_AN_IMAGE", f"the url returned {content_type}, not an image",
                               response.url, response.status)
            raw, too_big = url_fetch._read_capped(response, max_bytes)
            if too_big:
                return Refused("TOO_LARGE", f"the image is larger than {max_bytes // (1024 * 1024)}MB",
                               response.url, response.status)
            return FetchedImage(response.url, raw, content_type)

    except url_fetch._BlockedRedirect as exc:
        return Refused("BLOCKED_REDIRECT", exc.detail, url)
    except url_fetch._TooManyRedirects as exc:
        return Refused("TOO_MANY_REDIRECTS", exc.detail, url)
    except urllib.error.HTTPError as exc:
        return Refused("HTTP_ERROR", f"the image host refused the request (HTTP {exc.code})", url, exc.code)
    except socket.timeout:
        return Refused("TIMEOUT", f"the image host did not respond within {timeout}s", url)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            return Refused("TIMEOUT", f"the image host did not respond within {timeout}s", url)
        return Refused("NETWORK_ERROR", f"could not reach the image: {exc.reason}", url)
    except (OSError, ValueError) as exc:
        return Refused("NETWORK_ERROR", f"could not reach the image: {exc}", url)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #
def decoded_size(data):
    """(width, height) read from the REAL pixels, or None if these bytes are not a usable image.

    ⚠️ THE DECLARED DIMENSIONS ARE NOT USED, AND THAT IS THE POINT OF THIS FUNCTION. Half the
    fixtures publish width/height in their JSON-LD and half do not: kingarthurbaking declares both
    as null, and every list-of-string form declares nothing at all. A publisher is also free to be
    wrong. Opening the bytes is the only answer that is true for all nine.

    Image.open reads the header without decoding pixels, so this is cheap. It still carries the
    decompression-bomb guard, and the warning-as-error filter mirrors images._validate exactly, so
    a candidate that save_cook_photo would later reject is rejected here instead of being chosen and
    then thrown away.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return Image.open(io.BytesIO(data)).size
    except Exception:
        return None


class Hero(NamedTuple):
    url: str
    data: bytes
    size: tuple                 # (width, height) as DECODED
    tried: int                  # how many candidates were fetched to get here


def pick_hero(urls, *, min_long_edge=MIN_LONG_EDGE, allow_private=False, fetcher=None):
    """The candidate list -> the one to store, or Refused. Fetches in ORDER and stops early.

    THE RULE. Take the first candidate whose DECODED longest edge is at least min_long_edge. If none
    clears it, take the largest that decoded at all. Never return empty-handed over size alone: a
    small hero beats no hero, and the reader can replace it from the existing upload route.

    WHY ORDER AND NOT ALL. A multi-entry list is one photograph at several crops, measured across
    the four fixtures that publish one, so the choice is about SIZE and never about which picture.
    Element [0] is the publisher's own first answer and it clears the bar on 6 of 9 fixtures, so
    stopping early costs one fetch in the ordinary case. The exception is real: hot-thai-kitchen
    publishes 225x225, 260x195 and 320x180 before its 1200x1200, so bare [0] stores a thumbnail
    against a LONG_EDGE of 1600. That is the case this rule exists for.

    `fetcher` is an injection seam for the tests, which have no network. The app passes nothing.
    """
    get = fetcher or (lambda u: fetch_image(u, allow_private=allow_private))
    best = None
    first_refusal = None
    tried = 0
    for url in urls or []:
        got = get(url)
        tried += 1
        if isinstance(got, Refused):
            if first_refusal is None:
                first_refusal = got
            continue
        size = decoded_size(got.data)
        if size is None:
            if first_refusal is None:
                first_refusal = Refused("BAD_IMAGE", "the bytes did not decode as an image", url)
            continue
        if max(size) >= min_long_edge:
            return Hero(got.url, got.data, size, tried)         # STOP. No further candidate is fetched.
        if best is None or max(size) > max(best.size):
            best = Hero(got.url, got.data, size, tried)
    if best is not None:
        return best._replace(tried=tried)                       # the fallback: largest that decoded
    if first_refusal is not None:
        return first_refusal
    return Refused("NO_IMAGE", "the page's recipe carried no image", "")


# --------------------------------------------------------------------------- #
# The after-commit step
# --------------------------------------------------------------------------- #
class HeroResult(NamedTuple):
    """What happened. `path` is set only on success, `code` is "" on success and the reason otherwise."""
    path: str
    code: str
    detail: str
    size: tuple = ()
    tried: int = 0


def attach_hero(set_hero, urls, *, allow_private=False, fetcher=None):
    """Pick a hero from `urls`, harden it through images.save_cook_photo, call set_hero(path).

    ⚠️ NEVER RAISES, AND THAT IS THE WHOLE CONTRACT. import_commit's session ends with "nothing above
    committed - a raise leaves NO row", which is right for the recipe and wrong for its picture. The
    image lives on a third-party host, so it can answer 404, time out or be refused long after the
    recipe itself is perfect. Inside the transaction a dead image url throws away a good import.
    Outside it the same failure leaves the recipe hero-less, which is the state most recipes are
    already in and which the existing upload route already fixes by hand. So this is called AFTER the
    commit, and every failure is a returned code, because the caller is a route that already answered
    201.
    """
    if not urls:
        return HeroResult("", "NO_IMAGE", "the page's recipe carried no image")

    picked = pick_hero(urls, allow_private=allow_private, fetcher=fetcher)
    if isinstance(picked, Refused):
        return HeroResult("", picked.code, picked.detail)

    try:
        # The SAME storage seam the upload route uses (app.upload_recipe_image): validate by
        # DECODING, re-encode to a metadata-free JPEG, downscale to LONG_EDGE, write atomically
        # under a server-minted uuid. Bytes off the open internet get exactly the hardening bytes
        # off the user's phone get, bomb guard included.
        path = images.save_cook_photo(picked.data)
    except images.ImageValidationError as exc:
        return HeroResult("", "BAD_IMAGE", str(exc), picked.size, picked.tried)
    except Exception as exc:                          # disk full, permissions, anything at all
        return HeroResult("", "STORE_FAILED", f"{type(exc).__name__}: {exc}", picked.size, picked.tried)

    try:
        set_hero(path)                                # the DB write LAST: the file is on disk first (S6)
    except Exception as exc:
        return HeroResult("", "DB_FAILED", f"{type(exc).__name__}: {exc}", picked.size, picked.tried)
    return HeroResult(path, "", "", picked.size, picked.tried)
