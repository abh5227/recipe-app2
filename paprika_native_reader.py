#!/usr/bin/env python3
"""paprika_native_reader.py — READ-ONLY reader + normalized-shape preview for the
Paprika NATIVE export (`.paprikarecipes`).

The native export is a ZIP of gzip-compressed JSON `.paprikarecipe` entries, with
images embedded as base64. This tool:
  1. opens the archive IN MEMORY — it WRITES NOTHING and never modifies the archive,
  2. maps a deliberately varied SAMPLE of recipes into the NORMALIZED import shape
     (the source -> core contract), and
  3. prints each normalized record plus a summary.

It is ONLY the reader (source -> normalized shape). It does NOT parse amounts, classify
section headers, harvest grams, link the library, write image files, or touch the
database. The shared cleanup core is designed next, against this reader's output.

Run:  python3 paprika_native_reader.py ["My Recipes.paprikarecipes"]
"""
import base64
import gzip
import json
import random
import sys
import zipfile
from collections import Counter
from pathlib import Path

ARCHIVE = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parent / "My Recipes.paprikarecipes")

# Top-level keys the native format is known to use (from the format study). Anything
# outside this set is reported as a surprise.
EXPECTED_KEYS = {
    "name", "ingredients", "directions", "description", "notes",
    "source", "source_url", "servings", "categories", "rating", "difficulty",
    "nutritional_info", "prep_time", "cook_time", "total_time",
    "uid", "hash", "created",
    "photo", "photo_large", "photo_hash", "photo_data", "photos", "image_url",
}

# Fields the normalized shape draws on; absence (key not present) = schema variation.
EXPECTED_PRESENT = [
    "name", "ingredients", "directions", "source", "source_url", "servings",
    "categories", "notes", "description", "uid", "hash",
    "prep_time", "cook_time", "total_time", "rating", "difficulty", "nutritional_info",
]

BAKING_HINTS = ("baking", "dessert", "bread", "cake", "cookie", "pastr", "pie")
BAKING_NAME_HINTS = ("cake", "bread", "cookie", "muffin", "scone", "tart", "pie",
                     "brioche", "focaccia", "sourdough", "biscuit", "loaf", "bun")


# --------------------------------------------------------------------------- #
# Normalization helpers (no cleaning/parsing — just shape mapping)
# --------------------------------------------------------------------------- #
def strip_quotes(name):
    """Paprika stores some names wrapped in literal double-quotes ('"Almost Za\'atar"')."""
    n = (name or "").strip()
    if len(n) >= 2 and n[0] == '"' and n[-1] == '"':
        return n[1:-1]
    return n


def ingredient_lines(raw):
    """`ingredients` is one newline-joined string -> list of non-empty raw lines.
    No amount/section parsing (the core's job). Returns (lines, blank_break_count)."""
    if not raw:
        return [], 0
    parts = raw.split("\n")
    lines = [p.strip() for p in parts if p.strip()]
    blanks = sum(1 for p in parts if not p.strip())
    return lines, blanks


