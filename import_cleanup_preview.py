#!/usr/bin/env python3
"""import_cleanup_preview.py — the READ-ONLY sample preview for the import cleanup core.

Scans the Paprika archive for a handful of deliberately awkward recipes (TARGETS below),
runs each through import_cleanup.clean_recipe, and prints the structured-or-flagged result
plus a summary. WRITES NOTHING: the archive is opened in memory and never modified, and no
database connection is ever made.

Split out of import_cleanup.py, which is the SOURCE-AGNOSTIC core. That claim was true of
the core's functions but not of the module: this preview's `import paprika_native_reader`,
`import zipfile` and hardcoded ARCHIVE sat at import_cleanup's module level, so anything
importing the core imported the Paprika reader too. app.py and build_db.py both do exactly
that for one function (split_qty), which meant the live Flask app loaded the Paprika reader,
zipfile, gzip and base64 on every boot. Nothing Paprika-specific remains in the core.

Everything below is unchanged from import_cleanup.py apart from the imports it now needs
in its own right.

Run:  python3 import_cleanup_preview.py
"""
import zipfile
from collections import Counter
from pathlib import Path

import paprika_native_reader as reader
from import_cleanup import clean_recipe, trunc

ARCHIVE = Path(__file__).resolve().parent / "My Recipes.paprikarecipes"


# --------------------------------------------------------------------------- #
# Preview (writes nothing)
# --------------------------------------------------------------------------- #
TARGETS = [
    ("acqua pazza", "Acqua Pazza — sections, range, N x SIZE, alternatives"),
    ("blueberry muffin sugar cookies", "Blueberry Muffin Sugar Cookies — parenthetical grams + unicode fractions"),
    ("thai tea ice cream", "Thai Tea Ice Cream — dangling open paren (must not crash/harvest)"),
    ("panang curry", "Panang Curry — 'each' multi-ingredient + no-amount ambiguous lines"),
    ("beef and pepper", "Beef and Pepper Stir-Fry — all-caps colon sections"),
    ("blueberry muffins", "Blueberry Muffins — stub (photo-only)"),
]


def fmt_line(d):
    ann = []
    if d["range"]:
        ann.append("range=%s–%s" % d["range"])
    if d["grams_harvested"] is not None:
        ann.append("grams=%g" % d["grams_harvested"])
    if "grams_declined" in d["flags"]:
        ann.append("grams-declined")
    if d["has_alternative"]:
        ann.append("alt")
    if d["has_prep_note"]:
        ann.append("prep")
    if d.get("secondary_measure"):
        ann.append("2nd=%s" % d["secondary_measure"])
    tail = ("   [" + ", ".join(ann) + "]") if ann else ""
    if d["kind"] == "section":
        return "[SECTION   ] %s" % d["raw"].strip()
    if d["kind"] == "flagged":
        sug = " ->%s" % d["suggestion"] if d["suggestion"] else ""
        blocking = [f for f in d["flags"] if f != "grams_declined"]  # grams-declined shown in tail
        parsed = "  {amt=%r unit=%r}" % (d["amount"], d["unit"]) if d["amount"] else ""
        return "[FLAGGED   ] (%s%s) %s%s%s\n             reason: %s" % (
            ",".join(blocking), sug, trunc(d["name"]), parsed, tail, d["flag_reason"])
    return "[INGREDIENT] amt=%-8r unit=%-7r | %s%s" % (d["amount"], d["unit"], trunc(d["name"], 48), tail)


def print_recipe(r, label):
    print("\n" + "=" * 88)
    print("%s" % label)
    print("  name=%s" % r["name"])
    print("=" * 88)
    print("  servings : %s   (raw %r)" % (r["servings"] if r["servings"] is not None else "BLANK", r["servings_raw"]))
    print("  recipe_flags: %s    review_count: %d" % (r["recipe_flags"] or "none", r["review_count"]))
    print("  ingredients (%d):" % len(r["ingredients"]))
    for d in r["ingredients"]:
        print("    " + fmt_line(d))
    if not r["ingredients"]:
        print("    (none)")
    print("  directions: %d step-line(s) carried as-is" % len(r["directions"]))


def print_summary(results):
    lines = [d for r in results for d in r["ingredients"]]
    kinds = {k: sum(d["kind"] == k for d in lines) for k in ("ingredient", "section", "flagged")}
    flagtypes = Counter(f for d in lines for f in d["flags"] if f != "grams_declined")
    declined = sum("grams_declined" in d["flags"] for d in lines)
    grams = sum(d["grams_harvested"] is not None for d in lines)
    servings_ok = sum(r["servings"] is not None for r in results)
    print("\n" + "=" * 88)
    print("SAMPLE SUMMARY (%d recipes)" % len(results))
    print("=" * 88)
    print("  line kinds       : %s" % kinds)
    print("  flag types       : %s" % (dict(flagtypes) or "none"))
    print("  grams harvested  : %d line(s)   (declined low-confidence: %d)" % (grams, declined))
    print("  servings parsed  : %d   blank: %d" % (servings_ok, len(results) - servings_ok))
    print("  recipe_flags     : %s" % {r["name"]: r["recipe_flags"] for r in results if r["recipe_flags"]})


def collect_samples(zf):
    """Scan the archive once; return {label: cleaned recipe} for the TARGETS found."""
    found = {}
    for _name, rec, err in reader.iter_entries(zf):
        if err or not rec:
            continue
        nm = reader.strip_quotes(rec.get("name") or "").lower()
        for sub, label in TARGETS:
            if sub in nm and label not in found:
                found[label] = clean_recipe(reader.normalize(rec))
    return found


def main():
    if not ARCHIVE.is_file():
        raise SystemExit("Archive not found: %s" % ARCHIVE)
    print("IMPORT CLEANUP CORE — preview only (writes nothing; archive read in memory)")

    with zipfile.ZipFile(ARCHIVE) as zf:
        found = collect_samples(zf)

    results = []
    for sub, label in TARGETS:
        if label in found:
            print_recipe(found[label], label)
            results.append(found[label])
        else:
            print("\n(sample not found: %s)" % label)

    print_summary(results)


if __name__ == "__main__":
    main()
