#!/usr/bin/env python3
"""reparse_lines.py - re-read every stored ingredient line with the current parser.

TWO PHASES, and the order is the whole point.

  1. CATCH-UP. Re-split every `reason='original'` baseline from ITS OWN text. This is the debt
     ed6aaf5 left: it lifted the counting noun on 73 live rows on 2026-09-23 and touched no
     baseline, so the page has been showing 73 amount edits nobody made. Catch-up cancels them and
     leaves the genuine edits standing.

  2. REPARSE. Re-split the live rows, in lockstep with their baselines (resplit.write_lockstep).

⚠️ CATCH-UP RUNS FIRST BECAUSE RULE 2 DEPENDS ON IT. "A row whose live line differs from its
baseline is the cook's edit, skip it" is only true once the baseline has stopped carrying the
parser's own history. Run the other way round, 73 phantom edits would each veto their own row.

THE HARD RULES. A row breaking one is EXCLUDED and named in the CSV with the rule it broke.

  1. Never lose information. A stored amount survives a raw_text that no longer carries one.
     (Held inside resplit.split_columns, so every re-split path gets it.)
  2. Never overwrite an edit. A row carrying an annotation AFTER catch-up is the cook's, and so is
     a row with a non-empty note.
  3. Never turn an ingredient into a heading and never delete a row.
     (Held inside resplit.split_columns, which returns None for a section or an empty name.)
  4. Never touch a row named in hand_repoints.csv. Its line_check compares the stored text and
     halts build_links.py when it no longer matches, so these belong to the linkage pass.
  5. Lockstep applies to every change.

Usage:
    python3 scripts/reparse_lines.py --db /tmp/copy.db                 # dry run + CSV
    python3 scripts/reparse_lines.py --db /tmp/copy.db --apply         # write
"""
import argparse
import collections
import csv
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import resplit                                   # noqa: E402  THE shared re-split path
from snapshot_serialize import content_blob      # noqa: E402

CSV_OUT = REPO / "previews" / "reparse2-dryrun.csv"
HAND = REPO / "hand_repoints.csv"


