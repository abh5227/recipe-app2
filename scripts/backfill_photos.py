#!/usr/bin/env python3
"""backfill_photos.py — one-off backfill: give each imported recipe its ORIGINAL Paprika dish photo
as a hero image.

The Paprika native archive embeds photos as base64. Each recipe carries a 280x280 `photo_data`
thumbnail AND (for ~40% of them) full-size originals in `photos[]`. The recipe importer left
`image` blank ("full image storage = separate pass"); this fills it.

SCOPE (locked): full-size heroes ONLY. A recipe is backfilled iff it is source='app', has a BLANK
`image`, and the archive entry (matched by Paprika uid) has at least one full-size `photos[]` entry.
The hero is `photos[0]` (the primary); extra photos are ignored (reserved for a future gallery /
per-step feature). Recipes with only the 280x280 thumbnail, or no photo, get NOTHING and keep the
"+ add a photo" placeholder. `photo_data` thumbnails are never used.

For each backfilled recipe: decode photos[0], apply EXIF orientation, resize the LONG edge down to
1600px (never upscale), save JPEG q=85 to static/images/<slug>.jpg, and set image='images/<slug>.jpg'.

Guarded + idempotent: only touches source='app' rows with a blank image; skips any recipe that
already has an image (protects the 5 seed recipes and makes re-runs safe — a second run fills
nothing). DB writes happen in one transaction, only on the real run. A photo that fails to
decode/resize is logged and skipped; it never aborts the batch. The photos are regenerable from the
archive, so they are git-ignored (see .gitignore) — not committed.

Run:  python3 scripts/backfill_photos.py --dry-run   # report only; writes no file, no DB change
      python3 scripts/backfill_photos.py             # extract + resize + save + update the DB
"""
import argparse
import base64
import io
import sqlite3
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import paprika_native_reader as reader   # noqa: E402 (path set above) — archive iterate + in-memory decode
from PIL import Image, ImageOps          # noqa: E402

DB = REPO / "recipes.db"
# Define the archive path here rather than using reader.ARCHIVE — the reader derives ARCHIVE from
# sys.argv[1] at import time, which would wrongly pick up THIS script's flags (e.g. "--dry-run").
ARCHIVE = REPO / "My Recipes.paprikarecipes"
IMAGES_DIR = REPO / "static" / "images"
LONG_EDGE = 1600
JPEG_QUALITY = 85


def process_photo(b64):
    """Decode a base64 photo, orient it, resize the long edge down to LONG_EDGE (no upscale), and
    return (jpeg_bytes, (orig_w, orig_h), (new_w, new_h)). Raises on undecodable input (caller logs).
    Encodes to an in-memory buffer only — writes nothing — so the dry-run gets an accurate size."""
    raw = base64.b64decode(b64 or "")
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)          # honor phone-camera orientation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")                # JPEG can't hold alpha / CMYK / palette
    orig = img.size
    w, h = img.size
    longest = max(w, h)
    if longest > LONG_EDGE:                     # shrink only; never upscale a smaller original
        scale = LONG_EDGE / longest
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue(), orig, img.size


def main():
    ap = argparse.ArgumentParser(description="Backfill imported recipes with their Paprika dish photos.")
    ap.add_argument("--dry-run", action="store_true", help="report what would happen; write nothing")
    args = ap.parse_args()

    if not ARCHIVE.is_file():
        raise SystemExit(f"Archive not found: {ARCHIVE}")

    # Candidates: app-tier recipes with a blank image (uid -> slug). Everything else is skipped:
    # seed recipes and already-filled recipes both have a non-blank image.
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    candidates = {}                              # uid -> slug (app + blank image)
    skip_have_image = skip_not_app = 0
    for r in conn.execute("SELECT id, source, image, uid FROM recipes"):
        blank = not (r["image"] or "").strip()
        if r["source"] != "app":
            skip_not_app += 1
        elif not blank:
            skip_have_image += 1
        elif r["uid"]:
            candidates[r["uid"]] = r["id"]

    backfilled = []          # (slug, orig_dims, new_dims, orig_kb, new_kb)
    skip_thumb_only = []     # candidate, archive has only the 280px thumbnail
    skip_no_photo = []       # candidate, archive has no photo at all
    failures = []            # (slug, error)
    seen_uids = set()

    with zipfile.ZipFile(str(ARCHIVE)) as zf:
        for name, rec, err in reader.iter_entries(zf):
            if err is not None or rec is None:
                continue
            uid = rec.get("uid")
            slug = candidates.get(uid)
            if not slug:
                continue                         # not a blank-image app recipe
            seen_uids.add(uid)
            photos = rec.get("photos") or []
            if not photos:                       # no full-size original
                (skip_thumb_only if rec.get("photo_data") else skip_no_photo).append(slug)
                continue
            try:
                orig_b64 = photos[0].get("data")
                jpeg, orig, new = process_photo(orig_b64)
            except Exception as e:               # decode/resize failure — log + skip, never abort
                failures.append((slug, repr(e)))
                continue
            orig_kb = round(len(base64.b64decode(orig_b64 or "")) / 1024)
            new_kb = round(len(jpeg) / 1024)
            if not args.dry_run:
                IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                (IMAGES_DIR / f"{slug}.jpg").write_bytes(jpeg)
            backfilled.append((slug, orig, new, orig_kb, new_kb))

    # Candidates never seen in the archive (uid not present) — shouldn't happen, but report if so.
    missing_in_archive = [s for u, s in candidates.items() if u not in seen_uids]

    if not args.dry_run and backfilled:
        try:
            conn.execute("BEGIN")
            for slug, *_ in backfilled:
                conn.execute("UPDATE recipes SET image = ? WHERE id = ? AND source = 'app'",
                             (f"images/{slug}.jpg", slug))
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    else:
        conn.close()

    orig_mb = sum(b[3] for b in backfilled) / 1024
    new_mb = sum(b[4] for b in backfilled) / 1024
    print(f"=== {'DRY-RUN (no files written, DB untouched)' if args.dry_run else 'BACKFILL COMPLETE'} ===")
    print(f"  candidates (app-tier, blank image) : {len(candidates)}")
    print(f"  would backfill (has full-size photo): {len(backfilled)}" if args.dry_run
          else f"  backfilled (saved + DB updated)    : {len(backfilled)}")
    print(f"  skipped — already have an image     : {skip_have_image}  (app-tier; makes re-runs idempotent)")
    print(f"  skipped — thumbnail-only (no full)  : {len(skip_thumb_only)}")
    print(f"  skipped — no photo in archive       : {len(skip_no_photo)}")
    print(f"  non-app rows (seed, untouched)      : {skip_not_app}")
    if missing_in_archive:
        print(f"  !! candidates not found in archive  : {len(missing_in_archive)} -> {missing_in_archive[:5]}")
    print(f"  resize: {orig_mb:.1f} MB (originals) -> {new_mb:.1f} MB (resized JPEG q{JPEG_QUALITY}, long edge <= {LONG_EDGE}px)")
    if failures:
        print(f"  FAILURES (decode/resize, skipped): {len(failures)}")
        for slug, e in failures:
            print(f"      ! {slug}: {e}")
    # a few examples so the resize is legible
    for slug, orig, new, okb, nkb in backfilled[:6]:
        tag = "would save" if args.dry_run else "saved"
        print(f"      {tag} images/{slug}.jpg  {orig[0]}x{orig[1]} ({okb} KB) -> {new[0]}x{new[1]} ({nkb} KB)")
    if args.dry_run:
        print("\n(nothing written — dry run.)")


if __name__ == "__main__":
    main()
