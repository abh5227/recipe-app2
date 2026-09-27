#!/usr/bin/env python3
"""restore_notes.py - put back the separators the old save stripped out of a note.

THE DAMAGE. The old save rebuilt `raw_text` as f"{qty} {label}{note}" from a note whose leading
separator it had already removed, so 'pinch asafetida (optional, but really great)' became
'pinch asafetidaoptional, but really great' and the note lost its parentheses. Eight rows over four
recipes. The words all survived. Only the punctuation between them went.

⚠️ IT IS NOT A RE-SPLIT AND IT MUST NOT GO THROUGH write_lockstep. Measured before writing this:
`resplit.plan_row` on each of the eight BASELINE rows wants to pull the whole clause into the name
and clear the note, because the current parser has no note concept at all. Running the lockstep
helper here would write that into the baseline and destroy the very text this restores from.

THE LOCKSTEP RULE STILL HOLDS, by construction rather than by calling the helper. The repair moves
the live row ONTO its baseline, so the two agree afterwards and no annotation can be minted. The
baseline is never written.

⚠️ raw_text IS RESTORED AND THAT IS THE SAFER DIRECTION, not the riskier one. The reparse already
wants to move all eight rows and rule 2 already holds all eight back, before and after this. What
changes is what a future pass would write if that rule were ever relaxed:
    today   'asafetidaoptional, but really great'
    after   'asafetida (optional, but really great)'

TWO ROWS GET raw_text ONLY. bulgogi-bowls[2] and gai-yang[14] moved 'finely grated' and 'finely
chopped' from the note into the NAME, where they still are. The row lost no word, so restoring
those notes would print the clause twice and resplit.redundant_note would clear it again on the
next pass. Their source line lost the same parentheses as the other six, so that half is restored.

Idempotent. A second run finds every row already at its target and writes nothing.

Usage:
    python3.13 scripts/restore_notes.py --db /tmp/copy.db              # dry run
    python3.13 scripts/restore_notes.py --db /tmp/copy.db --apply      # write
"""
import argparse
import csv
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import resplit                                          # noqa: E402  baseline_rows only

CSV_OUT = REPO / "docs" / "data-repairs" / "note-separators-2026-09-27.csv"

# (recipe_id, position, columns to restore, the live value each must currently hold)
# The TARGET is read from the row's own baseline at run time and checked against what was reviewed,
# so a moved baseline stops the run instead of being written blind.
ROWS = (
    ("aloo-gobhi", 6, ("note", "raw_text"),
     {"note": "optional, but really great",
      "raw_text": "pinch asafetidaoptional, but really great"},
     {"note": " (optional, but really great)",
      "raw_text": "pinch asafetida (optional, but really great)"}),
    ("aloo-gobhi", 9, ("note", "raw_text"),
     {"note": " about half a lime, plus more if needed",
      "raw_text": "1 tbsp lime juice about half a lime, plus more if needed"},
     {"note": " (about half a lime), plus more if needed",
      "raw_text": "1 tbsp lime juice (about half a lime), plus more if needed"}),
    ("bulgogi-bowls", 2, ("raw_text",),
     {"raw_text": "1 tbsp onion, finely grated ~¼ onion"},
     {"raw_text": "1 tbsp onion, finely grated (~¼ onion)"}),
    ("bulgogi-bowls", 6, ("note", "raw_text"),
     {"note": "all-purpose or light",
      "raw_text": "2½ tbsp soy sauceall-purpose or light"},
     {"note": " — all-purpose or light",
      "raw_text": "2½ tbsp soy sauce — all-purpose or light"}),
    # ⚠️ THE BASELINE WORDING, NOT THE ARCHIVE'S. Paprika reads '(or similar chopped leafy greens
    #    – cabbage, kale)'. The baseline is the owner's own trimmed version and is what goes back.
    ("bulgogi-bowls", 18, ("note", "raw_text"),
     {"note": " or chopped greens — cabbage, kale",
      "raw_text": "4 large handfuls baby spinach or chopped greens — cabbage, kale"},
     {"note": " (or chopped greens — cabbage, kale)",
      "raw_text": "4 large handfuls baby spinach (or chopped greens — cabbage, kale)"}),
    ("gai-yang", 13, ("note", "raw_text"),
     {"note": "store-bought or homemade",
      "raw_text": "2 tbsp tamarind pastestore-bought or homemade"},
     {"note": ", store-bought or homemade",
      "raw_text": "2 tbsp tamarind paste, store-bought or homemade"}),
    ("gai-yang", 14, ("raw_text",),
     {"raw_text": "1 tbsp palm sugar, finely choppedor light brown sugar"},
     {"raw_text": "1 tbsp palm sugar, finely chopped (or light brown sugar)"}),
    # ⚠️ ADDED 2026-09-27, AFTER THE FIRST EIGHT. This row lost MORE than a separator: the whole
    #    clause left raw_text and the save put it in `note` instead. label is NULL here, so the page
    #    falls back to raw_text, and restoring raw_text WITHOUT clearing the note would print
    #    "plus more to serve" twice. The baseline has no note, so moving live onto it does both.
    ("mussakhan", 1, ("note", "raw_text"),
     {"note": "plus more to serve", "raw_text": "extra-virgin olive oil"},
     {"note": "", "raw_text": "extra-virgin olive oil, plus more to serve"}),
    ("mussakhan", 5, ("note", "raw_text"),
     {"note": "plus more to dust", "raw_text": "1½ tbsp sumacplus more to dust"},
     {"note": ", plus more to dust", "raw_text": "1½ tbsp sumac, plus more to dust"}),
)

