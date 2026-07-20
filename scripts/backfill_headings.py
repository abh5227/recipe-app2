#!/usr/bin/env python3
"""backfill_headings.py — one-off backfill: promote existing is_heading=0 rows that are really
SECTION HEADINGS but were stored as plain (amount-less) ingredient rows at import.

  "**Other Ingredients:**"  (is_heading=0, raw_text="**Other Ingredients:**")
    -> is_heading=1, raw_text="Other Ingredients:"  (emphasis wrapper stripped, colon kept)
  "For the dal"             (is_heading=0, label="For the dal")
    -> is_heading=1, raw_text="For the dal"

WHY a Python backfill (not a SQL migration): the decision re-parses free-text lines (emphasis
strip + is_section) and consults the import review queue; SQL can't. Mirrors scripts/
backfill_name_unit.py and scripts/backfill_qty_unit.py.

SCOPE — TWO high-confidence buckets only (the false-positive here is asymmetric-worse: a wrongly
promoted ingredient VANISHES from the list); anything else stays for manual review (the editor
heading-toggle):
  Bucket A — for/to  : rows FLAGGED in import_flags with a "section" suggestion ("For the X" /
                       "To finish"-style). The importer already recognized the signal but declined
                       to auto-promote; we now promote them.
  Bucket B — detector: rows whose (emphasis-stripped) text is a section per import_cleanup.
                       section_signal — colon / ALL-CAPS, whole-line emphasis that strips to one
                       ("**Other Ingredients:**" -> "Other Ingredients:"), or one of the 4 verified
                       amount-less patterns ("X Ingredients", unit-system label, "Day N", prep
                       allowlist {egg wash, dredge, sponge, brine}). Shares section_signal with the
                       import detector.

NOT promoted (left for manual review, no matching bucket): the section-word-ending rows ("... for
Garnish", "... Frosting" — half are real ingredients) and other one-offs (Pastina variant labels,
"Cheddar Mashed Potatoes", "Salsa", "Meatballs", "Loaves", the italic "_Vanilla … Icing_", "Spice
Mix"), plus the "Mix or Cajun seasoning" merge fragment.

WHAT CHANGES for a promoted row (matching the canonical heading shape — cf. a natively-detected
heading: is_heading=1, raw_text=text, label/quantity/unit/qty NULL): is_heading 0->1; raw_text =
the CLEAN text (emphasis stripped for Bucket B, unchanged for Bucket A); label/quantity/unit/qty ->
NULL. grams/secondary_measure are already NULL (untouched). Reading renders a heading's raw_text and
keys per-person sections on it, so the clean text must live in raw_text.

Guarded + idempotent: only is_heading=0 amount-less rows matching a bucket are promoted; a promoted
row is is_heading=1, so a re-run won't re-pick it.

Run FIRST:  python3 backup.py                              # snapshot recipes.db (safety)
Then:       python3 scripts/backfill_headings.py           # DRY-RUN: prints the plan, writes NOTHING
            python3 scripts/backfill_headings.py --apply    # perform the UPDATEs
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from import_cleanup import section_signal, strip_emphasis   # SAME strip + section test the detector uses

DB = BASE_DIR / "recipes.db"


def _row_text(row):
    """The line's text as stored on an is_heading=0 row: label if present, else raw_text."""
    return (row["label"] or row["raw_text"] or "").strip()


def plan_heading(text, is_flagged_section):
    """PURE classifier: should this is_heading=0 row become a heading, and what CLEAN text does it
    store? Returns {"action":"auto","bucket":...,"text":clean} or {"action":"skip"}.

      Bucket A (for/to)  : the import review queue already suggested "section" for it.
      Bucket B (detector): the (emphasis-stripped) text is a section per section_signal — colon /
                           ALL-CAPS, whole-line emphasis that strips to one, or one of the 4 verified
                           amount-less patterns ("X Ingredients", unit-system label, "Day N", prep
                           allowlist). The is_heading=0 SQL guard means an already-promoted row is
                           never re-selected, so no `not is_section` check is needed.
    """
    t = (text or "").strip()
    if not t:
        return {"action": "skip", "reason": "empty"}
    stripped = strip_emphasis(t)
    if is_flagged_section:
        return {"action": "auto", "bucket": "for/to", "text": stripped}
    if section_signal(stripped):
        return {"action": "auto", "bucket": "detector", "text": stripped}
    return {"action": "skip", "reason": "no-bucket"}


def run(apply=False):
    if not DB.exists():
        sys.exit(f"No database: {DB} (run build_db.py first)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # the import-review rows the importer already suggested were SECTIONS (Bucket A signal), keyed
    # (recipe_id, position) to match a recipe_ingredients row.
    flagged_section = {
        (r["recipe_id"], r["position"]) for r in conn.execute(
            "SELECT recipe_id, position FROM import_flags "
            "WHERE flag = 'ambiguous_section' AND reason LIKE '%suggest section%'")
    }

    # candidates: is_heading=0 AND amount-less (a heading never carries a quantity — a hard guard
    # against ever promoting a real amount-bearing ingredient).
    rows = conn.execute(
        "SELECT id, recipe_id, position, qty, quantity, unit, label, raw_text "
        "FROM recipe_ingredients WHERE is_heading = 0 AND (qty IS NULL OR qty = '')"
    ).fetchall()

    auto = {"for/to": [], "detector": []}
    for r in rows:
        p = plan_heading(_row_text(r), (r["recipe_id"], r["position"]) in flagged_section)
        if p["action"] == "auto":
            auto[p["bucket"]].append((r, p))
    total = sum(len(v) for v in auto.values())

    # ---- report ----
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] heading backfill — candidates (is_heading=0, amount-less): {len(rows)}")
    print(f"  PROMOTE to heading: {total}   (Bucket A for/to = {len(auto['for/to'])}, "
          f"Bucket B detector = {len(auto['detector'])})")

    for bucket, title in (("for/to", "BUCKET A · for/to (import flagged suggest-section)"),
                          ("detector", "BUCKET B · detector (section_signal: emphasis / X-Ingredients / unit / Day-N / prep)")):
        print(f"\n===== {title} =====")
        for r, p in auto[bucket]:
            print(f"  {r['id']:5d} | {r['recipe_id'][:40]} pos{r['position']}")
            print(f"        | before: is_heading=0 label={r['label']!r} raw_text={r['raw_text']!r}")
            print(f"        | after : is_heading=1 label=NULL raw_text={p['text']!r}")

    if apply:
        conn.executemany(
            "UPDATE recipe_ingredients "
            "SET is_heading = 1, raw_text = ?, label = NULL, quantity = NULL, unit = NULL, qty = NULL "
            "WHERE id = ?",
            [(p["text"], r["id"]) for bucket in auto for r, p in auto[bucket]],
        )
        conn.commit()
        print(f"\nAPPLIED: {total} rows promoted to headings (is_heading=1, raw_text cleaned, "
              f"label/quantity/unit/qty NULL). grams/secondary_measure untouched.")
    else:
        print(f"\nDRY-RUN — wrote NOTHING. {total} rows would be promoted to headings.")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry-run, writes nothing)")
    args = ap.parse_args()
    run(apply=args.apply)
