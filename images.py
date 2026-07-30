"""images.py — shared image-processing "brain" (root-level, like weights.py / stepscale.py).

resize_image_bytes() is the single resize core used at BOTH backfill time and (Stage 2) upload time,
so the two paths resize identically — the weights.py / split-helper shared pattern. Pure: raw image
bytes in, resized JPEG bytes out; no file I/O, no base64, no printing.
"""
import io

from PIL import Image, ImageOps

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
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