def detect_image_type(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP"
    if raw[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1"):
        return "HEIC/HEIF"
    return "unknown(%s)" % raw[:4].hex()


def decode_b64(data):
    """(byte_len, type) or (None, error) — decodes to MEASURE only; writes nothing."""
    try:
        raw = base64.b64decode(data or "")
        return len(raw), detect_image_type(raw)
    except Exception as e:  # malformed base64
        return None, "DECODE-ERROR: %s" % e


def images_of(rec):
    """Per-image metadata from `photos[]`. Decodes base64 to measure; never writes files."""
    out = []
    for ph in rec.get("photos") or []:
        n, t = decode_b64(ph.get("data"))
        out.append({
            "filename": ph.get("filename"),
            "hash": ph.get("hash"),
            "name": ph.get("name"),
            "b64_len": len(ph.get("data") or ""),
            "bytes": n,
            "type": t,
        })
    return out


def trunc(s, n=90):
    s = " ".join(str(s if s is not None else "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def normalize(rec):
    """Map a raw native recipe dict -> the NORMALIZED import shape (the source->core seam)."""
    lines, blanks = ingredient_lines(rec.get("ingredients"))
    primary = None
    if rec.get("photo_data"):
        pn, pt = decode_b64(rec.get("photo_data"))
        primary = {"bytes": pn, "type": pt, "b64_len": len(rec.get("photo_data") or "")}
    return {
        "name": strip_quotes(rec.get("name")),
        "name_raw": rec.get("name") or "",
        "ingredient_lines": lines,
        "_blank_breaks": blanks,
        "directions": rec.get("directions") or "",
        "source": rec.get("source") or "",
        "source_url": rec.get("source_url") or "",
        "servings_raw": rec.get("servings") or "",
        "categories": rec.get("categories") or [],
        "notes": rec.get("notes") or "",
        "description": rec.get("description") or "",
        "uid": rec.get("uid") or "",
        "hash": rec.get("hash") or "",
        "prep_time": rec.get("prep_time") or "",
        "cook_time": rec.get("cook_time") or "",
        "total_time": rec.get("total_time") or "",
        "rating": rec.get("rating"),
        "difficulty": rec.get("difficulty") or "",
        "nutritional_info": rec.get("nutritional_info") or "",
        "images": images_of(rec),
        "primary_photo": primary,
        "photo_ref": rec.get("photo") or "",
        "photo_large_ref": rec.get("photo_large") or "",
    }


# --------------------------------------------------------------------------- #
# Archive iteration + sample selection
# --------------------------------------------------------------------------- #
def iter_entries(zf):
    """Yield (entry_name, raw_dict, error) for each .paprikarecipe (error set on failure)."""
    for name in zf.namelist():
        if not name.endswith(".paprikarecipe"):
            continue
        try:
            yield name, json.loads(gzip.decompress(zf.read(name))), None
        except Exception as e:
            yield name, None, e


def pick_sample(light, target=9):
    """Deliberately varied selection: sections, baking, no-image, no-instructions,
    no-ingredients, then random fill. Returns {idx: reason} in insertion order."""
    chosen = {}

    def add(idx, reason):
        if idx is not None and idx not in chosen:
            chosen[idx] = reason

    def first(pred):
        return next((r["idx"] for r in light if pred(r)), None)

    add(first(lambda r: "acqua pazza" in r["name"].lower()), "sections (Acqua Pazza)")
    add(first(lambda r: any(h in " ".join(r["cats"]).lower() for h in BAKING_HINTS)
              or any(h in r["name"].lower() for h in BAKING_NAME_HINTS)), "baking/dessert")
    add(first(lambda r: not r["has_img"]), "no image")
    add(first(lambda r: not r["has_dir"]), "no instructions")
    add(first(lambda r: not r["has_ing"]), "no ingredients")

    rng = random.Random(42)
    pool = [r["idx"] for r in light if r["idx"] not in chosen]
    rng.shuffle(pool)
    for idx in pool:
        if len(chosen) >= target:
            break
        add(idx, "random")
    return chosen


# --------------------------------------------------------------------------- #
# Printing
# --------------------------------------------------------------------------- #
def print_record(norm, reason, idx):
    print("\n" + "=" * 80)
    print("SAMPLE #%d  [%s]" % (idx, reason))
    print("=" * 80)
    if norm["name_raw"].strip() != norm["name"]:
        print("  name         : %s   (raw %r -> surrounding quotes stripped)"
              % (norm["name"], norm["name_raw"]))
    else:
        print("  name         : %s" % norm["name"])
    print("  uid / hash   : %s / %s" % (norm["uid"] or "—", trunc(norm["hash"], 16) or "—"))
    print("  source       : %s" % (trunc(norm["source"]) or "—"))
    print("  source_url   : %s" % (norm["source_url"] or "—"))
    print("  servings_raw : %r" % norm["servings_raw"])
    print("  categories   : %s" % (norm["categories"] or []))
    print("  times        : prep=%r cook=%r total=%r"
          % (norm["prep_time"], norm["cook_time"], norm["total_time"]))
    print("  rating       : %r    difficulty: %r" % (norm["rating"], norm["difficulty"]))
    print("  description  : %s" % (trunc(norm["description"]) or "—"))
    print("  notes        : %s" % (trunc(norm["notes"]) or "—"))

    lines = norm["ingredient_lines"]
    extra = ("  (+%d blank-line break(s) collapsed)" % norm["_blank_breaks"]
             if norm["_blank_breaks"] else "")
    print("  ingredient_lines (%d)%s:" % (len(lines), extra))
    for ln in lines:
        print("      | %s" % trunc(ln, 84))
    if not lines:
        print("      (none)")

    dlines = [x for x in norm["directions"].split("\n") if x.strip()]
    print("  directions (%d newline-separated step-line(s)):" % len(dlines))
    for i, st in enumerate(dlines[:3], 1):
        print("      %d. %s" % (i, trunc(st, 82)))
    if len(dlines) > 3:
        print("      … (%d more step-line(s))" % (len(dlines) - 3))
    if not dlines:
        print("      (none)")

    imgs = norm["images"]
    suffix = "  + primary photo_data" if norm["primary_photo"] else ""
    print("  images       : %d in photos[]%s" % (len(imgs), suffix))
    for im in imgs:
        print("      - %-40s hash=%s  %-5s  %s bytes (b64 %d chars)"
              % (trunc(im["filename"], 40), trunc(im["hash"], 12),
                 im["type"], im["bytes"], im["b64_len"]))
    if norm["primary_photo"]:
        p = norm["primary_photo"]
        print("      - photo_data (primary)                    %-5s  %s bytes (b64 %d chars)"
              % (p["type"], p["bytes"], p["b64_len"]))
    if norm["photo_ref"] or norm["photo_large_ref"]:
        print("      refs: photo=%s  photo_large=%s"
              % (trunc(norm["photo_ref"], 24) or "—",
                 trunc(norm["photo_large_ref"], 24) or "—"))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    if not ARCHIVE.is_file():
        sys.exit("Archive not found: %s" % ARCHIVE)

    print("READ-ONLY native reader  |  archive: %s" % ARCHIVE.name)
    print("(opened in memory; nothing written, archive unmodified)")

    with zipfile.ZipFile(ARCHIVE) as zf:
        # ---- Pass 1: light corpus scan (parse all; keep only small fields) ----
        total = 0
        malformed = []
        key_union = set()
        missing_counts = Counter()
        quote_wrapped = 0
        img_present = img_absent = 0
        no_ing = no_dir = 0
        light = []
        for name, rec, err in iter_entries(zf):
            if err is not None:
                malformed.append((name, repr(err)))
                continue
            total += 1
            key_union |= set(rec.keys())
            for k in EXPECTED_PRESENT:
                if k not in rec:
                    missing_counts[k] += 1
            nm_raw = rec.get("name") or ""
            nm = strip_quotes(nm_raw)
            if nm != nm_raw.strip():
                quote_wrapped += 1
            has_img = bool(rec.get("photos") or rec.get("photo_data"))
            img_present, img_absent = (img_present + 1, img_absent) if has_img \
                else (img_present, img_absent + 1)
            lines, _ = ingredient_lines(rec.get("ingredients"))
            has_ing = bool(lines)
            has_dir = bool((rec.get("directions") or "").strip())
            no_ing += 0 if has_ing else 1
            no_dir += 0 if has_dir else 1
            light.append({
                "idx": len(light), "entry": name, "name_raw": nm_raw, "name": nm,
                "cats": rec.get("categories") or [],
                "has_img": has_img, "has_dir": has_dir, "has_ing": has_ing,
            })

        # ---- Pass 2: full parse of only the selected sample ----
        chosen = pick_sample(light)
        sample_lines = 0
        sample_img_present = sample_img_absent = 0
        sample_missing = []
        for idx in sorted(chosen):
            rec = json.loads(gzip.decompress(zf.read(light[idx]["entry"])))
            norm = normalize(rec)
            print_record(norm, chosen[idx], idx)
            sample_lines += len(norm["ingredient_lines"])
            if norm["images"] or norm["primary_photo"]:
                sample_img_present += 1
            else:
                sample_img_absent += 1
            miss = [k for k in EXPECTED_PRESENT if k not in rec]
            if miss:
                sample_missing.append((norm["name"], miss))

    # ---- Summaries ----
    print("\n" + "=" * 80)
    print("SAMPLE SUMMARY  (%d recipes)" % len(chosen))
    print("=" * 80)
    print("  total ingredient lines : %d" % sample_lines)
    print("  images present / absent: %d / %d" % (sample_img_present, sample_img_absent))
    if sample_missing:
        print("  recipes missing expected field(s):")
        for nm, miss in sample_missing:
            print("    - %s: %s" % (nm, ", ".join(miss)))
    else:
        print("  recipes missing expected field(s): none")

    print("\n" + "=" * 80)
    print("CORPUS SCAN  (across all %d parsed entries — context for surprises)" % total)
    print("=" * 80)
    print("  entries parsed         : %d   (malformed: %d)" % (total, len(malformed)))
    for nm, e in malformed:
        print("    ! %s -> %s" % (nm, e))
    print("  images present / absent: %d / %d" % (img_present, img_absent))
    print("  no ingredients / no directions: %d / %d" % (no_ing, no_dir))
    print("  names wrapped in literal quotes: %d" % quote_wrapped)
    unexpected = sorted(key_union - EXPECTED_KEYS)
    never_seen = sorted(EXPECTED_KEYS - key_union)
    print("  unexpected top-level keys: %s" % (unexpected or "none"))
    print("  expected keys never seen : %s" % (never_seen or "none"))
    if missing_counts:
        print("  expected fields absent in some entries:")
        for k, n in missing_counts.most_common():
            print("    - %s: absent in %d/%d" % (k, n, total))
    else:
        print("  every expected field present in every entry")


if __name__ == "__main__":
    main()
