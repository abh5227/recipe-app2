#!/usr/bin/env python3
"""backfill_name_unit.py — one-off backfill: move a leading size/count descriptor out of an ingredient
NAME into the empty unit field, for the CLEAN leading rows.

  "1 medium onion (diced)"  (quantity="1", unit="", label="medium onion (diced)", qty="1")
    -> quantity="1", unit="medium", label="onion (diced)", qty="1 medium"

WHY a Python backfill (not a SQL migration): this re-parses free-text names, which SQL can't do; and it
mutates ~259 persistent app rows. Mirrors scripts/backfill_qty_unit.py.

SCOPE (from the name→unit diagnostic):
  AUTO      — the name leads with a single listed descriptor (+ optional "of"), sane remainder after.
  FLAG only — size+count ("large cloves garlic": the COUNT is the real unit, ambiguous), intrinsic
              ("medium-grain rice", "large dice": descriptor is part of the name), empty/paren-after
              ("Cloves" alone, "cloves (or …)"). These are PRINTED for manual review, NOT transformed.
  DEFER     — trailing count-nouns ("garlic cloves") are out of scope (not a leading descriptor).

WHAT CHANGES for an auto row: unit ("" -> "medium"), label (stripped remainder), and — MANDATORY — qty
= quantity + " " + unit ("1" -> "1 medium"), because READING displays `qty`, not the `unit` column, so
leaving qty="1" would drop the descriptor from the reading ledger. `quantity` is unchanged, and
`raw_text` is left AS-IS: it's the original line ("5 sprigs fresh thyme") and stays accurate — it equals
qty ("5 sprigs") + " " + the new label ("fresh thyme"). grams/secondary_measure/ingredient_id untouched.

⚠️ The unit words (medium/cloves/…) are counts: the scaler treats them as counts BY THEIR ABSENCE from
its measure recognizers. This script does NOT touch the scaler and does NOT add these to any measure
list — so "1 medium" x2 = "2 medium" (round to whole), unchanged. Unit is just lowercased (NOT
singularized — "cloves" stays "cloves"; that's what canonicalizeUnit would do for these words anyway).

Guarded + idempotent: only non-heading rows WHERE unit IS NULL/'' whose name leads with a descriptor are
considered; an auto row gets a populated unit, so a re-run won't re-pick it.

Run FIRST:  python3 backup.py                              # snapshot recipes.db (safety)
Then:       python3 scripts/backfill_name_unit.py          # DRY-RUN: prints the plan, writes NOTHING
            python3 scripts/backfill_name_unit.py --apply   # perform the UPDATEs
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "recipes.db"

SIZE = ["large", "medium", "small"]
COUNT = ["cloves", "clove", "sprigs", "sprig", "stalks", "stalk", "bunches", "bunch",
         "cans", "can", "slices", "slice", "heads", "head", "pieces", "piece",
         "knobs", "knob", "handfuls", "handful", "pinch"]
LEAD = SIZE + COUNT
_ALT = "|".join(sorted(LEAD, key=len, reverse=True))                 # longest-first for the alternation
_LEAD_WORD = re.compile(r"^\s*(" + _ALT + r")\b", re.I)              # does the name lead with a descriptor?
_LEAD_STRIP = re.compile(r"^\s*(" + _ALT + r")\b[ \t]*(?:of\b[ \t]*)?", re.I)   # strip lead word + optional "of"
_INTRINSIC = re.compile(r"^\s*(?:large|medium|small)[\s-]+(?:grain|dice|curd|batch)\b", re.I)
# SIZE + COUNT-noun ("large cloves of garlic") — capture the "size count-noun" phrase (the KEPT unit)
# and strip an optional following "of". group(1) = the unit phrase; .end() lands after the "of".
_SIZE_COUNT_STRIP = re.compile(
    r"^\s*((?:large|medium|small)\s+(?:" + "|".join(COUNT) + r"))\b[ \t]*(?:of\b[ \t]*)?", re.I)
# descriptor immediately followed by a hyphen -> a hyphenated compound ("medium-to-large",
# "medium-grain", "large-flake"): the word is part of the name, never the unit. More general than
# the grain/dice/curd/batch denylist (which it subsumes for hyphenated cases).
_HYPHEN_COMPOUND = re.compile(r"^\s*(?:" + _ALT + r")-", re.I)
# Pre-mangled signatures (conservative — must not flag legit rows). A merged second ingredient shows a
# second quantity OUTSIDE parentheses with a SPELLED-OUT spoon/cup measure ("… each 2 teaspoons kosher
# salt"); we drop parenthetical notes FIRST so legit weight annotations ("(around 10 oz)", "(3.5 oz /
# 100g)") are NOT mistaken for a merge. Truncation = a dangling "(about" / bare "(" at the very end.
_PAREN = re.compile(r"\([^)]*\)")
_MERGED_QTY = re.compile(r"\b\d[\d./\s-]*(?:teaspoons?|tablespoons?|cups?)\b", re.I)
_TRUNCATED = re.compile(r"\(\s*about\s*$|\(\s*$")


def _looks_mangled(name):
    """Clear merged-line / truncation signatures only (conservative — see the regexes)."""
    if _MERGED_QTY.search(_PAREN.sub("", name)):   # second spoon/cup qty in the OPEN text (parens dropped)
        return True
    if _TRUNCATED.search(name):                    # dangling "(about" / "(" at the end
        return True
    return False


def _recombine(quantity, unit):
    """qty = quantity + ' ' + unit (split_qty's inverse) — a normal combined string the scaler reads."""
    return f"{(quantity or '').strip()} {unit}".strip()


def split_leading_descriptor(name):
    """Recognize a leading size/count descriptor in an ingredient NAME and split it into
    (unit, remaining_name); return None when there is no clean split.

    PURE and PROMOTABLE: plain string in, tuple|None out — NO database, no `view`, no row objects — so
    this function can later be LIFTED VERBATIM into a shared import helper (alongside
    import_cleanup.split_qty) to structure descriptors at import time, without dragging any DB code.

    Two cases (the size is KEPT — it's real info):
      * SIZE + COUNT-noun  "large cloves of garlic"     -> ("large cloves", "garlic")
                           "small bunch of flatleaf parsley (finely chopped)"
                                                        -> ("small bunch", "flatleaf parsley (finely chopped)")
      * single descriptor  "medium onion (cut into wedges)" -> ("medium", "onion (cut into wedges)")
                           "cloves garlic, crushed"          -> ("cloves", "garlic, crushed")
    An optional "of" after the descriptor is dropped. Unit is lowercased; plurals are NOT folded.

    Guards that yield None (no clean split): no leading descriptor; a hyphenated compound
    ("medium-to-large", "medium-grain"); an intrinsic phrase (grain/dice/curd/batch); or an empty /
    paren-only remainder after stripping. (Backfill review policy — merged/truncated imports and
    "or …" alternatives — lives in the CALLER, not here, so this stays a clean general recognizer.)
    """
    name = (name or "").strip()
    if not _LEAD_WORD.match(name):
        return None
    if _HYPHEN_COMPOUND.match(name) or _INTRINSIC.match(name):
        return None
    sc = _SIZE_COUNT_STRIP.match(name)
    if sc:                                                           # SIZE + COUNT-noun -> keep the phrase
        unit = re.sub(r"\s+", " ", sc.group(1)).strip().lower()     # "Large Cloves" -> "large cloves"
        remainder = name[sc.end():].strip()
    else:                                                           # single leading descriptor
        m = _LEAD_STRIP.match(name)
        unit = m.group(1).lower()
        remainder = name[m.end():].strip()
    if remainder == "" or remainder.startswith("("):
        return None
    return (unit, remainder)


def plan_name_split(name, quantity):
    """The BACKFILL classifier (not promotable — it adds backfill review policy + the qty recombine on
    top of split_leading_descriptor). Returns a dict:
      {"action": "auto", "unit", "name", "qty"}   — transform this row
      {"action": "skip", "reason": ...}           — reason in: no-leading-descriptor, pre-mangled,
          hyphen-compound, intrinsic, empty/paren, alternative
    """
    name = (name or "").strip()
    if not _LEAD_WORD.match(name):
        return {"action": "skip", "reason": "no-leading-descriptor"}
    if _looks_mangled(name):                                         # merged second qty / truncated import
        return {"action": "skip", "reason": "pre-mangled"}
    split = split_leading_descriptor(name)
    if split is None:                                               # label WHY the recognizer declined
        if _HYPHEN_COMPOUND.match(name):
            return {"action": "skip", "reason": "hyphen-compound"}
        if _INTRINSIC.match(name):
            return {"action": "skip", "reason": "intrinsic"}
        return {"action": "skip", "reason": "empty/paren"}
    unit, newname = split
    if re.match(r"or\b", newname, re.I):                            # "large or 4 small onions…" alternative
        return {"action": "skip", "reason": "alternative"}
    return {"action": "auto", "unit": unit, "name": newname, "qty": _recombine(quantity, unit)}


def run(apply=False):
    if not DB.exists():
        sys.exit(f"No database: {DB} (run build_db.py first)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, qty, quantity, unit, label, raw_text FROM recipe_ingredients "
        "WHERE is_heading = 0 AND (unit IS NULL OR unit = '')"
    ).fetchall()

    # hand-verified merged/truncated imports (force-flagged by id, belt-and-suspenders on the signature)
    KNOWN_MANGLED = {2648, 5932}
    CATS = ["hyphen-compound", "intrinsic", "pre-mangled", "empty/paren", "alternative"]
    auto, flagged = [], {k: [] for k in CATS}
    for r in rows:
        name = (r["label"] or r["raw_text"] or "")
        p = plan_name_split(name, r["quantity"])
        if r["id"] in KNOWN_MANGLED and p["action"] == "auto":     # force-flag the two known bad rows
            p = {"action": "skip", "reason": "pre-mangled"}
        if p["action"] == "auto":
            auto.append((r, p))
        elif p["reason"] in flagged:
            flagged[p["reason"]].append((r, name))

    # ---- report ----
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] name->unit backfill — candidates (non-heading, empty unit): {len(rows)}")
    print(f"  AUTO-TRANSFORM  : {len(auto)}   (incl. size+count rows, unit = 'size count-noun')")
    print(f"  FLAG intrinsic+hyphen: {len(flagged['intrinsic']) + len(flagged['hyphen-compound'])}"
          f"   (intrinsic={len(flagged['intrinsic'])}, hyphen-compound={len(flagged['hyphen-compound'])} — descriptor is part of the name)")
    print(f"  FLAG empty/paren: {len(flagged['empty/paren'])}  (stripping leaves no real name — review)")
    print(f"  FLAG alternative: {len(flagged['alternative'])}  (remainder starts with 'or …' — review)")
    print(f"  FLAG pre-mangled: {len(flagged['pre-mangled'])}  (merged second qty / truncated import — review)")

    print("\n===== AUTO-TRANSFORM (every proposed change) =====")
    for r, p in auto:
        print(f"  {r['id']:5d} | before: qty={r['qty']!r} unit={(r['unit'] or '')!r} name={name_of(r)!r}")
        print(f"        | after : qty={p['qty']!r} unit={p['unit']!r} name={p['name']!r}")

    for key, title in (("hyphen-compound", "HYPHEN-COMPOUND (review — descriptor is part of a hyphenated word)"),
                       ("intrinsic", "INTRINSIC (review — descriptor is part of the name)"),
                       ("pre-mangled", "PRE-MANGLED (review — merged second qty / truncated import)"),
                       ("alternative", "ALTERNATIVE (review — remainder starts with 'or …')"),
                       ("empty/paren", "EMPTY/PAREN (review — no real name after strip)")):
        print(f"\n===== FLAGGED · {title} =====")
        for r, nm in flagged[key]:
            print(f"  {r['id']:5d} | qty={r['qty']!r} unit={(r['unit'] or '')!r} name={nm!r}")
        if not flagged[key]:
            print("  (none)")

    if apply:
        conn.executemany(
            "UPDATE recipe_ingredients SET unit = ?, label = ?, qty = ? WHERE id = ?",
            [(p["unit"], p["name"], p["qty"], r["id"]) for r, p in auto],
        )
        conn.commit()
        print(f"\nAPPLIED: {len(auto)} rows updated (unit + label + qty). quantity/raw_text untouched.")
    else:
        print(f"\nDRY-RUN — wrote NOTHING. {len(auto)} rows would be transformed; "
              f"{sum(len(v) for v in flagged.values())} flagged for manual review.")
    conn.close()


def name_of(r):
    return r["label"] or r["raw_text"] or ""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry-run, writes nothing)")
    args = ap.parse_args()
    run(apply=args.apply)
