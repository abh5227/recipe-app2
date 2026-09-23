"""U3: the hero-image fetch path. No network — every test injects its own fetcher.

Two things are proved here. The SELECTION rule, which is the only new judgement in the module, and
the ADDRESS GUARD, which is shared with url_fetch and must keep biting when it is reached through
this door instead of that one.
"""
import io
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import images
import url_fetch
import url_image


def jpeg(w, h):
    """Real bytes at a real size, so decoded_size reads pixels rather than a promise."""
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (180, 90, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def served(**by_url):
    """A fetcher that answers from a dict. A value may be bytes or a Refused."""
    calls = []

    def fetcher(url):
        calls.append(url)
        value = by_url[url]
        if isinstance(value, url_fetch.Refused):
            return value
        return url_image.FetchedImage(url, value, "image/jpeg")

    fetcher.calls = calls
    return fetcher


# ------------------------------------------------------------------ selection
def test_the_first_candidate_over_the_bar_wins_and_nothing_after_it_is_fetched():
    """The ordinary case, 6 of the 9 fixtures: the publisher's first answer is already full size,
    so the import costs exactly one request."""
    f = served(**{"a": jpeg(1500, 1125), "b": jpeg(800, 600), "c": jpeg(400, 300)})
    got = url_image.pick_hero(["a", "b", "c"], fetcher=f)
    assert got.size == (1500, 1125)
    assert f.calls == ["a"]                      # b and c were never retrieved
    assert got.tried == 1


def test_the_hot_thai_kitchen_shape_skips_three_thumbnails_and_takes_the_full_size():
    """THE CASE THE RULE EXISTS FOR. Measured off the real fixture: 225x225, 260x195 and 320x180 are
    published before the 1200x1200. Bare [0] stores a thumbnail against a LONG_EDGE of 1600."""
    f = served(**{"t1": jpeg(225, 225), "t2": jpeg(260, 195), "t3": jpeg(320, 180),
                  "full": jpeg(1200, 1200)})
    got = url_image.pick_hero(["t1", "t2", "t3", "full"], fetcher=f)
    assert got.size == (1200, 1200)
    assert got.tried == 4
    assert f.calls == ["t1", "t2", "t3", "full"]


def test_a_landscape_clears_on_its_LONGEST_edge_not_its_shortest():
    """thewoksoflife's first candidate is 650x824. The short edge is under the bar and the long edge
    is over it, and it is the full-size image, so the long edge is what counts."""
    f = served(**{"a": jpeg(650, 824)})
    assert url_image.pick_hero(["a"], fetcher=f).size == (650, 824)


def test_when_nothing_clears_the_bar_the_largest_is_taken_rather_than_none():
    """⚠️ NEVER HERO-LESS OVER SIZE ALONE. bbcgoodfood publishes one 440x400 and minimalistbaker one
    550x550. A small hero beats no hero, and the upload route already replaces one by hand."""
    f = served(**{"a": jpeg(300, 300), "b": jpeg(550, 550), "c": jpeg(420, 420)})
    got = url_image.pick_hero(["a", "b", "c"], fetcher=f)
    assert got.size == (550, 550)
    assert f.calls == ["a", "b", "c"]            # no early stop is possible when none clears
    assert got.tried == 3


def test_the_bar_is_inclusive_at_800():
    f = served(**{"a": jpeg(800, 100)})
    got = url_image.pick_hero(["a"], fetcher=f)
    assert got.size == (800, 100) and got.tried == 1


def test_a_refused_candidate_is_skipped_and_the_next_one_is_taken():
    f = served(**{"gone": url_fetch.Refused("HTTP_ERROR", "404", "gone", 404),
                  "good": jpeg(1000, 1000)})
    got = url_image.pick_hero(["gone", "good"], fetcher=f)
    assert got.size == (1000, 1000) and got.tried == 2


def test_bytes_that_do_not_decode_are_skipped_rather_than_stored():
    f = served(**{"lie": b"%PDF-1.4 not a photograph", "good": jpeg(900, 900)})
    assert url_image.pick_hero(["lie", "good"], fetcher=f).size == (900, 900)


def test_when_every_candidate_fails_the_first_reason_is_the_one_reported():
    blocked = url_fetch.Refused("BLOCKED_ADDRESS", "that address is on this machine", "a")
    f = served(**{"a": blocked, "b": url_fetch.Refused("TOO_LARGE", "too big", "b")})
    got = url_image.pick_hero(["a", "b"], fetcher=f)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BLOCKED_ADDRESS"


def test_an_empty_candidate_list_is_NO_IMAGE_and_not_an_error():
    got = url_image.pick_hero([], fetcher=served())
    assert isinstance(got, url_fetch.Refused) and got.code == "NO_IMAGE"


# ------------------------------------------------------------------ the guard
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam/",    # cloud metadata, the classic target
    "http://127.0.0.1:8000/api/recipes",               # the app's own API
    "http://10.0.0.5/admin/backup.jpg",
    "http://192.168.1.1/router-config.png",
    "http://[::1]:8000/secrets.jpg",
    "http://localhost:5432/",
    "http://0.0.0.0/",
])
def test_a_page_cannot_make_the_server_fetch_a_private_address(url):
    """⚠️ THE POINT OF THE MODULE. These urls are published by the PAGE, not typed by the user, so
    they are attacker-influenced in a way the pasted recipe url is not. Refused before any packet."""
    got = url_image.fetch_image(url, timeout=5)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BLOCKED_ADDRESS"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "data:image/png;base64,iVBORw0KGgo=",
                                 "ftp://example.com/hero.jpg", "not a url at all"])
