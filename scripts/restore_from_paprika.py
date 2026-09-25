#!/usr/bin/env python3
"""restore_from_paprika.py - put the amount back into raw_text from the Paprika archive.

WHAT WENT WRONG. Until e7835cb, every save rewrote `raw_text` with the DISPLAYED name and NULLed
`label`, so "2 tbsp extra virgin olive oil" became "extra virgin olive oil" and the amount fell out
of the stored source line. The measurement is previews/save-path-scoping.md: 373 rows across 31
recipes already damaged. The save is fixed, so nothing new is being lost. This repairs what was.

THE REPAIR, one row at a time:

    label    <- the row's CURRENT display text, which is `label || raw_text` as it reads today
    raw_text <- the archive line

Both move together on purpose. Everything that reads an ingredient resolves it as `label ||
raw_text` (the reading view at app.js, linkage_matcher, snapshot_diff._ing_name, the save's own
carry key), so setting `label` to exactly what that expression resolves to today leaves every one
of them reading the same string. The repair is invisible on screen. What it restores is the source
line underneath.

⚠️ ROWS ARE MATCHED ON (recipe_id, position), NEVER ON id. The save deletes and reinserts every
row of a recipe, so `recipe_ingredients.id` churns on any ordinary save and would survive nothing.

⚠️ TWO PARTS, AND PART B IS A ONE-OFF. Part A repairs the live rows. Part B repairs the
`reason='original'` snapshots, which hold the damaged text because
scripts/backfill_original_snapshots.py minted each baseline from the rows AS THEY STOOD, already
damaged. The archive is the true original, so the baseline is corrected to it. See
docs/design-decisions.md for why that is a correction rather than a rewrite of history.

⚠️ A SNAPSHOT ROW KEEPS ITS OWN DISPLAY TEXT, not the live row's. An edit made since the baseline
was minted has to stay visible in the crossed-out view, so the baseline's `label` is set from the
BASELINE's `label || raw_text`, which may differ from the live row's.

IDEMPOTENT, and the claim rule is what makes it so. Only a NULL-`label` row is ever a candidate,
and a repaired row has one, so a second run plans nothing and Part B derives from Part A. That
alone is not enough: an archive line claimed by one row must STAY claimed once that row is
repaired, or a row refused as ambiguous on the first run would seize the line on the second. Every
row that already holds an archive line therefore claims it, candidate or not. Both parts commit in
ONE transaction, so a failure leaves neither half applied.

⚠️ THE ARCHIVE IS GITIGNORED (235 MB, `*.paprikarecipes`), so a fresh clone cannot recompute this
plan. The committed CSVs under docs/data-repairs/ are the durable record of what was changed.

Usage:
    python3 scripts/restore_from_paprika.py                       # dry run on recipes.db
    python3 scripts/restore_from_paprika.py --db /tmp/copy.db     # dry run on a copy
    python3 scripts/restore_from_paprika.py --db /tmp/copy.db --apply
"""
import argparse
import collections
import csv
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import paprika_native_reader as pr                    # noqa: E402
from snapshot_serialize import content_blob           # noqa: E402  THE snapshot format, single-sourced

ARCHIVE = REPO / "My Recipes.paprikarecipes"
CSV_DIR = REPO / "docs" / "data-repairs"

LIVE_CSV = "paprika-restore-live-rows.csv"
SNAP_CSV = "paprika-restore-snapshot-rows.csv"

# The reviewed plan. The run STOPS rather than writing if it no longer matches these.
# ⚠️ Part B's SPLIT of the 39 it leaves alone was first reported as 28 and 11, which was wrong and
#    came from a count taken by hand. 31 and 8 is what the data says, reproduced byte-exact, under
#    case-and-space folding, and against the earlier database state the plan was first reviewed on.
#    The 261 rows it CHANGES were the same under every reading.
EXPECTED_LIVE = {"RESTORE": 300, "SKIP: nothing was lost": 44, "SKIP: no archive record": 17,
                 "SKIP: no match": 10, "SKIP: ambiguous": 2}
EXPECTED_SNAP = {"CORRECT": 261, "SKIP: already the archive line": 31,
                 "SKIP: holds something else": 8}


def one(s):
    return " ".join(str(s or "").split())


def low(s):
    return one(s).lower()


