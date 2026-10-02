#!/usr/bin/env python3.13
"""scan_notes_for_waits.py - find a wait a recipe describes ONLY in its notes.

⚠️ IT WRITES NOTHING TO THE RECIPE DATA, EVER. It produces a review list and stops. A wait is a
judgement about what the author meant, which is why scripts/add_missed_waits.py carries its 94 rows
written out one per line rather than a pattern, and why this file exists to hand a person candidates
rather than to add them.

THE RULE, which is the one coconut-curried-golden-lentils fell through. A note is a candidate when
all four hold:
  1. it reads a DURATION that planahead.read_duration understands;
  2. the floor is 30 minutes or more, which is the threshold the plan-ahead panel is for;
  3. it uses an UNATTENDED-TIME word, one of planahead's own eight kinds, so "bake for 45 minutes"
     is not a wait and "soak for 8 hours" is;
  4. no wait row on that recipe already covers it, compared by the kind and by overlapping minutes.
"""
import argparse
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from corpus_guard import refuse_live, report_target                          # noqa: E402

CSV_NAME = "notes-only-waits.csv"
FLOOR_MINUTES = 30

# ⚠️ THE KIND WORDS ARE planahead's OWN EIGHT, plus the ordinary inflections a note writes them in.
#    Inventing a wider vocabulary here would hand back candidates the rest of the app has no kind
#    for, and a reviewer would have to decide what they even are before deciding whether to add them.
KIND_WORDS = {
    "marinating": r"marinat\w*",
    "chilling":   r"chill\w*|refrigerat\w*|in the fridge",
    "rising":     r"ris\w*|proof\w*|prove\b|ferment\w*",
    "soaking":    r"soak\w*|steep\w*|hydrat\w*",
    "resting":    r"rest\w*|sit\b|stand\b|settle\w*",
    "freezing":   r"freez\w*|frozen",
    "brining":    r"brin\w*|cure\w*",
}
# ⚠️ STORAGE READS EXACTLY LIKE A WAIT AND IS NOT ONE, which is the thing that makes a naive version
#    of this rule useless. "Chill for 3 days" and "keeps in the fridge for 3 days" both carry a
#    chilling word and a duration; the first is a step the cook waits through and the second is what
#    to do with the leftovers. Measured on the corpus: 12 of the 15 raw hits are storage. They are
#    SEPARATED rather than dropped, and both lists go in the report, because the boundary is a
#    judgement and silently discarding a candidate is how a review list stops being trusted.
STORAGE_PHRASE = re.compile(
    r"\bstor\w*|\bkeeps?\b|\bkeeping\b|\bleftover\w*|\blasts?\b|\bwill last\b|\bairtight\b"
    r"|\bfreezer-safe\b|\bin advance\b|\bthaw\w*|\bmake.ahead\b"
    r"|\bfor up to\b", re.I)

# a duration written in a note, with enough around it to read
DURATION = re.compile(
    r"\b(?:overnight|\d+(?:\s*[–—-]\s*\d+)?\s*(?:min(?:ute)?s?|hours?|hrs?|days?))\b", re.I)


def _sentence_around(text, index):
    """The sentence a duration sits in. Storage and a wait are told apart by the words beside the
    figure, not by the words anywhere in the paragraph: chipotle-black-beans holds both in one
    note."""
    start = max((text.rfind(ch, 0, index) for ch in ".!?\n"), default=-1)
    end = min((p for p in (text.find(ch, index) for ch in ".!?\n") if p != -1), default=len(text))
    return text[start + 1:end + 1]


def _covered(cand_kind, lo, waits):
    """Does a wait row already cover this? Same kind and an overlapping range, or the same kind with
    no figures at all (an 'overnight' row whose floor IS the word)."""
    for w in waits:
        if w["kind"] != cand_kind:
            continue
        wlo, whi = w["min_minutes"], w["max_minutes"]
        if wlo is None:
            return True
        if lo is None:
            return True
        if whi is None:
            if abs(wlo - lo) <= 60:
                return True
        elif wlo - 60 <= lo <= whi + 60:
            return True
    return False