def test_only_http_and_https_are_fetchable(url):
    got = url_image.fetch_image(url, timeout=5)
    assert isinstance(got, url_fetch.Refused) and got.code == "BAD_URL"


def test_the_guard_resolves_the_name_rather_than_reading_it(monkeypatch):
    """A public-LOOKING name is not a public destination. evil.test can hold an A record of
    127.0.0.1, so the hostname is resolved and every address it returns is checked."""
    import socket as real_socket
    monkeypatch.setattr(url_fetch.socket, "getaddrinfo",
                        lambda host, port, **kw: [(real_socket.AF_INET, real_socket.SOCK_STREAM,
                                                   6, "", ("169.254.169.254", port))])
    got = url_image.fetch_image("http://totally-ordinary-cdn.test/hero.jpg", timeout=5)
    assert isinstance(got, url_fetch.Refused)
    assert got.code == "BLOCKED_ADDRESS" and "169.254.169.254" in got.detail


def test_the_guard_is_url_fetchs_own_and_not_a_second_copy():
    """If these ever drift apart, one door is shut and the other is open."""
    assert url_image.destination_refusal is url_fetch.destination_refusal


# ------------------------------------------------------------------ decoding
def test_decoded_size_reads_pixels_and_returns_none_for_anything_else():
    assert url_image.decoded_size(jpeg(120, 340)) == (120, 340)
    assert url_image.decoded_size(b"") is None
    assert url_image.decoded_size(b"%PDF-1.4") is None


def test_a_decompression_bomb_is_rejected_at_the_measuring_step(tmp_path):
    """Measuring has to be as strict as storing, or a bomb gets chosen and then thrown away."""
    code = ("import io,sys\nfrom PIL import Image\nImage.MAX_IMAGE_PIXELS=None\n"
            "b=io.BytesIO()\nImage.new('RGB',(10000,10000),(9,9,9)).save(b,format='PNG')\n"
            "sys.stdout.buffer.write(b.getvalue())\n")
    bomb = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True).stdout
    assert url_image.decoded_size(bomb) is None


# ------------------------------------------------------------------ attach_hero
def test_attach_hero_stores_through_the_real_seam_and_reports_the_path(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "IMAGES_DIR", Path(tmp_path) / "images")
    written = []
    got = url_image.attach_hero(written.append, ["a"], fetcher=served(**{"a": jpeg(1200, 900)}))
    assert got.code == "" and got.path.startswith("images/cooks/") and got.path.endswith(".jpg")
    assert written == [got.path]
    stored = (Path(tmp_path) / "images") / got.path[len("images/"):]
    assert stored.is_file()
    assert Image.open(stored).format == "JPEG"       # re-encoded, which is what strips EXIF/GPS


def test_attach_hero_never_raises_when_the_db_write_fails(tmp_path, monkeypatch):
    """The caller is a route that has already answered 201. Nothing here may raise into it."""
    monkeypatch.setattr(images, "IMAGES_DIR", Path(tmp_path) / "images")

    def boom(_path):
        raise RuntimeError("database is locked")

    got = url_image.attach_hero(boom, ["a"], fetcher=served(**{"a": jpeg(1000, 1000)}))
    assert got.code == "DB_FAILED" and "database is locked" in got.detail


def test_attach_hero_never_raises_when_the_bytes_are_not_an_image(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "IMAGES_DIR", Path(tmp_path) / "images")
    got = url_image.attach_hero(lambda p: None, ["a"], fetcher=served(**{"a": b"not an image"}))
    assert got.code in ("BAD_IMAGE", "NO_IMAGE") and got.path == ""


def test_attach_hero_with_no_candidates_is_a_quiet_NO_IMAGE():
    got = url_image.attach_hero(lambda p: None, [])
    assert got.code == "NO_IMAGE" and got.path == ""
