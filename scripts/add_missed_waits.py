#!/usr/bin/env python3.13
"""add_missed_waits.py - the plan-ahead waits a step stated and the import never captured.

Round A item 2. Every row marked yes in docs/data-repairs/waits-missed-multi-duration-*.csv, except
one that measurement showed would double-count (see SKIP below).

⚠️ LOCKSTEP, AND THE WAITS KEY IS THE REASON IT MATTERS. content_blob omits `waits` from a snapshot
   when the list is empty, so a recipe that GAINS its first wait stops being byte-equal to its
   baseline and every one of its waits then reports as "added" in the cook's changes. Patching the
   baseline in the same transaction is what keeps the change invisible, which is correct: the app is
   reading a duration the recipe always stated, not recording something the cook did.

⚠️ THE KIND AND THE WORDS ARE A JUDGEMENT AND ARE WRITTEN OUT HERE, one line per wait, rather than
   derived from the sentence. read_duration turns the words into minutes and the expected figures are
   asserted before anything is written, so a typo in a label fails loudly instead of storing a wrong
   range.

⚠️ 'overnight' AS THE UPPER END KEEPS ITS WORD. "at least 30 minutes or overnight" is 30 minutes to
   8 hours, and the ceiling is written as the word because that is what the recipe says and what
   planahead.display_label leaves alone. See Round A item 5.
"""
import argparse
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # for corpus_guard
from corpus_guard import BASE, refuse_live                        # noqa: E402
import planahead                                                 # noqa: E402
import snapshot_serialize                                        # noqa: E402

# recipe_id -> (step_row_id, kind, label, expected_min, expected_max)
WAITS = {
    "agedashi-tofu":                          (1659, "soaking",    "2 hr – overnight", 120, 480),
    "apple-pie":                              (1690, "resting",    "at least 3 hr", 180, None),
    "blueberry-muffin-sugar-cookies":         (1841, "resting",    "30 min", 30, 30),
    "earl-grey-tea-cake":                     (2337, "soaking",    "30 min – 1 hr", 30, 60),
    "french-fries":                           (2452, "resting",    "30 min", 30, 30),
    "key-lime-pie":                           (2643, "resting",    "about 1 hr", 60, 60),
    "kfc-spicy-chicken-rice-bowl":            (2651, "marinating", "20 min – overnight", 20, 480),
    "mocha-chocolate-chunk-cookies":          (2919, "resting",    "30 min", 30, 30),
    "no-knead-bread":                         (4556, "rising",     "2–3 hr", 120, 180),
    "pepper-steak":                           (3191, "marinating", "30 min – overnight", 30, 480),
    "pumpkin-scones":                         (3275, "resting",    "30 min", 30, 30),
    "red-wine-braised-short-ribs":            (3339, "brining",    "2–6 hr", 120, 360),
    "thai-tea-ice-cream-chatramues-thai-tea": (3772, "chilling",   "6–8 hr", 360, 480),
}

# ⚠️ MARKED YES AND DELIBERATELY NOT ADDED, because adding it would make the recipe wrong.
#    salt-and-pepper-tofu step 3 opens "After 1 to 2 hours, drain the liquid", which is a BACK
#    REFERENCE to the brine step 2 already states, and that brine is already stored as a 1-2 hr
#    brining wait on step 2. A second wait would tell a cook to set aside 2 to 4 hours for one brine.
#    The scan could not see this because the two durations sit on different step rows.
SKIP = {"salt-and-pepper-tofu": "the 1-2 hr is a back reference to the brine already stored on step 2"}

# ⚠️ THE TWO EXTENSIONS DESCRIBED IN A STEP OF THEIR OWN. Round A item 3. The other 5 state the
#    alternative in the wait's own step and stay NULL, because a second link to the step already
#    named above says nothing. ext_step_id is not in SNAPSHOT_WAIT_FIELDS, so these need no baseline
#    patch: the pointer is provenance, not content.
EXT_LINKS = {
    "beans": 1779,            # "QUICK SOAK", the method for the 90 minute alternative
    "brioche-bread": 1874,    # "If you want to skip the overnight proof..."
}