def run(db, record=False):
    import app
    import models
    import notes as notes_rules
    import planahead
    import sqlalchemy
    app.DB = models.DB = pathlib.Path(db)

    rows = []
    with app.orm_session() as s:
        recipes = s.execute(sqlalchemy.text(
            "SELECT id, notes FROM recipes WHERE notes IS NOT NULL AND notes != '' ORDER BY id")).all()
        for rid, text in recipes:
            waits = [dict(w) for w in s.execute(sqlalchemy.text(
                "SELECT kind, min_minutes, max_minutes FROM recipe_waits WHERE recipe_id=:r"),
                {"r": rid}).mappings()]
            # ⚠️ ROWS OR COLUMN, DECIDED PER RECIPE. This read one COUNT over the whole table and
            #    applied the answer to all 300, so once any recipe had rows every recipe was read
            #    from rows, and a recipe whose notes are still only in the column was counted as
            #    having notes and scanned as empty. That is the state every imported recipe was in.
            rows_here = [r[0] for r in s.execute(sqlalchemy.text(
                "SELECT text FROM recipe_notes WHERE recipe_id=:r ORDER BY position"),
                {"r": rid}).all()]
            paras = rows_here if rows_here else notes_rules.paragraphs(text)
            for i, para in enumerate(paras):
                for m in DURATION.finditer(para):
                    lo, hi = planahead.read_duration(m.group(0))
                    if lo is None or lo < FLOOR_MINUTES:
                        continue
                    # the kind word has to sit near the duration, not merely somewhere in the note
                    window = para[max(0, m.start() - 90):m.end() + 90]
                    kind = next((k for k, pat in KIND_WORDS.items()
                                 if re.search(pat, window, re.I)), None)
                    if kind is None:
                        continue
                    if _covered(kind, lo, waits):
                        continue
                    # the sentence the duration sits in, which is what decides wait against storage
                    sentence = _sentence_around(para, m.start())
                    rows.append({
                        "recipe_id": rid, "note_position": i, "kind": kind,
                        "duration": m.group(0), "min_minutes": lo,
                        "max_minutes": hi if hi is not None else "",
                        "reads_as": "storage" if STORAGE_PHRASE.search(sentence) else "wait",
                        "existing_waits": "; ".join(
                            f"{w['kind']} {w['min_minutes']}-{w['max_minutes']}" for w in waits) or "none",
                        "sentence": sentence.strip()[:200],
                        "note": para.replace("\n", " ")[:240],
                    })

    waits_like = [r for r in rows if r["reads_as"] == "wait"]
    storage_like = [r for r in rows if r["reads_as"] == "storage"]
    print(f"  recipes with notes        : {len(recipes)}")
    print(f"  durations found           : {len(rows)}")
    print(f"  of those, read as a WAIT  : {len(waits_like)}")
    for r in waits_like:
        print(f"      {r['recipe_id']:44s} {r['kind']:11s} {r['duration']:16s} "
              f"(existing: {r['existing_waits'][:30]})")
        print(f"          {r['sentence'][:110]}")
    print(f"  of those, read as STORAGE : {len(storage_like)}  (listed in the CSV, not proposed)")
    for r in storage_like:
        print(f"      {r['recipe_id']:44s} {r['duration']}")
    # ⚠️ A RUN THAT FOUND NOTHING WRITES NOTHING. --record on an empty run otherwise put a
    #    header-only file into the committed folder, which is how three records were truncated to
    #    their headers once already (see corpus_guard.report_target).
    if not rows:
        print("  no candidates, so no review list was written.")
        print("  NOTHING WAS WRITTEN. A wait is a judgement; this hands over candidates.")
        return rows
    target = report_target(CSV_NAME, record)
    with open(target, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else
                           ["recipe_id", "note_position", "kind", "duration", "min_minutes",
                            "max_minutes", "existing_waits", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"  review list -> {target}")
    print("  NOTHING WAS WRITTEN. A wait is a judgement; this hands over candidates.")
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
