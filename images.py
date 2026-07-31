"""images.py — shared image-processing "brain" (root-level, like weights.py / stepscale.py).

resize_image_bytes() is the single resize core used at BOTH backfill time and (Stage 2) upload time,
so the two paths resize identically — the weights.py / split-helper shared pattern. Pure: raw image
bytes in, resized JPEG bytes out; no file I/O, no base64, no printing.
"""
import io
import os
import tempfile
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps

import pillow_heif
pillow_heif.register_heif_opener()   # HEIC/HEIF (iPhone/Photos default) — register the opener ONCE here in
                                     # the shared image brain so EVERY decode path (upload + backfill) gains
                                     # it; once decodable, the existing pipeline re-encodes HEIC to JPEG.

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "static" / "images"   # where hero photos live + are served from; a REDIRECTABLE
                                              # module global (tests rebind it, like app.DB) so uploads
                                              # never touch the real dir. save_image() reads it at call time.

# Decompression-bomb guard (S2), process-wide: a small file can decode to enormous pixel dimensions.
# 40 MP is generous for real photos (~12 MP phone, ~33 MP 8K) yet far below a bomb's gigapixels.
Image.MAX_IMAGE_PIXELS = 40_000_000

# Accepted INPUT formats, decided by what Pillow DECODES the bytes as — never the client Content-Type
# or filename (S3). Output is always a re-encoded JPEG, so this gates input only. "HEIF" is what Pillow
# reports for the whole HEIF family (.heic AND .heif) once pillow-heif's opener is registered above —
# confirmed by decoding a real HEIC (img.format == "HEIF"; there is no "HEIC" format id).
ALLOWED_INPUT_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "HEIF"})

LONG_EDGE = 1600       # downscale the long edge to this; never upscale a smaller original
JPEG_QUALITY = 85


def resize_image_bytes(raw_bytes):
    """Decode raw image bytes, honor EXIF orientation, convert to a JPEG-safe mode, downscale the long
    edge to LONG_EDGE (never upscale) with LANCZOS, and return re-encoded JPEG bytes at JPEG_QUALITY.
    Pure — no file/base64/printing. Raises on undecodable input (the caller handles/logs)."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)          # honor phone-camera orientation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")                # JPEG can't hold alpha / CMYK / palette
    w, h = img.size
    longest = max(w, h)
    if longest > LONG_EDGE:                     # shrink only; never upscale a smaller original
        scale = LONG_EDGE / longest
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    # No exif= passed → the re-encode DROPS all metadata (EXIF/GPS) — deliberate: output is served from
    # a PUBLIC route (S4). exif_transpose above already applied orientation before this strip.
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


class ImageValidationError(Exception):
    """The uploaded bytes aren't an accepted, safely-decodable image (blocked/undecodable format or a
    decompression bomb). The upload endpoint maps this to HTTP 400."""


def _validate(raw_bytes):
    """S2/S3: a successful decode of an allowlisted format is the ONLY acceptance test — client
    MIME/extension is never trusted. A decompression bomb (error OR warning) is a rejection. Raises
    ImageValidationError on any failure."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw_bytes))
            fmt = img.format
            img.load()                      # force pixel decode -> a bomb raises HERE, not mid-resize
    except Image.DecompressionBombError as e:
        raise ImageValidationError("image too large (possible decompression bomb)") from e
    except Exception as e:                  # UnidentifiedImageError / OSError / bomb-warning-as-error / …
        raise ImageValidationError("not a decodable image") from e
    if fmt not in ALLOWED_INPUT_FORMATS:
        raise ImageValidationError(f"unsupported image format: {fmt}")


def _atomic_write(dest, data):
    """S6: write to a temp file in the SAME dir, then os.replace into place (atomic on one filesystem) —
    an interrupted write can never leave a truncated file at the real path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)               # atomic rename into place
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_image(file_bytes, *, slug):
    """The storage SEAM: validate -> resize (re-encode, which strips EXIF/GPS) -> atomically write a
    metadata-free JPEG to IMAGES_DIR under a SERVER-DERIVED name -> return the DB path 'images/<slug>.jpg'.
    The ONLY disk-writing boundary — swap this body for object storage later; callers see only the
    returned string. Raises ImageValidationError on bad input (endpoint -> 400)."""
    _validate(file_bytes)                                              # S2/S3
    jpeg = resize_image_bytes(file_bytes)                              # Stage 1: orient-then-strip; fresh pixels (S4)
    name = f"{slug}.jpg"                                               # S1: name derived ENTIRELY from the server slug
    dest = IMAGES_DIR / name
    if not dest.resolve().is_relative_to(IMAGES_DIR.resolve()):        # S1: containment, defense-in-depth
        raise ImageValidationError("resolved path escapes the images directory")
    _atomic_write(dest, jpeg)                                          # S6: atomic; DB write happens only after
    return f"images/{name}"


COOKS_SUBDIR = "cooks"   # album photos live under IMAGES_DIR/cooks/, distinct from the flat hero <slug>.jpg


def save_cook_photo(file_bytes):
    """Storage SEAM for a cook-album photo — a sibling of save_image (Stage 4 build 2a). Validate -> resize
    (re-encode, which strips EXIF/GPS) -> atomically write a metadata-free JPEG under IMAGES_DIR/cooks/<uuid>.jpg
    -> return the DB path 'images/cooks/<uuid>.jpg'. Shares save_image's internals byte-for-byte (_validate +
    resize_image_bytes + _atomic_write) — the ONLY differences from the hero are the NAME (a server-minted
    uuid, never a client value or the recipe slug) and the cooks/ SUBDIR, so several photos per cook never
    collide and never overwrite the hero. No DB interaction (build 2b's endpoint records the row + path).
    Raises ImageValidationError on bad input (endpoint -> 400)."""
    _validate(file_bytes)                                              # S2/S3: identical validation to save_image
    jpeg = resize_image_bytes(file_bytes)                              # orient-then-strip; fresh pixels (S4)
    name = f"{COOKS_SUBDIR}/{uuid.uuid4().hex}.jpg"                    # S1: name is a SERVER-minted uuid, no input
    dest = IMAGES_DIR / name
    if not dest.resolve().is_relative_to(IMAGES_DIR.resolve()):        # S1: containment, defense-in-depth
        raise ImageValidationError("resolved path escapes the images directory")
    _atomic_write(dest, jpeg)                                          # S6: atomic; also mkdirs IMAGES_DIR/cooks
    return f"images/{name}"


def delete_image(path):
    """The file-DELETION seam — the FIRST place the app unlinks a stored image (Stage 4 build 2a; build 2c
    uses it for cook-photo deletion AND the hero-orphan cleanup). Mirrors save_image's containment discipline:
    take a stored relative path ('images/<...>'), resolve it under IMAGES_DIR, CONTAINMENT-CHECK it is inside
    IMAGES_DIR (refuse otherwise — NEVER unlink outside the images dir), and unlink(missing_ok=True) so a
    missing / already-deleted file is a clean no-op (idempotent). Returns True if a file was removed, False if
    it was absent or the path was refused. Swap this body for object-storage deletion later, alongside
    save_image / save_cook_photo. No DB interaction."""
    rel = str(path or "")
    if rel.startswith("images/"):
        rel = rel[len("images/"):]                                    # stored paths are 'images/<...>'; strip the prefix
    dest = IMAGES_DIR / rel
    if not dest.resolve().is_relative_to(IMAGES_DIR.resolve()):       # containment: never escape the images dir
        return False
    try:
        existed = dest.is_file()
        dest.unlink(missing_ok=True)                                  # idempotent: a missing file is a no-op
    except OSError:
        return False
    return existed
