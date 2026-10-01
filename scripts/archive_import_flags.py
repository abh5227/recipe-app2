#!/usr/bin/env python3
"""archive_import_flags.py — move the finished import review queue out of the working table.

WHAT MOVES. Every import_flags row that carries a POSITION. Measured on live: 562 of 595 rows, over
five flags — ambiguous_section 471, grams_declined 37, section_suggested 30, each_multi 18,
multiplier 6. The importer wrote them to record what it declined to guess about a specific ingredient
line, under decline-over-guess, and the decisions have since been made.

⚠️ NOTHING READS THEM, CONFIRMED BY MEASUREMENT RATHER THAN BY GREP ALONE. Two things read
import_flags at all. app.update_recipe looks for flag='imported_via' to decide whether a recipe's
reason='original' baseline is captured on its first save, and that flag carries no position.
scripts/backfill_headings.py reads flag='ambiguous_section' rows whose reason suggests a section — and
that script is SPENT: all 18 such rows on live are already is_heading=1, so its Bucket A is fully
applied. A stale reader was the real risk here, and it is the one that had to be checked.

⚠️ WHAT STAYS. The 2 imported_via rows, which are live. And the 31 other unpositioned rows
(no_directions 26, no_ingredients 3, photo_only 2), which name a RECIPE rather than a line and so have
not gone stale the way a position has.

⚠️ WHY THE POSITIONS ARE THE ONES TO GO. position records the ingredient slot as it stood at import.
Rows have been inserted, deleted and reordered since, so it names a line only by accident now. Leaving
them in the working table invites a future join on a pointer that no longer points.

RECOVERABLE, NOT DELETED. Rows move to import_flags_archive (migration 055) keeping their original id,
so putting them back is one statement:

    INSERT INTO import_flags (id, recipe_id, position, flag, reason, created_at)
    SELECT id, recipe_id, position, flag, reason, created_at FROM import_flags_archive;

A tracked CSV under docs/data-repairs/ is written as well, so the rows survive the database too.

Run:  python3.13 backup.py
      python3.13 scripts/archive_import_flags.py                  # rehearse, write the CSV
      python3.13 scripts/archive_import_flags.py --apply
"""
import argparse
import collections
import csv
import pathlib
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # for corpus_guard
from corpus_guard import refuse_live                              # noqa: E402
CSV_OUT = REPO / "docs" / "data-repairs" / "import-flags-archived-2026-09-30.csv"
COLS = ("id", "recipe_id", "position", "flag", "reason", "created_at")
# ⚠️ THE ONE FLAG THAT IS LIVE. It carries no position, so it is outside the WHERE below anyway; it is
#    named here so the guard is explicit rather than incidental.
KEEP_FLAGS = ("imported_via",)


def run(db, apply=False, csv_out=CSV_OUT):
    conn = sqlite3.connect(db if apply else f"file:{db}?mode=ro", uri=not apply)
    conn.row_factory = sqlite3.Row
    if not conn.execute("SELECT name FROM sqlite_master WHERE name='import_flags_archive'").fetchone():
        raise SystemExit("import_flags_archive is missing — apply migration 055 first")

    rows = conn.execute(
        f"SELECT {','.join(COLS)} FROM import_flags WHERE position IS NOT NULL "
        f"AND flag NOT IN ({','.join('?' * len(KEEP_FLAGS))}) ORDER BY id", KEEP_FLAGS).fetchall()
    kept = conn.execute("SELECT flag, COUNT(*) n FROM import_flags WHERE position IS NULL "
                        "GROUP BY flag ORDER BY n DESC").fetchall()
    already = conn.execute("SELECT COUNT(*) FROM import_flags_archive").fetchone()[0]

    if apply:
        conn.executemany(
            f"INSERT INTO import_flags_archive ({','.join(COLS)}) "
            f"VALUES ({','.join('?' * len(COLS))})", [tuple(r[c] for c in COLS) for r in rows])
        conn.executemany("DELETE FROM import_flags WHERE id=?", [(r["id"],) for r in rows])
        # ⚠️ READ IT BACK, don't trust the tally. Every moved row must be in the archive, byte for
        #    byte, and gone from the working table.
        back = {r["id"]: tuple(r[c] for c in COLS) for r in conn.execute(
            f"SELECT {','.join(COLS)} FROM import_flags_archive")}
        for r in rows:
            got = back.get(r["id"])
            if got != tuple(r[c] for c in COLS):
                conn.rollback()
                raise SystemExit(f"ABORT on flag id {r['id']}: the archived row does not match the "
                                 f"original. Nothing has been written.\n  was {tuple(r[c] for c in COLS)}"
                                 f"\n  now {got}")
        left = conn.execute("SELECT COUNT(*) FROM import_flags WHERE position IS NOT NULL").fetchone()[0]
        if left:
            conn.rollback()
            raise SystemExit(f"ABORT: {left} positioned flag(s) still in import_flags")
        conn.commit()
    conn.close()

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ AN EMPTY REPORT DOES NOT OVERWRITE A COMMITTED ONE. These CSVs live in
    #    docs/data-repairs/, which holds the record of what was done to the data. The pass has
    #    already run, so a re-run finds nothing, and writing anyway truncated the record to its
    #    header line. Measured during the review: three committed files at once, from DRY RUNS.
    #    A dry run that destroys a record is not a dry run.
    if not rows:
        print(f"nothing to report, so {csv_out} is left exactly as it is")
    else:
        with open(csv_out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(COLS)
            w.writerows([tuple(r[c] for c in COLS) for r in rows])

    by_flag = collections.Counter(r["flag"] for r in rows)
    print(f"{'APPLIED' if apply else 'REHEARSAL'} — {len(rows)} positioned flag(s) "
          f"{'moved to' if apply else 'would move to'} import_flags_archive"
          f"{f' ({already} already there)' if already else ''}")
    for flag, n in by_flag.most_common():
        print(f"    {flag:22} {n}")
    print(f"  staying in import_flags: {sum(r['n'] for r in kept)} unpositioned row(s)")
    for r in kept:
        print(f"    {r['flag']:22} {r['n']}" + ("   <- live, read by update_recipe"
                                                if r["flag"] in KEEP_FLAGS else ""))
    print(f"  audit: {csv_out.relative_to(REPO) if csv_out.is_relative_to(REPO) else csv_out}")
    return len(rows), by_flag


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(REPO / "recipes.db"))
    ap.add_argument("--apply", action="store_true", help="write (default is a read-only rehearsal)")
    ap.add_argument("--csv", default=str(CSV_OUT))
    ap.add_argument("--i-mean-live", action="store_true",
                    help="required to write the repo's own recipes.db")
    a = ap.parse_args()
    # ⚠️ THE SHARED GUARD. A live run is a sentence a person had to type. See
    #    scripts/corpus_guard.py — one definition, every script that can write.
    refuse_live(a.db, a.i_mean_live)
    run(a.db, apply=a.apply, csv_out=pathlib.Path(a.csv))