# --------------------------------------------------------------------------------------------- #
# The archive
# --------------------------------------------------------------------------------------------- #
def load_archive(uids, path=ARCHIVE):
    """{uid: [ingredient line, ...]} for the uids asked for.

    ⚠️ ingredient_lines returns (lines, blank_count), a TUPLE. Taking the return value as the list
    is the error that made an earlier count of this same repair meaningless, so the [0] is the
    whole point of this line."""
    if not Path(path).exists():
        raise SystemExit(f"⚠️  the Paprika archive is not here: {path}\n"
                         "    It is gitignored (235 MB). This plan cannot be recomputed without it.\n"
                         "    The record of what was applied is in docs/data-repairs/.")
    arc = {}
    with zipfile.ZipFile(path) as zf:
        for _name, rec, err in pr.iter_entries(zf):
            if err or not rec:
                continue
            uid = rec.get("uid")
            if uid in uids and uid not in arc:
                arc[uid] = pr.ingredient_lines(rec.get("ingredients") or "")[0]
                if len(arc) == len(uids):
                    break
    return arc


# --------------------------------------------------------------------------------------------- #
# Part A: the live rows
# --------------------------------------------------------------------------------------------- #
def plan_live(conn):
    """One entry per damaged row, in (recipe_id, position) order, with its verdict.

    ⚠️ AN ARCHIVE LINE IS CLAIMED ONCE, IN POSITION ORDER. A recipe listing the same ingredient
    twice ("2 tbsp water", "3 tbsp water") has two archive lines containing "water", so a
    contains-test alone is ambiguous on both rows. Walking the rows in position order and taking
    the first unclaimed line resolves them, the same rule the save's carry map uses."""
    damaged = {r[0] for r in conn.execute(
        "SELECT DISTINCT recipe_id FROM recipe_ingredients WHERE is_heading = 0 "
        "AND label IS NULL AND raw_text IS NOT NULL AND raw_text <> ''")}
    rows = [r for r in conn.execute(
        """SELECT ri.recipe_id, ri.position, ri.qty, ri.label, ri.raw_text, r.uid
             FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id
            WHERE ri.is_heading = 0
              AND ri.raw_text IS NOT NULL AND ri.raw_text <> ''
            ORDER BY ri.recipe_id, ri.position""").fetchall() if r[0] in damaged]
    arc = load_archive({r[5] for r in rows if r[5]})
    claimed = collections.defaultdict(set)
    plan, tally = [], collections.Counter()

    for recipe_id, position, qty, label, raw, uid in rows:
        display = label or raw                       # what the page shows today
        lines = arc.get(uid) or []
        # ⚠️ A ROW THAT ALREADY HOLDS AN ARCHIVE LINE CLAIMS IT, repaired or never damaged. Without
        #    this the run is not idempotent AND the second run is WRONG. Two archive lines merge two
        #    ingredients into one ("...10 to 12 ounces each 2 teaspoons kosher salt, plus more for
        #    the sauce"), where the first row claims the line and the second is refused as
        #    ambiguous. Let the claim lapse once the first row is repaired and the salt row takes a
        #    line that opens with snapper fillets.
        already = next((i for i, l in enumerate(lines)
                        if low(l) == low(raw) and i not in claimed[uid]), None)
        if label is not None:                        # not a candidate: it only ever claims
            if already is not None:
                claimed[uid].add(already)
            continue

        # CONFIDENT = an archive line CONTAINS this text and is longer than it
        hits = [l for l in lines if low(raw) and low(raw) in low(l) and low(l) != low(raw)]
        chosen = None

        if already is not None:
            claimed[uid].add(already)
            verdict = "SKIP: nothing was lost"
        elif any(low(l) == low(raw) for l in lines):
            verdict = "SKIP: nothing was lost"       # its line is held by an earlier row
        elif len(hits) == 1:
            idx = lines.index(hits[0])
            if idx in claimed[uid]:
                verdict = "SKIP: ambiguous"
            else:
                claimed[uid].add(idx)
                chosen, verdict = hits[0], "RESTORE"
        elif len(hits) > 1:
            free = [i for i, l in enumerate(lines) if l in hits and i not in claimed[uid]]
            if free:
                claimed[uid].add(free[0])
                chosen, verdict = lines[free[0]], "RESTORE"
            else:
                verdict = "SKIP: ambiguous"
        elif not lines:
            verdict = "SKIP: no archive record"
        else:
            verdict = "SKIP: no match"

        tally[verdict] += 1
        new_label = display if chosen else None
        plan.append(dict(
            recipe_id=recipe_id, position=position, qty=qty or "", verdict=verdict,
            old_label="" if label is None else label, old_raw=raw,
            new_label=new_label or "", new_raw=chosen or "",
            display_before=display,
            # the invariant, resolved the way every reader resolves it rather than asserted
            display_after=(new_label or chosen) if chosen else display))
    return plan, tally