# ⚠️ THE TWO RECIPES WHOSE TOTAL NEEDS A RULING, AND THIS IS THE ONE PLACE A RULING LIVES. Each is a
#    recipe a rule put on a review list and a person then answered, which is the only shape a
#    one-off row write takes here. miso-tofu states a 25 min total and marinates for a further 15 to
#    20, so the total EXCLUDES the wait and the waits are added to it. The other nine recipes flagged
#    as unclear want exactly what the rule already does, so they stay NULL.
#    all-butter-pie-crust was flagged by planahead.stated_total_verdict on 2026-10-07, which could
#    not settle it: the recipe states 1 hr 15 min with a 1 hr chill and NO cook time, so the rule has
#    no upper bound to compare against and says "unclear" rather than guessing. Andy read the recipe
#    and answered it. 15 min hands-on plus the 1 hr chill is the stated 1 hr 15 min, so the author
#    counted the wait. The crust alone is never baked, which is why cook_time is empty and why the
#    arithmetic the rule wanted was unavailable to it.
#    ⚠️ A 1 CHANGES NO FIGURE ON THE PAGE HERE, and that is the point. recipe_total already shows a
#    stated total unchanged, so the Total stays "1 hr 15 min" either way. What the ruling does is end
#    the question, so the recipe leaves reports/total-vs-waits.csv instead of being asked again every
#    time the survey runs.
#    total_includes_waits is not in SNAPSHOT_RECIPE_FIELDS, so this needs no baseline patch.
TOTAL_RULINGS = {"miso-tofu-recipe": 0, "all-butter-pie-crust": 1}