def hand_repointed():
    """{(recipe_id, position)} named in hand_repoints.csv."""
    out = set()
    for line in open(HAND, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("action,"):
            continue
        r = next(csv.reader([line]))
        out.add((r[1], int(r[2])))
    return out


def annotations(db, rids):
    """{recipe_id: [entry, ...]} through the app's own diff, so "is this an edit" is the app's
    answer and not a second opinion."""
    import app, models
    app.DB = pathlib.Path(db)
    models.DB = pathlib.Path(db)
    with app.orm_session() as s:
        return {rid: app._recipe_annotations(s, rid) or [] for rid in rids}


# --------------------------------------------------------------------------------------------- #
# Phase 1: catch-up
# --------------------------------------------------------------------------------------------- #
CATCHUP_KEYS = ("qty", "label")


def plan_catchup(conn):
    """{recipe_id: {position: cols}} for every baseline a live re-split LEFT BEHIND.

    ⚠️ CATCH-UP ONLY EVER CANCELS DEBT. It never runs ahead of the live row. A baseline is caught
    up only when re-splitting its own text lands it exactly where the live row already is, which
    is the definition of "the live row was re-split and this one was not". Re-splitting every
    stale baseline instead moves 401 rows and MINTS annotations: acqua-pazza[5]'s live row still
    holds qty '2', so lifting its baseline to '2 cloves' invents the very phantom this exists to
    remove. A baseline whose live row has not moved yet is left for phase 2, where lockstep takes
    both together.
    """
    plan = collections.defaultdict(dict)
    for rid, in conn.execute("SELECT DISTINCT recipe_id FROM recipe_snapshots WHERE reason='original'"):
        hints = resplit.recipe_hints(conn, rid)
        live = {r[0]: r for r in conn.execute(
            "SELECT position, qty, quantity, unit, label FROM recipe_ingredients "
            "WHERE recipe_id=? AND is_heading=0", (rid,))}
        _snap_id, _doc, at = resplit.baseline_rows(conn, rid)
        for pos, row in at.items():
            if row.get("is_heading") or pos not in live:
                continue
            got = resplit.plan_row(row, hints)
            if not got:
                continue
            merged = dict(row, **got)
            lv = dict(zip(("position", "qty", "quantity", "unit", "label"), live[pos]))
            if all((merged.get(k) or None) == (lv.get(k) or None) for k in CATCHUP_KEYS):
                plan[rid][pos] = got
    return plan


def apply_catchup(conn, plan):
    n = 0
    for rid, bypos in plan.items():
        snap_id, doc, at = resplit.baseline_rows(conn, rid)
        if snap_id is None:
            continue
        for pos, cols in bypos.items():
            at[pos].update(cols)
            n += 1
        conn.execute("UPDATE recipe_snapshots SET content = ? WHERE id = ?",
                     (content_blob(doc["recipe"], doc["ingredients"], doc["steps"]), snap_id))
    return n


# --------------------------------------------------------------------------------------------- #
# Phase 2: the live reparse
# --------------------------------------------------------------------------------------------- #
def _edited_positions(anns):
    """Heading-EXCLUDED positions carrying an ingredient annotation, keyed as snapshot_diff keys
    them (new_pos over real rows only)."""
    return {a["new_pos"] for a in anns
            if a.get("kind") == "ingredient" and a.get("new_pos") is not None}


def _real_index(conn, rid):
    """{heading-excluded index -> stored position}, the mapping snapshot_diff's new_pos uses."""
    out, i = {}, 0
    for pos, is_h in conn.execute("SELECT position, is_heading FROM recipe_ingredients "
                                  "WHERE recipe_id=? ORDER BY position", (rid,)):
        if not is_h:
            out[i] = pos
            i += 1
    return out


def plan_reparse(conn, anns, hand):
    """[row dicts] for every live line the reparse touches or refuses, with its verdict."""
    out = []
    for rid, in conn.execute("SELECT DISTINCT recipe_id FROM recipe_ingredients ORDER BY recipe_id"):
        hints = resplit.recipe_hints(conn, rid)
        idx = _real_index(conn, rid)
        edited = {idx[i] for i in _edited_positions(anns.get(rid, [])) if i in idx}
        for row in conn.execute(
                """SELECT position, qty, quantity, unit, label, note, raw_text
                     FROM recipe_ingredients WHERE recipe_id=? AND is_heading=0
                    ORDER BY position""", (rid,)):
            pos, qty, quantity, unit, label, note, raw = row
            d = {"recipe_id": rid, "position": pos, "raw_text": raw,
                 "old_qty": qty or "", "old_quantity": quantity or "", "old_unit": unit or "",
                 "old_label": label or ""}
            got = resplit.split_columns(raw, qty, hints)
            if got is None:
                continue                                  # rule 3, and it is not a candidate
            cols = {k: v for k, v in got.items() if (dict(zip(
                ("qty", "quantity", "unit", "label"), (qty, quantity, unit, label))).get(k) or None)
                != (v or None)}
            if not cols:
                continue
            d.update({"new_qty": cols.get("qty", qty) or "", "new_quantity": cols.get("quantity", quantity) or "",
                      "new_unit": cols.get("unit", unit) or "", "new_label": cols.get("label", label) or "",
                      "changed": " ".join(sorted(cols))})
            if (rid, pos) in hand:
                d["verdict"] = "EXCLUDED: rule 4, named in hand_repoints.csv"
            elif (note or "").strip():
                d["verdict"] = "EXCLUDED: rule 2, the row carries a note"
            elif pos in edited:
                d["verdict"] = "EXCLUDED: rule 2, the row carries an edit"
            else:
                d["verdict"] = "WRITE"
                d["_cols"] = cols
            out.append(d)
    return out


def classify(d):
    """IMPROVE / NEUTRAL by what actually moves. WORSE is never assigned here: it is a READING,
    and the report lists every changed row for that reading rather than trusting this."""
    before = (d["old_label"] or d["raw_text"])
    after = (d["new_label"] or d["raw_text"])
    if d["old_qty"] != d["new_qty"] or d["old_unit"] != d["new_unit"]:
        return "AMOUNT MOVES"
    if before != after:
        return "NAME MOVES"
    return "NEUTRAL"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default=str(CSV_OUT))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    hand = hand_repointed()
    rids = [r[0] for r in conn.execute("SELECT id FROM recipes ORDER BY id")]

    before_anns = annotations(args.db, rids)
    cu = plan_catchup(conn)
    n_cu_rows = sum(len(v) for v in cu.values())
    print(f"PHASE 1 catch-up: {n_cu_rows} baseline rows over {len(cu)} recipes")

    conn.execute("BEGIN")
    apply_catchup(conn, cu)
    conn.execute("COMMIT")
    after_cu = annotations(args.db, rids)

    plan = plan_reparse(conn, after_cu, hand)
    writes = [d for d in plan if d["verdict"] == "WRITE"]
    print(f"\nPHASE 2 reparse: {len(plan)} rows differ, {len(writes)} would be written")
    print(f"  verdicts: {dict(collections.Counter(d['verdict'] for d in plan))}")
    print(f"  shape of the writes: {dict(collections.Counter(classify(d) for d in writes))}")

    pathlib.Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    cols = ["recipe_id", "position", "verdict", "changed", "raw_text", "old_qty", "new_qty",
            "old_quantity", "new_quantity", "old_unit", "new_unit", "old_label", "new_label"]
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for d in sorted(plan, key=lambda x: (x["verdict"] != "WRITE", x["recipe_id"], x["position"])):
            w.writerow(d)
    print(f"\nCSV: {args.csv}")

    if not args.apply:
        # the catch-up was applied to get a true rule-2 reading; roll the file back by refusing to
        # keep it unless asked
        print("\nDRY RUN. The catch-up was applied to THIS DATABASE so rule 2 could be read "
              "honestly. Use a throwaway copy. Phase 2 wrote nothing.")
        return 0

    conn.execute("BEGIN")
    for d in writes:
        resplit.write_lockstep(conn, d["recipe_id"], {d["position"]: d["_cols"]},
                               resplit.recipe_hints(conn, d["recipe_id"]))
    conn.execute("COMMIT")
    print(f"\nAPPLIED: catch-up {n_cu_rows} baseline rows, reparse {len(writes)} live rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
