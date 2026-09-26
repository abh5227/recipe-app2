#!/usr/bin/env python3
"""relink_pass.py - the 2026-09-25 linkage pass, in the one order that works.

THREE PHASES, and phase 2 has to run before phase 3 or the rebuild halts.

  1. The re-split debt. `scripts/reparse_lines.py`'s own catch-up and reparse, unchanged. The
     catch-up now also clears a baseline `note` that only repeats its own label, which is the
     other half of ed6aaf5's damage. 18 baseline rows, 0 live rows.

  2. FIVE NAMED ROWS the rules refused and a person then decided. Each carries its stored
     `raw_text` and the name the re-split must produce, so a drifted line stops the run instead
     of being repaired blind.

  3. build_links.py, which rebuilds every link from committed files.

⚠️ PHASE 2 AND hand_repoints.csv ARE ONE CHANGE. Two of the five rows are named in the hand
file, whose `line_check` column holds the line as it read when the decision was made.
`apply_repoints.py` stops the whole run when that text no longer matches, so repairing the line
without updating the check halts phase 3, and updating the check without repairing the line halts
it too. They were committed together and they have to move together.

⚠️ THE OTHER THREE ROWS ARE WHY THIS SCRIPT EXISTS. ed6aaf5 lifted the counting noun into the
unit on 73 live rows and touched no baseline. The reparse repaired 70 of them. These 3 it could
not: each one's baseline was already correct, so the phantom annotation ed6aaf5 minted read as
the cook's edit under rule 2, and the row's own damage vetoed its own repair. Left alone, the
matcher reads 'cinnamon' where raw_text says '1 cinnamon stick' and links ground cinnamon.

Idempotent. A second run re-splits nothing, writes the same 2,851 links, and leaves the file
byte-identical.

Usage:
    python3.13 scripts/relink_pass.py --db /tmp/copy.db              # dry run + CSV
    python3.13 scripts/relink_pass.py --db /tmp/copy.db --apply      # write
"""
import argparse
import collections
import csv
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import build_links                                      # noqa: E402
import reparse_lines                                    # noqa: E402  phase 1, unchanged
import resplit                                          # noqa: E402

CSV_OUT = REPO / "docs" / "data-repairs" / "relink-2026-09-25.csv"

# (recipe_id, position, raw_text as stored, the name the re-split must produce, why the rules
#  refused it and a person did not)
NAMED_REPAIRS = (
    ("dan-dan-noodles", 2, "1 cinnamon stick", "cinnamon stick",
     "rule 2: ed6aaf5's own phantom read as an edit. A cinnamon stick is not ground cinnamon, "
     "and the link followed the damaged name to Q28165"),
    ("taiwanese-beef-noodle-soup", 20, "1 Chinese cinnamon stick", "Chinese cinnamon stick",
     "rule 2: same shape. Chinese cinnamon is cassia and the stick is still the whole spice"),
    ("kale-fennel-and-noodle-soup-rishta", 5, "1 fennel bulb, finely chopped",
     "fennel bulb, finely chopped",
     "rule 2: same shape. The bulb is the vegetable and bare 'fennel' reaches the seed's row"),
    ("panang-curry", 13, "1 1/4 cups coconut cream , full-fat", "coconut cream, full-fat",
     "rule 4: named in hand_repoints.csv, so the comma cleanup was held for this pass"),
    ("panang-curry", 21, "2 tbsp unsalted peanuts , finely chopped", "unsalted peanuts, finely chopped",
     "rule 4: named in hand_repoints.csv, so the comma cleanup was held for this pass"),
)

ROW_COLS = ("position", "qty", "quantity", "unit", "label", "note", "raw_text")


def _row(conn, rid, pos):
    got = conn.execute(f"SELECT {','.join(ROW_COLS)} FROM recipe_ingredients "
                       "WHERE recipe_id=? AND position=? AND is_heading=0", (rid, pos)).fetchone()
    if got is None:
        raise SystemExit(f"⚠️  no line at {rid!r} position {pos}. The repair names a row that is "
                         "not in the corpus. Fix the script rather than skipping it.")
    return dict(zip(ROW_COLS, got))


def plan_named(conn):
    """[(rid, pos, cols, why)] for the five rows, or an empty plan when they are already right."""
    out = []
    for rid, pos, raw, want, why in NAMED_REPAIRS:
        row = _row(conn, rid, pos)
        if (row["raw_text"] or "") != raw:
            raise SystemExit(f"⚠️  {rid}[{pos}] reads {row['raw_text']!r}, not {raw!r}. The "
                             "decision was made about different text, so it is not replayed.")
        cols = resplit.plan_row(row, resplit.recipe_hints(conn, rid))
        merged = dict(row, **cols)
        if (merged.get("label") or "") != want:
            raise SystemExit(f"⚠️  {rid}[{pos}] would be named {merged.get('label')!r}, not "
                             f"{want!r}. The parser no longer agrees with the decision.")
        out.append((rid, pos, cols, why))
    return out


