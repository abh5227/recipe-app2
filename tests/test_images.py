"""Stage 1 of the photo uploader: the shared resize core (images.resize_image_bytes), extracted from
scripts/backfill_photos.py. Pins the resize contract (downscale long edge to 1600, never upscale,
EXIF-oriented, RGB, JPEG q85) and asserts the backfill's process_photo stays behavior-preserving
through the extracted helper. Synthesizes inputs with Pillow — no fixtures, no DB.

Scope of proof: the extraction is verified behavior-preserving by DIMENSION + CONTRACT equivalence
(and the moved code being verbatim), NOT by a byte-for-byte golden comparison against the pre-extraction
output — overkill for a transparent refactor whose observable contract is (jpeg_bytes, orig, new)."""
import io
import sys
import base64
from pathlib import Path

from PIL import Image

import images   # root shared module (Stage 1)


def _img_bytes(size, mode="RGB", exif_orientation=None):
    im = Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else "red")
    buf = io.BytesIO()
    if exif_orientation is not None:
        ex = im.getexif(); ex[274] = exif_orientation           # 274 = EXIF Orientation
        im.save(buf, format="JPEG", exif=ex)
    else:
        im.save(buf, format="PNG" if mode in ("RGBA", "P") else "JPEG")
    return buf.getvalue()


def _open(b):
    return Image.open(io.BytesIO(b))


def test_oversized_downscaled_to_long_edge_1600_aspect_kept():
    im = _open(images.resize_image_bytes(_img_bytes((2000, 1000))))
    assert im.format == "JPEG"
    assert max(im.size) == 1600
    assert im.size == (1600, 800)               # aspect preserved


def test_small_image_not_upscaled():
    im = _open(images.resize_image_bytes(_img_bytes((800, 600))))
    assert im.size == (800, 600)                # unchanged — never upscale


def test_non_rgb_converted_to_rgb():
    im = _open(images.resize_image_bytes(_img_bytes((100, 100), mode="RGBA")))
    assert im.format == "JPEG" and im.mode == "RGB"   # JPEG can't hold alpha


def test_exif_orientation_applied():
    # orientation 6 = rotate 90°, so a 100x50 source comes out 50x100 (transposed)
    assert _open(images.resize_image_bytes(_img_bytes((100, 50), exif_orientation=6))).size == (50, 100)


def _process_photo():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import backfill_photos
    return backfill_photos.process_photo


def test_backfill_process_photo_behavior_preserved_oversized():
    jpeg, orig, new = _process_photo()(base64.b64encode(_img_bytes((2000, 1000))).decode())
    assert isinstance(jpeg, (bytes, bytearray)) and _open(jpeg).format == "JPEG"
    assert orig == (2000, 1000)
    assert new == (1600, 800)                   # same result the inline logic produced


def _heic_bytes(size=(2000, 1200)):
    """A small in-memory HEIC (HEIF container). images.py registers pillow-heif's opener at import, so
    Pillow can both save and open HEIF here — the same registration the app relies on at request time."""
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="HEIF")
    return buf.getvalue()


def test_heic_decodes_and_reports_heif_format():
    # Pins the allowlisted string: a decoded HEIC reports format "HEIF" (not "HEIC") — exactly what
    # images.ALLOWED_INPUT_FORMATS must contain for the uploader to accept iPhone photos.
    assert _open(_heic_bytes()).format == "HEIF"
    assert "HEIF" in images.ALLOWED_INPUT_FORMATS


def test_heic_flows_through_pipeline_to_jpeg():
    # HEIC goes through the SAME resize core and comes out downscaled JPEG — no HEIC-specific path.
    im = _open(images.resize_image_bytes(_heic_bytes((2000, 1000))))
    assert im.format == "JPEG"
    assert max(im.size) == 1600 and im.size == (1600, 800)


def test_backfill_process_photo_behavior_preserved_small_not_upscaled():
    # the not-resized branch: `new` read back from the encoded JPEG must equal the source dims, matching
    # the old inline `new = img.size` for a small image (guards the recompute-from-bytes change).
    jpeg, orig, new = _process_photo()(base64.b64encode(_img_bytes((800, 600))).decode())
    assert orig == (800, 600)
    assert new == (800, 600)                    # new == orig — no upscale, dims survive the round-trip