# --------------------------------------------------------------------------------------------- #
# Part B: the 'original' snapshots
# --------------------------------------------------------------------------------------------- #
def plan_snapshots(conn, live_plan):
    """One entry per live RESTORE, classifying the baseline row at the same position."""
    wanted = collections.defaultdict(list)
    for p in live_plan:
        if p["verdict"] == "RESTORE":
            wanted[p["recipe_id"]].append(p)

    plan, tally = [], collections.Counter()
    for recipe_id, items in sorted(wanted.items()):
        row = conn.execute("SELECT id, content FROM recipe_snapshots "
                           "WHERE recipe_id = ? AND reason = 'original'", (recipe_id,)).fetchone()
        if row is None:
            tally["SKIP: no original snapshot"] += len(items)
            continue
        snap_id, content = row
        doc = json.loads(content)
        at = {x["position"]: x for x in doc.get("ingredients") or [] if x.get("position") is not None}

        for p in items:
            x = at.get(p["position"])
            if x is None:
                tally["SKIP: no baseline row at that position"] += 1
                continue
            snap_label, snap_raw = x.get("label"), x.get("raw_text") or ""
            snap_display = snap_label or snap_raw     # ⚠️ the BASELINE's own text, not the live row's

            if low(snap_raw) == low(p["old_raw"]):
                verdict, new_label, new_raw = "CORRECT", snap_display, p["new_raw"]
            elif low(snap_raw) == low(p["new_raw"]):
                verdict, new_label, new_raw = "SKIP: already the archive line", None, None
            else:
                verdict, new_label, new_raw = "SKIP: holds something else", None, None

            tally[verdict] += 1
            plan.append(dict(
                snapshot_id=snap_id, recipe_id=recipe_id, position=p["position"], verdict=verdict,
                old_label="" if snap_label is None else snap_label, old_raw=snap_raw,
                new_label=new_label or "", new_raw=new_raw or "",
                display_before=snap_display,
                display_after=(new_label or new_raw) if new_raw else snap_display))
    return plan, tally