def apply_named(conn, plan):
    n_live = n_base = 0
    for rid, pos, cols, _why in plan:
        if not cols:
            continue
        a, b = resplit.write_lockstep(conn, rid, {pos: cols}, resplit.recipe_hints(conn, rid))
        n_live += a
        n_base += b
    return n_live, n_base


def link_state(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = {(r[0], r[1]): r[2:] for r in conn.execute(
        "SELECT recipe_id, position, catalog_id, link_confidence, link_rule, link_matched, "
        "COALESCE(label, raw_text) FROM recipe_ingredients WHERE is_heading=0")}
    canon = {r[0]: r[1] for r in conn.execute("SELECT library_id, canonical FROM library_names")}
    conn.close()
    return rows, canon


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default=str(CSV_OUT))
    args = ap.parse_args()

    before_links, _ = link_state(args.db)
    conn = sqlite3.connect(args.db)
    rids = [r[0] for r in conn.execute("SELECT id FROM recipes ORDER BY id")]
    before_anns = sum(len(v) for v in reparse_lines.annotations(args.db, rids).values())
    print(f"annotations before: {before_anns}")

    # ---- phase 1 -------------------------------------------------------------------------- #
    cu = reparse_lines.plan_catchup(conn)
    n_cu = sum(len(v) for v in cu.values())
    print(f"PHASE 1 catch-up: {n_cu} baseline rows over {len(cu)} recipes")
    conn.execute("BEGIN")
    reparse_lines.apply_catchup(conn, cu)
    conn.execute("COMMIT")
    after_cu = reparse_lines.annotations(args.db, rids)
    plan = reparse_lines.plan_reparse(conn, after_cu, reparse_lines.hand_repointed())
    writes = [d for d in plan if d["verdict"] == "WRITE"]
    print(f"         reparse: {len(plan)} rows differ, {len(writes)} would be written")
    if writes:
        raise SystemExit(f"⚠️  the reparse is not settled: {len(writes)} rows want a write. This "
                         "pass expects the 2026-09-25 reparse to have already run.")

    # ---- phase 2 -------------------------------------------------------------------------- #
    named = plan_named(conn)
    print(f"PHASE 2 named repairs: {sum(1 for _r, _p, c, _w in named if c)} of "
          f"{len(NAMED_REPAIRS)} rows need a re-split")
    conn.execute("BEGIN")
    n_live, n_base = apply_named(conn, named)
    conn.execute("COMMIT")
    print(f"         {n_live} live rows, {n_base} baseline rows, in lockstep")
    conn.close()

    # ---- phase 3 -------------------------------------------------------------------------- #
    total = build_links.build(db=args.db)
    after_links, canon = link_state(args.db)
    after_anns = sum(len(v) for v in reparse_lines.annotations(args.db, rids).values())
    print(f"annotations after: {after_anns}")

    # ---- the record ----------------------------------------------------------------------- #
    rows = []
    for rid, pos, cols, why in named:
        rows.append({"recipe_id": rid, "position": pos, "change": "LINE_RESPLIT",
                     "line": _by_key(after_links, rid, pos), "detail": str(cols or "already right"),
                     "reading": why})
    for rid, bypos in sorted(cu.items()):
        for pos in sorted(bypos):
            rows.append({"recipe_id": rid, "position": pos, "change": "BASELINE_NOTE_CLEARED",
                         "line": _by_key(after_links, rid, pos),
                         "detail": str(bypos[pos]),
                         "reading": "the note only repeated the name the label already carries"})
    for key in sorted(before_links):
        b, a = before_links[key], after_links[key]
        if b[:4] == a[:4]:
            continue
        kind = ("LINK_RULE_ONLY" if b[0] == a[0] else
                "LINK_GAINED" if not b[0] else "LINK_LOST" if not a[0] else "LINK_RETARGETED")
        rows.append({"recipe_id": key[0], "position": key[1], "change": kind, "line": a[4],
                     "detail": f"{b[0] or '-'} {canon.get(b[0], '')!r} ({b[2] or '-'}) -> "
                               f"{a[0] or '-'} {canon.get(a[0], '')!r} ({a[2] or '-'})",
                     "reading": ""})
    cols_out = ["recipe_id", "position", "change", "line", "detail", "reading"]
    pathlib.Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols_out, lineterminator="\n")   # ⚠️ csv defaults to CRLF
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["change"], x["recipe_id"], int(x["position"]))):
            w.writerow(r)
    print(f"\n{len(rows)} rows -> {args.csv}")
    print("  " + str(dict(collections.Counter(r["change"] for r in rows))))
    print(f"  {total} links, annotations {before_anns} -> {after_anns}")
    if not args.apply:
        print("\nDRY RUN. Every phase was applied to THIS DATABASE, because each one has to see "
              "what the last one wrote. Use a throwaway copy.")


def _by_key(state, rid, pos):
    got = state.get((rid, pos))
    return got[4] if got else ""


if __name__ == "__main__":
    main()
