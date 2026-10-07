#!/usr/bin/env python3.13
"""scan_total_vs_waits.py - which recipes the page cannot tell about their own stated total.

⚠️ IT WRITES NOTHING TO THE RECIPE DATA, EVER. It produces a review list and stops, exactly as
scan_notes_for_waits.py does, and for the same reason: what it hands over is a judgement.

THE QUESTION. A recipe's author states a total, and the recipe also carries waits that ALWAYS
apply. Did the author count them? planahead.stated_total_verdict answers it three ways and this
script reports the one it refuses to answer:

  excludes     the stated total is SHORTER than those waits alone, so it cannot contain them. The
               page adds them and says "(incl. plan ahead)", and keeps the author's own figure on
               a line below. Arithmetic, not a guess, so nothing to review.
  unclear      long enough to hold them, short enough that it might not. THIS LIST.
  includes     prep + cook + the waits fits inside the stated total.

⚠️ A RECORDED DECISION IS NOT A QUESTION. recipes.total_includes_waits is a person's answer to
exactly this, so a recipe carrying one is never listed. miso-tofu-recipe is the one row that has
one.

⚠️ AND THE ANSWER IS A COLUMN, NOT A HAND EDIT. A recipe decided off this list is recorded by
setting total_includes_waits (0 means the author did not count them, 1 means they did), which is
what migration 058 added the column for. Editing the stated time instead would rewrite the
author's words to work around a display rule.

Measured on live, 2026-10-07: 1 excludes (earl-grey-tea-cake), 1 unclear (all-butter-pie-crust),
1 includes (no-knead-bread), 1 already decided (miso-tofu-recipe), 296 with no question to answer.
"""
import argparse
import csv
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402
import planahead                                                            # noqa: E402

CSV_NAME = "total-vs-waits.csv"


def run(db, record=False):
    # ⚠️ mode=ro, SO SQLITE ITSELF REFUSES A WRITE rather than this file promising not to attempt
    #    one. Same shape as scripts/gates/state.py and gen_note_corpus.py.
    con = sqlite3.connect(f"file:{pathlib.Path(db)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    waits_by = {}
    for w in con.execute("SELECT * FROM recipe_waits ORDER BY recipe_id, position"):
        waits_by.setdefault(w["recipe_id"], []).append(dict(w))
    recipes = [dict(r) for r in con.execute("SELECT * FROM recipes ORDER BY id")]
    con.close()

    tally, rows = {}, []
    for r in recipes:
        waits = waits_by.get(r["id"], [])
        verdict, stated_min, wait_min = planahead.stated_total_verdict(r, waits)
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict != planahead.STATED_UNCLEAR:
            continue
        plo, _ = planahead.clock_minutes(r.get("prep_time"))
        clo, _ = planahead.clock_minutes(r.get("cook_time"))
        shown, note = planahead.recipe_total(r, waits)
        rows.append({
            "recipe_id": r["id"],
            "stated_total": r.get("total_time") or "",
            "stated_minutes": stated_min,
            "always_wait_minutes": wait_min,
            "prep_minutes": "" if plo is None else plo,
            "cook_minutes": "" if clo is None else clo,
            "why": ("prep or cook is missing, so the upper bound cannot be computed"
                    if plo is None or clo is None
                    else "the stated total sits between the waits alone and prep + cook + waits"),
            "shown_today": shown or "",
            "waits": "; ".join(f"{w['kind']} {w.get('min_minutes')}-{w.get('max_minutes')}"
                               for w in waits if planahead.counts(w)),
        })

    print(f"  recipes                       : {len(recipes)}")
    for name in (planahead.STATED_EXCLUDES, planahead.STATED_UNCLEAR,
                 planahead.STATED_INCLUDES, planahead.STATED_NO_QUESTION):
        print(f"  {name:30}: {tally.get(name, 0)}")
    for row in rows:
        print(f"      {row['recipe_id']:44s} stated {row['stated_total']!r} "
              f"({row['stated_minutes']} min) vs {row['always_wait_minutes']} min of waits")
        print(f"          {row['why']}")
    # ⚠️ A RUN THAT FOUND NOTHING WRITES NOTHING. --record on an empty run otherwise puts a
    #    header-only file into the committed folder, which truncated three records once already.
    if not rows:
        print("  nothing to review, so no list was written.")
        return rows
    target = report_target(CSV_NAME, record)
    with open(target, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  review list -> {target}")
    print("  NOTHING WAS WRITTEN. Record a decision in recipes.total_includes_waits.")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args(argv)
    refuse_live(a.db, a.i_mean_live)
    run(a.db, record=a.record)


if __name__ == "__main__":
    main()