# --------------------------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------------------------- #
def apply_plans(conn, live_plan, snap_plan):
    """Both parts, ONE transaction. A row that no longer reads what was planned stops the run."""
    live_writes = [p for p in live_plan if p["verdict"] == "RESTORE"]
    snap_writes = [p for p in snap_plan if p["verdict"] == "CORRECT"]
    conn.execute("BEGIN")
    try:
        for p in live_writes:
            cur = conn.execute(
                "SELECT label, raw_text FROM recipe_ingredients "
                "WHERE recipe_id = ? AND position = ? AND is_heading = 0",
                (p["recipe_id"], p["position"])).fetchall()
            if len(cur) != 1:
                raise SystemExit(f"⚠️  {p['recipe_id']}[{p['position']}] matched {len(cur)} rows, "
                                 "expected exactly 1. Nothing was written.")
            if (cur[0][0] or "") != p["old_label"] or (cur[0][1] or "") != p["old_raw"]:
                raise SystemExit(f"⚠️  {p['recipe_id']}[{p['position']}] now reads "
                                 f"{cur[0][1]!r}, not {p['old_raw']!r}. Nothing was written.")
            conn.execute("UPDATE recipe_ingredients SET label = ?, raw_text = ? "
                         "WHERE recipe_id = ? AND position = ? AND is_heading = 0",
                         (p["new_label"], p["new_raw"], p["recipe_id"], p["position"]))

        by_snapshot = collections.defaultdict(list)
        for p in snap_writes:
            by_snapshot[p["snapshot_id"]].append(p)
        for snap_id, items in by_snapshot.items():
            content = conn.execute("SELECT content FROM recipe_snapshots WHERE id = ?",
                                   (snap_id,)).fetchone()[0]
            doc = json.loads(content)
            at = {x["position"]: x for x in doc["ingredients"] if x.get("position") is not None}
            for p in items:
                x = at[p["position"]]
                if (x.get("raw_text") or "") != p["old_raw"]:
                    raise SystemExit(f"⚠️  baseline {p['recipe_id']}[{p['position']}] now reads "
                                     f"{x.get('raw_text')!r}. Nothing was written.")
                x["label"], x["raw_text"] = p["new_label"], p["new_raw"]
            # re-serialized through THE format module, so an untouched field cannot drift
            conn.execute("UPDATE recipe_snapshots SET content = ? WHERE id = ?",
                         (content_blob(doc["recipe"], doc["ingredients"], doc["steps"]), snap_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(live_writes), len(snap_writes)


def write_csvs(live_plan, snap_plan, csv_dir):
    """Before and after for every row the run CHANGES. The audit trail, committed."""
    csv_dir = Path(csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    live_cols = ["recipe_id", "position", "qty", "old_label", "old_raw", "new_label", "new_raw",
                 "display_before", "display_after"]
    snap_cols = ["recipe_id", "position", "old_label", "old_raw", "new_label", "new_raw",
                 "display_before", "display_after"]
    for name, cols, rows in ((LIVE_CSV, live_cols, [p for p in live_plan if p["verdict"] == "RESTORE"]),
                             (SNAP_CSV, snap_cols, [p for p in snap_plan if p["verdict"] == "CORRECT"])):
        with open(csv_dir / name, "w", newline="", encoding="utf-8") as fh:
            # ⚠️ LF, not csv.writer's default CRLF. .gitattributes pins text to LF and names this
            #    exact trap: a CSV rewritten through the default turns a small edit into a
            #    whole-file diff. git normalizes on the way in, this keeps the working tree honest.
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            for r in sorted(rows, key=lambda d: (d["recipe_id"], d["position"])):
                w.writerow(r)
    return csv_dir / LIVE_CSV, csv_dir / SNAP_CSV


def report(title, tally, expected):
    print(f"\n=== {title} ===")
    for k in sorted(tally, key=lambda k: -tally[k]):
        want = expected.get(k)
        flag = "" if want is None or want == tally[k] else f"   ⚠️ reviewed plan said {want}"
        print(f"  {tally[k]:5}  {k}{flag}")
    return dict(tally) == expected


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "recipes.db"))
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--csv-dir", default=str(CSV_DIR))
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--allow-any-counts", action="store_true",
                    help="write even if the plan no longer matches the reviewed counts")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db if args.apply else f"file:{args.db}?mode=ro", uri=not args.apply)
    live_plan, live_tally = plan_live(conn)
    snap_plan, snap_tally = plan_snapshots(conn, live_plan)

    print(f"db: {args.db}")
    ok_live = report("Part A, the live rows", live_tally, EXPECTED_LIVE)
    ok_snap = report("Part B, the 'original' baselines", snap_tally, EXPECTED_SNAP)

    moved = [p for p in live_plan if p["display_before"] != p["display_after"]]
    moved += [p for p in snap_plan if p["display_before"] != p["display_after"]]
    print(f"\nrows whose displayed text would MOVE: {len(moved)}")
    for p in moved[:5]:
        print(f"   {p['recipe_id']}[{p['position']}] "
              f"{p['display_before']!r} -> {p['display_after']!r}")

    if not args.no_csv:
        a, b = write_csvs(live_plan, snap_plan, args.csv_dir)
        print(f"\nCSV: {a}\nCSV: {b}")

    if not args.apply:
        print("\nDRY RUN. Nothing was written. Pass --apply to write.")
        return 0

    if moved:
        raise SystemExit("\n⚠️  a row's displayed text would move. Nothing was written.")
    if not (ok_live and ok_snap) and not args.allow_any_counts:
        raise SystemExit("\n⚠️  the plan no longer matches the reviewed counts. Nothing was "
                         "written. Re-review, or pass --allow-any-counts if the drift is expected.")
    n_live, n_snap = apply_plans(conn, live_plan, snap_plan)
    print(f"\nAPPLIED: {n_live} live rows, {n_snap} baseline rows, one transaction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