def _patch_baseline_waits(stored, waits):
    body = json.loads(stored)
    if waits:
        body["waits"] = [{k: w.get(k) for k in snapshot_serialize.SNAPSHOT_WAIT_FIELDS} for w in waits]
    else:
        body.pop("waits", None)
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run(db, apply_it):
    # ⚠️ EVERY LABEL IS CHECKED AGAINST ITS EXPECTED FIGURES BEFORE A SINGLE ROW IS WRITTEN. The
    #    reader misreads a mixed number ("2 1/2 hrs" reads as 2 hr, taking the denominator), so a
    #    label that does not produce what this table says it should must stop the run, not store a
    #    quietly wrong range.
    for rid, (_sid, _kind, label, lo, hi) in sorted(WAITS.items()):
        got = planahead.read_duration(label)
        if got != (lo, hi):
            raise SystemExit(f"ABORT: {rid} label {label!r} reads {got}, expected {(lo, hi)}")

    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    added, skipped = [], []
    for rid, (sid, kind, label, lo, hi) in sorted(WAITS.items()):
        step = c.execute("SELECT id, position, is_heading FROM recipe_steps WHERE id=? AND recipe_id=?",
                         (sid, rid)).fetchone()
        if step is None or step["is_heading"]:
            skipped.append((rid, sid, "no such ordinary step")); continue
        stored = c.execute("SELECT content FROM recipe_snapshots WHERE recipe_id=? AND reason='original'",
                           (rid,)).fetchone()
        if stored is None:
            skipped.append((rid, sid, "no baseline")); continue
        dupe = c.execute("SELECT id FROM recipe_waits WHERE recipe_id=? AND step_id=? AND label=?",
                         (rid, sid, label)).fetchone()
        if dupe:
            skipped.append((rid, sid, "already stored")); continue
        c.execute("INSERT INTO recipe_waits (recipe_id, position, kind, label, min_minutes, "
                  "max_minutes, when_kind, step_id) VALUES (?,?,?,?,?,?, 'always', ?)",
                  (rid, 10_000 + sid, kind, label, lo, hi, sid))
        # ⚠️ RENUMBERED BY THE STEP THE WAIT COMES FROM, not by insertion order. A cook reads the
        #    method top to bottom and the breakdown has to agree with it. A wait with no step keeps
        #    its relative place at the end.
        rows = [dict(r) for r in c.execute(
            "SELECT w.*, s.position AS sp FROM recipe_waits w LEFT JOIN recipe_steps s ON s.id=w.step_id "
            "WHERE w.recipe_id=? ORDER BY COALESCE(s.position, 99999), w.id", (rid,))]
        for i, w in enumerate(rows):
            c.execute("UPDATE recipe_waits SET position=? WHERE id=?", (-1 - i, w["id"]))
        for i, w in enumerate(rows):
            c.execute("UPDATE recipe_waits SET position=? WHERE id=?", (i, w["id"]))
            w["position"] = i
        c.execute("UPDATE recipe_snapshots SET content=? WHERE recipe_id=? AND reason='original'",
                  (_patch_baseline_waits(stored["content"], rows), rid))
        added.append((rid, sid, kind, label, lo, hi, len(rows)))

    for rid, sid in sorted(EXT_LINKS.items()):
        step = c.execute("SELECT id FROM recipe_steps WHERE id=? AND recipe_id=? AND is_heading=0",
                         (sid, rid)).fetchone()
        if step is None:
            skipped.append((rid, sid, "ext link: no such ordinary step")); continue
        # ⚠️ COUNT FIRST, THEN WRITE ONE ROW BY ID. This read UPDATE-then-check, so an unexpected
        #    match count was REPORTED as skipped and WRITTEN anyway: a recipe with two waits that each
        #    state an alternative got the pointer on both, and the printout said nothing was done.
        #    `step_id IS NULL OR step_id <> ?` because NULL <> 1779 is NULL, not true, so a wait with
        #    no step of its own was silently never eligible.
        hits = [r["id"] for r in c.execute(
            "SELECT id FROM recipe_waits WHERE recipe_id=? AND ext_label IS NOT NULL "
            "AND (step_id IS NULL OR step_id <> ?)", (rid, sid))]
        if len(hits) != 1:
            skipped.append((rid, sid, f"ext link: matched {len(hits)} waits, expected 1. Nothing written"))
            continue
        c.execute("UPDATE recipe_waits SET ext_step_id=? WHERE id=?", (sid, hits[0]))

    for rid, ruling in sorted(TOTAL_RULINGS.items()):
        if c.execute("SELECT 1 FROM recipes WHERE id=?", (rid,)).fetchone() is None:
            skipped.append((rid, None, "no such recipe")); continue
        c.execute("UPDATE recipes SET total_includes_waits=? WHERE id=?", (ruling, rid))

    if apply_it:
        c.commit()
    else:
        c.rollback()
    return added, skipped



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-mean-live", action="store_true")
    a = ap.parse_args()
    refuse_live(a.db, a.i_mean_live)
    added, skipped = run(a.db, a.apply)
    print(f"{'APPLIED' if a.apply else 'DRY RUN'}  {a.db}")
    print(f"  waits added: {len(added)}   (of {len(WAITS)} in the table, {len(SKIP)} deliberately not in it)")
    for rid, sid, kind, label, lo, hi, n in added:
        print(f"    {rid:42s} step {sid:<6d} {kind:11s} {label!r:22s} ({lo}, {hi})  recipe now has {n}")
    for rid, why in sorted(SKIP.items()):
        print(f"    NOT ADDED  {rid}: {why}")
    for rid, sid in sorted(EXT_LINKS.items()):
        print(f"    ext_step_id={sid} on {rid}")
    for rid, ruling in sorted(TOTAL_RULINGS.items()):
        print(f"    total_includes_waits={ruling} on {rid}")
    if skipped:
        print(f"  SKIPPED: {skipped}")


if __name__ == "__main__":
    main()