READ_COLS = ("qty", "quantity", "unit", "label", "note", "raw_text")


def plan(conn):
    """[(rid, pos, {col: value}, before)] for every row that is not already at its target."""
    out = []
    for rid, pos, cols, want_live, want_target in ROWS:
        got = conn.execute(
            f"SELECT {','.join(READ_COLS)} FROM recipe_ingredients "
            "WHERE recipe_id=? AND position=? AND is_heading=0", (rid, pos)).fetchone()
        if got is None:
            raise SystemExit(f"⚠️  no line at {rid!r} position {pos}.")
        row = dict(zip(READ_COLS, got))
        _snap, _doc, at = resplit.baseline_rows(conn, rid)
        base = at.get(pos) or {}
        for c in cols:
            if (base.get(c) or "") != want_target[c]:
                raise SystemExit(f"⚠️  {rid}[{pos}] baseline {c} reads {base.get(c)!r}, not "
                                 f"{want_target[c]!r}. The restore target moved.")
        at_target = all((row.get(c) or "") == want_target[c] for c in cols)
        if at_target:
            continue                                     # already restored
        for c in cols:
            if (row.get(c) or "") != want_live[c]:
                raise SystemExit(f"⚠️  {rid}[{pos}] live {c} reads {row.get(c)!r}, not "
                                 f"{want_live[c]!r}. The row drifted since it was reviewed.")
        out.append((rid, pos, {c: want_target[c] for c in cols}, row))
    return out


def apply(conn, planned):
    for rid, pos, cols, _before in planned:
        sets = ", ".join(f"{c} = ?" for c in cols)
        conn.execute(f"UPDATE recipe_ingredients SET {sets} "
                     "WHERE recipe_id = ? AND position = ? AND is_heading = 0",
                     (*cols.values(), rid, pos))
    return len(planned)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default=str(CSV_OUT))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    planned = plan(conn)
    print(f"{len(planned)} of {len(ROWS)} rows need restoring")
    for rid, pos, cols, before in planned:
        print(f"  {rid}[{pos}]  {' + '.join(sorted(cols))}")
        for c in sorted(cols):
            print(f"      {c:<9} {before.get(c)!r}\n      {'':<9} -> {cols[c]!r}")
    if args.apply and planned:
        conn.execute("BEGIN")
        apply(conn, planned)
        conn.execute("COMMIT")
        print(f"\nwrote {len(planned)} rows")

    # ⚠️ THE RECORD IS THE WHOLE REPAIR, NOT THIS RUN'S DELTA. Writing only what a run changed made
    #    the second run overwrite the record of the first with one row, which is the opposite of an
    #    audit trail. Every row in ROWS is written every time, from the committed before/after pair,
    #    so the file is the same bytes whether it is run once or five times.
    rows = []
    for rid, pos, cols, want_live, want_target in ROWS:
        for c in cols:
            rows.append({"recipe_id": rid, "position": pos, "column": c,
                         "before": want_live[c], "after": want_target[c],
                         "source": "the row's reason='original' baseline"})
    pathlib.Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["recipe_id", "position", "column", "before", "after",
                                           "source"], lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n{len(rows)} column changes -> {args.csv}")
    conn.close()
    if not args.apply:
        print("DRY RUN. Nothing was written.")


if __name__ == "__main__":
    main()
